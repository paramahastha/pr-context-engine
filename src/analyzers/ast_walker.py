"""Extract names of changed functions and classes from a FileChange.

Uses Python's `ast` module for Python files and language-specific regexes
for JavaScript, TypeScript, and Go. Falls back to a generic regex for unknown
languages. Only lines that appear in the diff (added or removed) are scanned —
we report which named symbols were touched, not a full symbol table.
"""
import ast
import logging
import re

from src.analyzers.diff_parser import FileChange

logger = logging.getLogger(__name__)

# Patterns keyed by language; each pattern has one capturing group: the symbol name.
_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ],
    "javascript": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        re.compile(r"^(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        re.compile(
            r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
            r"\s*=\s*(?:async\s+)?(?:function|\()"
        ),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]+\)\s+)?([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct"),
    ],
}
_PATTERNS["typescript"] = _PATTERNS["javascript"]


def _names_via_regex(lines: list[str], language: str) -> list[str]:
    patterns = _PATTERNS.get(language, [])
    names: list[str] = []
    for line in lines:
        stripped = line.strip()
        for pat in patterns:
            m = pat.match(stripped)
            if m:
                names.append(m.group(1))
                break
    return names


def _names_via_ast(lines: list[str]) -> list[str]:
    """Try to parse Python lines as a module and extract def/class names at any depth.

    Returns an empty list on any parse failure — the caller falls back to regex.
    """
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def extract_changed_symbols(change: FileChange) -> list[str]:
    """Return deduplicated names of functions/classes touched in this file's diff.

    Combines names found in both added and removed lines so the caller knows
    which symbols were modified (added, changed, or deleted).
    """
    all_lines = change.added_lines + change.removed_lines

    names: list[str] = []
    if change.language == "python":
        names = _names_via_ast(all_lines)
        if not names:
            names = _names_via_regex(all_lines, "python")
    else:
        names = _names_via_regex(all_lines, change.language)

    # preserve order while deduplicating
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique
