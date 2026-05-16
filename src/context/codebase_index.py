"""Codebase vector index for semantic similarity search across repo files.

Chunks repo source files by function/class (Python) or sliding window (others),
embeds them with a local fastembed model, and stores them in a sqlite-vec database.
Subsequent runs only re-embed files whose git blob hash changed.
"""
import ast
import logging
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_CHUNK_WINDOW = 60
_CHUNK_OVERLAP = 10
_MAX_FILE_LINES = 2000

_INDEXABLE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".java",
    ".rs", ".c", ".cpp", ".cs", ".php", ".sh",
}

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", "dist", "build", ".mypy_cache", ".ruff_cache",
}


@dataclass
class RelatedChunk:
    """A code chunk retrieved as semantically similar to a query."""

    file_path: str
    label: str
    chunk_text: str
    distance: float


@dataclass
class _Chunk:
    """Internal representation of a code chunk before indexing."""

    file_path: str
    git_hash: str
    label: str
    chunk_text: str
    start_line: int


class CodebaseIndex:
    """Manages a sqlite-vec index of repo code chunks for semantic search.

    On first run, walks the repo, chunks files by function/class, embeds them
    with a local fastembed model, and stores them in index.db. Subsequent runs
    only re-embed files whose git blob hash changed, making incremental updates fast.
    """

    def __init__(self, db_path: str = "index.db", repo_root: str = ".") -> None:
        self._db_path = db_path
        self._repo_root = Path(repo_root).resolve()
        self._model: TextEmbedding | None = None
        self._db: sqlite3.Connection | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            logger.info("Loading embedding model %s (first run downloads weights)", _EMBEDDING_MODEL)
            self._model = TextEmbedding(model_name=_EMBEDDING_MODEL)
        return self._model

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            db = sqlite3.connect(self._db_path)
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            self._db = db
            self._init_schema()
        return self._db

    def _init_schema(self) -> None:
        self._db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                git_hash TEXT NOT NULL,
                label TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                start_line INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS file_hashes (
                file_path TEXT PRIMARY KEY,
                git_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
                USING vec0(embedding float[{_EMBEDDING_DIM}]);
            """
        )
        self._db.commit()

    def build_or_update(self) -> None:
        """Walk the repo and (re-)embed any files whose content changed since last run."""
        db = self._get_db()

        current_files = self._list_repo_files()
        indexed: dict[str, str] = dict(
            db.execute("SELECT file_path, git_hash FROM file_hashes").fetchall()
        )

        to_index: list[tuple[str, str]] = []
        to_remove: list[str] = list(set(indexed) - set(current_files))

        for path, git_hash in current_files.items():
            if path not in indexed or indexed[path] != git_hash:
                to_index.append((path, git_hash))

        if to_remove:
            self._remove_files(to_remove)
            logger.info("Removed %d deleted/untracked files from index", len(to_remove))

        if not to_index:
            logger.info("Index up to date (%d files indexed)", len(current_files))
            return

        logger.info("Indexing %d new/changed files", len(to_index))

        # Remove stale chunks for changed files before re-adding
        changed_paths = [p for p, _ in to_index if p in indexed]
        if changed_paths:
            self._remove_files(changed_paths)

        all_chunks: list[_Chunk] = []
        for path, git_hash in to_index:
            abs_path = self._repo_root / path
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Cannot read %s: %s", path, exc)
                continue
            all_chunks.extend(chunk_file(path, git_hash, text))

        if not all_chunks:
            logger.info("No chunks produced from %d files", len(to_index))
            return

        model = self._get_model()
        texts = [c.chunk_text for c in all_chunks]
        embeddings = list(model.embed(texts))

        for chunk, embedding in zip(all_chunks, embeddings):
            row = db.execute(
                "INSERT INTO chunks (file_path, git_hash, label, chunk_text, start_line)"
                " VALUES (?, ?, ?, ?, ?)",
                (chunk.file_path, chunk.git_hash, chunk.label, chunk.chunk_text, chunk.start_line),
            )
            chunk_id = row.lastrowid
            emb_bytes = sqlite_vec.serialize_float32(embedding.tolist())
            db.execute(
                "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                (chunk_id, emb_bytes),
            )

        for path, git_hash in to_index:
            db.execute(
                "INSERT OR REPLACE INTO file_hashes (file_path, git_hash) VALUES (?, ?)",
                (path, git_hash),
            )

        db.commit()
        logger.info("Indexed %d chunks from %d files", len(all_chunks), len(to_index))

    def query(
        self,
        text: str,
        exclude_paths: set[str] | None = None,
        top_k: int = 5,
    ) -> list[RelatedChunk]:
        """Find top-k chunks semantically similar to *text*, skipping *exclude_paths*."""
        db = self._get_db()

        model = self._get_model()
        embedding = next(iter(model.embed([text])))
        emb_bytes = sqlite_vec.serialize_float32(embedding.tolist())

        # Fetch extra rows to cover filtered-out excluded paths, capped to avoid over-fetching
        fetch_k = min(top_k + (len(exclude_paths) * 3 if exclude_paths else 0) + 20, top_k + 100)

        # sqlite-vec requires k = ? in the WHERE clause for knn queries
        rows = db.execute(
            """
            SELECT c.file_path, c.label, c.chunk_text, v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.id = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (emb_bytes, fetch_k),
        ).fetchall()

        results: list[RelatedChunk] = []
        for file_path, label, chunk_text, distance in rows:
            if exclude_paths and file_path in exclude_paths:
                continue
            results.append(
                RelatedChunk(
                    file_path=file_path,
                    label=label,
                    chunk_text=chunk_text,
                    distance=distance,
                )
            )
            if len(results) >= top_k:
                break

        return results

    def _remove_files(self, paths: list[str]) -> None:
        db = self._get_db()
        for path in paths:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM chunks WHERE file_path = ?", (path,)
                ).fetchall()
            ]
            for chunk_id in ids:
                db.execute("DELETE FROM vec_chunks WHERE rowid = ?", (chunk_id,))
            db.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
            db.execute("DELETE FROM file_hashes WHERE file_path = ?", (path,))

    def _list_repo_files(self) -> dict[str, str]:
        """Return {relative_path: git_blob_hash} for all indexable tracked files."""
        try:
            result = subprocess.run(
                ["git", "ls-files", "-s"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("git ls-files failed; falling back to directory scan")
            return _scan_directory(self._repo_root)

        files: dict[str, str] = {}
        for line in result.stdout.splitlines():
            # format: <mode> <hash> <stage>\t<path>
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                git_hash = parts[0].split()[1]
            except IndexError:
                continue
            path = parts[1]
            if is_indexable(path):
                files[path] = git_hash

        return files


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions — unit-testable without the class)
# ---------------------------------------------------------------------------


def is_indexable(path: str) -> bool:
    """Return True if this file path should be included in the codebase index."""
    p = Path(path)
    if any(part in _SKIP_DIRS for part in p.parts):
        return False
    return p.suffix.lower() in _INDEXABLE_EXTS


def chunk_file(file_path: str, git_hash: str, text: str) -> list[_Chunk]:
    """Split a source file into indexable chunks.

    Uses AST-based function/method chunking for Python files; falls back to a
    sliding-window strategy for all other languages.
    """
    if file_path.endswith(".py"):
        chunks = chunk_python(file_path, git_hash, text)
        if chunks:
            return chunks
    return chunk_window(file_path, git_hash, text)


def chunk_python(file_path: str, git_hash: str, text: str) -> list[_Chunk]:
    """Chunk a Python file by top-level functions and class methods."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines()
    chunks: list[_Chunk] = []

    def _extract(node: ast.AST, prefix: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            end = node.end_lineno or (start + 1)
            body = "\n".join(lines[start:end])
            label = f"{prefix}{node.name}" if prefix else node.name
            chunks.append(
                _Chunk(
                    file_path=file_path,
                    git_hash=git_hash,
                    label=label,
                    chunk_text=body,
                    start_line=node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            class_prefix = f"{node.name}."
            for child in node.body:
                _extract(child, prefix=class_prefix)

    for node in tree.body:
        _extract(node)

    return chunks


def chunk_window(file_path: str, git_hash: str, text: str) -> list[_Chunk]:
    """Chunk a file with a sliding window of lines."""
    lines = text.splitlines()
    if not lines:
        return []

    if len(lines) > _MAX_FILE_LINES:
        lines = lines[:_MAX_FILE_LINES]

    step = max(1, _CHUNK_WINDOW - _CHUNK_OVERLAP)
    chunks: list[_Chunk] = []

    for start in range(0, len(lines), step):
        end = min(start + _CHUNK_WINDOW, len(lines))
        body = "\n".join(lines[start:end])
        label = f"lines {start + 1}-{end}"
        chunks.append(
            _Chunk(
                file_path=file_path,
                git_hash=git_hash,
                label=label,
                chunk_text=body,
                start_line=start + 1,
            )
        )

    return chunks


def _scan_directory(repo_root: Path) -> dict[str, str]:
    """Fallback: scan directory and hash file contents when git is unavailable."""
    import hashlib

    files: dict[str, str] = {}
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in filenames:
            abs_path = Path(root) / filename
            rel_path = str(abs_path.relative_to(repo_root))
            if not is_indexable(rel_path):
                continue
            try:
                content = abs_path.read_bytes()
                content_hash = hashlib.sha1(content).hexdigest()
                files[rel_path] = content_hash
            except OSError:
                continue

    return files
