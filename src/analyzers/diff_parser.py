"""Parse a unified diff string into structured FileChange objects."""
import os
import re
from dataclasses import dataclass, field

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".sh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sql": "sql",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
}

def detect_language(path: str) -> str:
    """Return the markdown fence language identifier for a file path, or empty string."""
    return _EXT_LANG.get(os.path.splitext(path)[1].lower(), "")


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    """One @@ block from a unified diff, with its raw diff lines."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FileChange:
    """All changes for a single file extracted from a unified diff."""

    path: str
    language: str
    added_lines: list[str]
    removed_lines: list[str]
    hunks: list[Hunk]
    is_new_file: bool = False
    is_deleted_file: bool = False


def _detect_language(path: str) -> str:
    if "." not in path:
        return "unknown"
    suffix = "." + path.rsplit(".", 1)[-1].lower()
    return _EXT_LANG.get(suffix, "unknown")


def parse_diff(diff_text: str) -> list[FileChange]:
    """Parse a unified diff string into a list of FileChange objects.

    Handles new files (--- /dev/null), deleted files (+++ /dev/null), and
    standard modifications. Each FileChange includes per-hunk line data with
    positional information needed by the risk scorer.
    """
    changes: list[FileChange] = []
    current: FileChange | None = None
    current_hunk: Hunk | None = None
    pending_new = False
    pending_deleted = False
    pending_old_path = ""

    def _push_hunk() -> None:
        nonlocal current_hunk
        if current is not None and current_hunk is not None:
            current.hunks.append(current_hunk)
            current_hunk = None

    def _push_file() -> None:
        nonlocal current, pending_new, pending_deleted, pending_old_path
        _push_hunk()
        if current is not None:
            changes.append(current)
        current = None
        pending_new = False
        pending_deleted = False
        pending_old_path = ""

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            _push_file()
            continue

        if line.startswith("new file mode"):
            pending_new = True
            continue

        if line.startswith("deleted file mode"):
            pending_deleted = True
            continue

        if line.startswith("--- "):
            raw = line[4:]
            pending_old_path = raw[2:] if raw.startswith("a/") else raw
            if pending_old_path == "/dev/null":
                pending_new = True
            continue

        if line.startswith("+++ "):
            _push_hunk()
            raw = line[4:]
            new_path = raw[2:] if raw.startswith("b/") else raw
            if new_path == "/dev/null":
                pending_deleted = True
                new_path = pending_old_path
            current = FileChange(
                path=new_path,
                language=_detect_language(new_path),
                added_lines=[],
                removed_lines=[],
                hunks=[],
                is_new_file=pending_new,
                is_deleted_file=pending_deleted,
            )
            continue

        if line.startswith("@@") and current is not None:
            _push_hunk()
            m = _HUNK_RE.match(line)
            if m:
                current_hunk = Hunk(
                    old_start=int(m.group(1)),
                    old_count=int(m.group(2) or "1"),
                    new_start=int(m.group(3)),
                    new_count=int(m.group(4) or "1"),
                )
            continue

        if current_hunk is not None and current is not None:
            current_hunk.lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current.added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                current.removed_lines.append(line[1:])

    _push_file()
    return changes
