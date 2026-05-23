"""Unit tests for codebase_index chunking helpers and CodebaseIndex.

Tests cover the pure chunking functions (no DB, no embedding model) and a
lightweight integration test that exercises build_or_update + query against
a temp directory with a mocked embedding model.
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.context.codebase_index import (
    CodebaseIndex,
    chunk_file,
    chunk_python,
    chunk_window,
    is_indexable,
)


# ---------------------------------------------------------------------------
# is_indexable
# ---------------------------------------------------------------------------


def test_is_indexable_accepts_python():
    assert is_indexable("src/foo.py") is True


def test_is_indexable_accepts_typescript():
    assert is_indexable("frontend/app.ts") is True


def test_is_indexable_rejects_markdown():
    assert is_indexable("README.md") is False


def test_is_indexable_rejects_pycache():
    assert is_indexable("src/__pycache__/foo.cpython-312.pyc") is False


def test_is_indexable_rejects_node_modules():
    assert is_indexable("node_modules/lodash/index.js") is False


def test_is_indexable_rejects_venv():
    assert is_indexable(".venv/lib/python3.12/site-packages/foo.py") is False


# ---------------------------------------------------------------------------
# chunk_window
# ---------------------------------------------------------------------------


def test_chunk_window_empty_file():
    assert chunk_window("x.go", "abc", "") == []


def test_chunk_window_small_file():
    text = "\n".join(f"line {i}" for i in range(10))
    chunks = chunk_window("x.go", "abc", text)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].label == "lines 1-10"
    assert chunks[0].file_path == "x.go"
    assert chunks[0].git_hash == "abc"


def test_chunk_window_multiple_chunks():
    # 70 lines → should produce at least 2 chunks with default window=60/overlap=10
    text = "\n".join(f"line {i}" for i in range(70))
    chunks = chunk_window("x.go", "h", text)
    assert len(chunks) >= 2
    # All chunks reference the same file
    assert all(c.file_path == "x.go" for c in chunks)


def test_chunk_window_caps_at_max_lines():
    # 3000 lines — should be capped at _MAX_FILE_LINES (2000)
    text = "\n".join(f"line {i}" for i in range(3000))
    chunks = chunk_window("big.go", "h", text)
    # The last chunk must not start beyond the cap
    assert chunks[-1].start_line <= 2000


# ---------------------------------------------------------------------------
# chunk_python
# ---------------------------------------------------------------------------


_PYTHON_SOURCE = '''\
def standalone():
    return 42

class MyClass:
    def method_a(self):
        pass

    def method_b(self, x: int) -> int:
        return x * 2

async def async_func():
    await something()
'''


def test_chunk_python_finds_functions():
    chunks = chunk_python("mod.py", "h", _PYTHON_SOURCE)
    labels = {c.label for c in chunks}
    assert "standalone" in labels
    assert "async_func" in labels


def test_chunk_python_finds_methods():
    chunks = chunk_python("mod.py", "h", _PYTHON_SOURCE)
    labels = {c.label for c in chunks}
    assert "MyClass.method_a" in labels
    assert "MyClass.method_b" in labels


def test_chunk_python_no_class_level_duplicate():
    # The class itself should NOT appear as a chunk — only its methods
    chunks = chunk_python("mod.py", "h", _PYTHON_SOURCE)
    labels = {c.label for c in chunks}
    assert "MyClass" not in labels


def test_chunk_python_syntax_error_returns_empty():
    assert chunk_python("bad.py", "h", "def (") == []


def test_chunk_python_empty_file():
    assert chunk_python("empty.py", "h", "") == []


def test_chunk_python_start_line():
    chunks = chunk_python("mod.py", "h", _PYTHON_SOURCE)
    standalone = next(c for c in chunks if c.label == "standalone")
    assert standalone.start_line == 1


# ---------------------------------------------------------------------------
# chunk_file dispatch
# ---------------------------------------------------------------------------


def test_chunk_file_dispatches_python():
    chunks = chunk_file("src/foo.py", "h", _PYTHON_SOURCE)
    labels = {c.label for c in chunks}
    assert "standalone" in labels  # AST path taken


def test_chunk_file_dispatches_window_for_go():
    text = "\n".join(f"line {i}" for i in range(10))
    chunks = chunk_file("main.go", "h", text)
    assert chunks
    assert chunks[0].label.startswith("lines")


def test_chunk_file_falls_back_to_window_on_bad_python():
    # If Python parse fails, chunk_file should use the window fallback
    bad_python = "def (\n" + "\n".join(f"line {i}" for i in range(5))
    chunks = chunk_file("broken.py", "h", bad_python)
    assert chunks
    assert chunks[0].label.startswith("lines")


# ---------------------------------------------------------------------------
# CodebaseIndex integration (mocked embedding model)
# ---------------------------------------------------------------------------


def _make_index(tmp_path: Path) -> CodebaseIndex:
    db_path = str(tmp_path / "test.db")
    index = CodebaseIndex(db_path=db_path, repo_root=str(tmp_path))
    return index


def _fake_embed(texts):
    """Return deterministic 384-dim unit vectors based on text length."""
    for text in texts:
        vec = np.zeros(384, dtype=np.float32)
        vec[len(text) % 384] = 1.0
        yield vec


@pytest.fixture()
def repo_with_files(tmp_path: Path):
    """Create a small fake repo with two Python files."""
    (tmp_path / "alpha.py").write_text(
        "def alpha_func():\n    return 'alpha'\n", encoding="utf-8"
    )
    (tmp_path / "beta.py").write_text(
        "def beta_func():\n    return 'beta'\n", encoding="utf-8"
    )
    return tmp_path


@patch("src.context.codebase_index.TextEmbedding")
@patch("src.context.codebase_index.subprocess.run")
def test_build_or_update_indexes_files(mock_run, MockEmbedding, repo_with_files):
    # git ls-files -s returns two files
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=(
            "100644 aaaa0000 0\talpha.py\n"
            "100644 bbbb0000 0\tbeta.py\n"
        ),
    )
    instance = MockEmbedding.return_value
    instance.embed.side_effect = _fake_embed

    index = _make_index(repo_with_files)
    index.build_or_update()

    db = sqlite3.connect(str(repo_with_files / "test.db"))
    count = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert count >= 2  # at least one chunk per file


@patch("src.context.codebase_index.TextEmbedding")
@patch("src.context.codebase_index.subprocess.run")
def test_build_or_update_skips_unchanged(mock_run, MockEmbedding, repo_with_files):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="100644 aaaa0000 0\talpha.py\n100644 bbbb0000 0\tbeta.py\n",
    )
    instance = MockEmbedding.return_value
    instance.embed.side_effect = _fake_embed

    index = _make_index(repo_with_files)
    index.build_or_update()
    first_call_count = instance.embed.call_count

    # Second build_or_update with same hashes → no new embedding calls
    index2 = _make_index(repo_with_files)
    index2.build_or_update()
    assert instance.embed.call_count == first_call_count


@patch("src.context.codebase_index.TextEmbedding")
@patch("src.context.codebase_index.subprocess.run")
def test_query_returns_results(mock_run, MockEmbedding, repo_with_files):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="100644 aaaa0000 0\talpha.py\n100644 bbbb0000 0\tbeta.py\n",
    )
    instance = MockEmbedding.return_value
    instance.embed.side_effect = _fake_embed

    index = _make_index(repo_with_files)
    index.build_or_update()

    results = index.query("alpha function", top_k=5)
    assert isinstance(results, list)
    # At least one result should come back
    assert len(results) >= 1


@patch("src.context.codebase_index.TextEmbedding")
@patch("src.context.codebase_index.subprocess.run")
def test_query_excludes_paths(mock_run, MockEmbedding, repo_with_files):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="100644 aaaa0000 0\talpha.py\n100644 bbbb0000 0\tbeta.py\n",
    )
    instance = MockEmbedding.return_value
    instance.embed.side_effect = _fake_embed

    index = _make_index(repo_with_files)
    index.build_or_update()

    # Exclude alpha.py — results should only come from beta.py
    results = index.query("function", exclude_paths={"alpha.py"}, top_k=5)
    assert len(results) >= 1
    for chunk in results:
        assert chunk.file_path != "alpha.py"
