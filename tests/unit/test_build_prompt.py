"""Tests for cli._build_prompt — the structured context assembler."""
from src.analyzers.diff_parser import FileChange, Hunk
from src.analyzers.risk_scorer import RiskFlag
from src.cli import _build_prompt


def _make_change(
    path: str = "src/foo.py",
    language: str = "python",
    added: list[str] | None = None,
    removed: list[str] | None = None,
    is_new: bool = False,
    is_deleted: bool = False,
) -> FileChange:
    return FileChange(
        path=path,
        language=language,
        added_lines=added or [],
        removed_lines=removed or [],
        hunks=[],
        is_new_file=is_new,
        is_deleted_file=is_deleted,
    )


def test_file_path_and_language_appear():
    changes = [_make_change(path="src/auth.py", language="python", added=["x"])]
    prompt = _build_prompt(changes, {}, [])
    assert "src/auth.py" in prompt
    assert "python" in prompt


def test_new_and_deleted_labels():
    changes = [
        _make_change(path="src/new.py", is_new=True),
        _make_change(path="src/old.py", is_deleted=True),
    ]
    prompt = _build_prompt(changes, {}, [])
    assert "new file" in prompt
    assert "deleted" in prompt


def test_symbols_included_when_present():
    changes = [_make_change()]
    symbols = {"src/foo.py": ["do_thing", "helper"]}
    prompt = _build_prompt(changes, symbols, [])
    assert "do_thing" in prompt
    assert "helper" in prompt


def test_risk_flag_with_line_number():
    changes = [_make_change()]
    flags = [RiskFlag(flag="modifies_auth", file="src/foo.py", line=42, snippet="token = req.headers")]
    prompt = _build_prompt(changes, {}, flags)
    assert "modifies_auth" in prompt
    assert ":42" in prompt
    assert "token = req.headers" in prompt


def test_risk_flag_without_line_number():
    changes = [_make_change()]
    flags = [RiskFlag(flag="touches_migration", file="migrations/001.sql", line=None, snippet="migrations/001.sql")]
    prompt = _build_prompt(changes, {}, flags)
    assert "touches_migration" in prompt
    assert "migrations/001.sql" in prompt


def test_no_flags_shows_none():
    changes = [_make_change()]
    prompt = _build_prompt(changes, {}, [])
    assert "None detected." in prompt


def test_line_counts_appear():
    changes = [_make_change(added=["a", "b", "c"], removed=["x"])]
    prompt = _build_prompt(changes, {}, [])
    assert "+3" in prompt
    assert "-1" in prompt


def test_instructions_always_present():
    prompt = _build_prompt([], {}, [])
    assert "terse" in prompt.lower() or "instructions" in prompt.lower()
