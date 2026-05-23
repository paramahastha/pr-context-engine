"""Heuristic risk-flag detection over parsed diff changes.

Each flag is a located issue object carrying enough information for Milestone 8's
fix generator: which file, which line (or None when a specific line doesn't apply),
and a short snippet. Flags where `line` is None are briefing-only and never fix-eligible.
"""
import re
from dataclasses import dataclass
from pathlib import Path

from src.analyzers.diff_parser import FileChange

_AUTH_RE = re.compile(
    # Use letter-only boundaries so compound names like auth_token / AUTH_SECRET match.
    r"(?<![a-zA-Z])(auth|token|password|secret|permission|credential|api_key|apikey)(?![a-zA-Z])",
    re.IGNORECASE,
)

# Top-level function/method definition patterns for public-API deletion detection.
# We only match lines with no leading whitespace (top-level scope).
_FUNC_DEF_RE = re.compile(
    r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"  # Python
    r"|^func\s+(?:\([^)]+\)\s+)?([A-Za-z_][A-Za-z0-9_]*)"  # Go
    r"|^export\s+(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)"  # JS/TS named function
    r"|^export\s+(?:const|let)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?\("  # JS/TS arrow
)

_MIGRATION_MARKERS = ("migrations/", "alembic/", "alembic_migrations/")

# Lines that look auth-related by keyword but carry no real risk:
# - comment lines (//  #  /*  *  <!--)
# - bare type/struct/class/interface declarations
_COMMENT_LINE_RE = re.compile(r"^\s*(?://|/\*|\*+/?\s|#|<!--)")
_TYPE_DECL_RE = re.compile(
    r"^\s*type\s+\w+\s+(?:struct|interface)\b"  # Go struct/interface
    r"|^\s*type\s+\w+\s*(?:=|\b(?:int|string|float|bool)\b)"  # Go type alias/definition
    r"|^\s*(?:class|interface)\s+\w+"  # Python / JS / TS
)

_LARGE_NEW_FILE_THRESHOLD = 300  # added lines; new files above this warrant explicit review


@dataclass
class RiskFlag:
    """A located risk signal from heuristic analysis of a diff.

    `line` is the line number in the relevant file version:
      - new-file line for `modifies_auth` (the code being added)
      - old-file line for `deletes_public_api` (where the definition existed)
      - None for whole-file flags (`touches_migration`, `changes_config`)
    """

    flag: str
    file: str
    line: int | None
    snippet: str


def _is_migration(path: str) -> bool:
    lower = path.lower()
    return any(m in lower for m in _MIGRATION_MARKERS) or lower.endswith(".sql")


def _is_config(path: str) -> bool:
    """True for .env*, config.*, or *.yaml/yml files at the repo root."""
    name = Path(path).name.lower()
    parts = path.replace("\\", "/").split("/")
    at_root = len(parts) == 1

    if name.startswith(".env"):
        return True
    if name.startswith("config.") and at_root:
        return True
    if name.endswith((".yaml", ".yml")) and at_root:
        return True
    return False


def _dedup_flags(flags: list[RiskFlag]) -> list[RiskFlag]:
    """Deduplicate flags where one occurrence per file is enough.

    modifies_auth fires once per matching line and can produce dozens of hits
    in a large file (e.g. a new store implementation).  Keeping only the first
    match per file preserves the signal while eliminating fix-suggestion spam.
    Other flag types are kept as-is because each occurrence is independently
    meaningful (e.g. multiple deletes_public_api deletions).
    """
    seen_auth_files: set[str] = set()
    result: list[RiskFlag] = []
    for flag in flags:
        if flag.flag == "modifies_auth":
            if flag.file in seen_auth_files:
                continue
            seen_auth_files.add(flag.file)
        result.append(flag)
    return result


def score(changes: list[FileChange]) -> list[RiskFlag]:
    """Return all risk flags detected across the list of file changes."""
    flags: list[RiskFlag] = []

    for change in changes:
        if _is_migration(change.path):
            flags.append(
                RiskFlag(flag="touches_migration", file=change.path, line=None, snippet=change.path)
            )

        if _is_config(change.path):
            flags.append(
                RiskFlag(flag="changes_config", file=change.path, line=None, snippet=change.path)
            )

        if change.is_new_file and len(change.added_lines) >= _LARGE_NEW_FILE_THRESHOLD:
            flags.append(
                RiskFlag(
                    flag="large_new_file",
                    file=change.path,
                    line=None,
                    snippet=f"{len(change.added_lines)} lines added — review for correctness and completeness",
                )
            )

        for hunk in change.hunks:
            new_lineno = hunk.new_start
            old_lineno = hunk.old_start

            for raw in hunk.lines:
                if raw.startswith("+") and not raw.startswith("+++"):
                    content = raw[1:]
                    stripped = content.strip()
                    if _COMMENT_LINE_RE.match(stripped) or _TYPE_DECL_RE.match(stripped):
                        new_lineno += 1
                        continue
                    if _AUTH_RE.search(content):
                        flags.append(
                            RiskFlag(
                                flag="modifies_auth",
                                file=change.path,
                                line=new_lineno,
                                snippet=content.strip()[:200],
                            )
                        )
                    new_lineno += 1

                elif raw.startswith("-") and not raw.startswith("---"):
                    content = raw[1:]
                    # Only flag top-level (no leading whitespace) function removals
                    if not content[:1].isspace():
                        m = _FUNC_DEF_RE.match(content)
                        if m:
                            flags.append(
                                RiskFlag(
                                    flag="deletes_public_api",
                                    file=change.path,
                                    line=old_lineno,
                                    snippet=content.strip()[:200],
                                )
                            )
                    old_lineno += 1

                else:
                    # context line — advances both counters
                    new_lineno += 1
                    old_lineno += 1

    return _dedup_flags(flags)
