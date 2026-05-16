"""Unit tests for src/fixes/fix_generator.py, src/fixes/confidence.py, and format_fix_section."""
from unittest.mock import MagicMock

import pytest

from src.analyzers.diff_parser import FileChange, Hunk
from src.analyzers.risk_scorer import RiskFlag
from src.fixes.confidence import (
    format_prose_note,
    format_suggestion_block,
    is_block_eligible,
)
from src.fixes.fix_generator import (
    FixSuggestion,
    _build_fix_prompt,
    _get_flag_context,
    _parse_fix_response,
    generate_fixes,
)
from src.github_api.comment_poster import format_fix_section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hunk(old_start: int, new_start: int, lines: list[str]) -> Hunk:
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return Hunk(
        old_start=old_start,
        old_count=removed,
        new_start=new_start,
        new_count=added,
        lines=lines,
    )


def _change(path: str, hunks: list[Hunk], language: str = "python") -> FileChange:
    added = [l[1:] for h in hunks for l in h.lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for h in hunks for l in h.lines if l.startswith("-") and not l.startswith("---")]
    return FileChange(
        path=path,
        language=language,
        added_lines=added,
        removed_lines=removed,
        hunks=hunks,
    )


def _flag(flag: str, file: str, line: int | None, snippet: str = "code") -> RiskFlag:
    return RiskFlag(flag=flag, file=file, line=line, snippet=snippet)


def _provider(response: str) -> MagicMock:
    mock = MagicMock()
    mock.generate.return_value = response
    return mock


# ---------------------------------------------------------------------------
# _get_flag_context
# ---------------------------------------------------------------------------


def test_get_flag_context_finds_matching_hunk():
    hunk = _hunk(1, 10, [" ctx", "+token = headers.get('Authorization')", " end"])
    change = _change("src/auth.py", [hunk])
    flag = _flag("modifies_auth", "src/auth.py", 10)

    ctx = _get_flag_context(flag, [change])

    assert "+token = headers.get('Authorization')" in ctx


def test_get_flag_context_falls_back_to_snippet_when_no_hunk():
    change = _change("src/auth.py", [])
    flag = _flag("modifies_auth", "src/auth.py", 99, snippet="fallback_snippet")

    ctx = _get_flag_context(flag, [change])

    assert ctx == "fallback_snippet"


def test_get_flag_context_falls_back_when_file_not_in_changes():
    flag = _flag("modifies_auth", "src/other.py", 5, snippet="other_snippet")
    ctx = _get_flag_context(flag, [])
    assert ctx == "other_snippet"


def test_get_flag_context_old_file_range_matched():
    # deletes_public_api uses old-file line numbers
    hunk = _hunk(old_start=20, new_start=20, lines=["-def old_func():", "-    pass"])
    change = _change("src/api.py", [hunk])
    flag = _flag("deletes_public_api", "src/api.py", 20)

    ctx = _get_flag_context(flag, [change])

    assert "-def old_func():" in ctx


# ---------------------------------------------------------------------------
# _build_fix_prompt
# ---------------------------------------------------------------------------


def test_build_fix_prompt_includes_flag_info():
    flag = _flag("modifies_auth", "src/auth.py", 42, snippet="token = raw")
    prompt = _build_fix_prompt(flag, "context lines here")

    assert "modifies_auth" in prompt
    assert "src/auth.py" in prompt
    assert "42" in prompt
    assert "token = raw" in prompt
    assert "context lines here" in prompt


def test_build_fix_prompt_includes_system_instructions():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    prompt = _build_fix_prompt(flag, "ctx")

    # FIX_SYSTEM_PROMPT is prepended
    assert "CONFIDENCE" in prompt
    assert "RATIONALE" in prompt
    assert "PATCH" in prompt


# ---------------------------------------------------------------------------
# _parse_fix_response
# ---------------------------------------------------------------------------


def test_parse_high_confidence_with_patch():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = (
        "CONFIDENCE: high\n"
        "RATIONALE: Token stored in plain text.\n"
        "PATCH:\n"
        "token = hash_token(headers.get('Authorization'))\n"
    )

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.confidence == "high"
    assert suggestion.rationale == "Token stored in plain text."
    assert suggestion.patch is not None
    assert "hash_token" in suggestion.patch


def test_parse_medium_confidence_with_patch():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = "CONFIDENCE: medium\nRATIONALE: Possible issue.\nPATCH:\nfixed_line()\n"

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.confidence == "medium"
    assert suggestion.patch == "fixed_line()"


def test_parse_low_confidence_nulls_patch():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = (
        "CONFIDENCE: low\n"
        "RATIONALE: Cannot determine correct fix.\n"
        "PATCH:\nNO_PATCH\n"
    )

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.confidence == "low"
    assert suggestion.patch is None


def test_parse_low_confidence_nulls_patch_even_if_llm_emits_one():
    # Enforce the hard rule: low confidence must never carry a patch.
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = "CONFIDENCE: low\nRATIONALE: Unsure.\nPATCH:\nsome_code()\n"

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.patch is None


def test_parse_no_patch_keyword_sets_none():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = "CONFIDENCE: medium\nRATIONALE: Risky.\nPATCH:\nNO_PATCH\n"

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.patch is None


def test_parse_missing_sections_defaults_to_low():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    response = "some unexpected response"

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.confidence == "low"
    assert suggestion.patch is None


def test_parse_uses_snippet_as_fallback_rationale():
    flag = _flag("modifies_auth", "src/auth.py", 5, snippet="my_snippet")
    response = "CONFIDENCE: low\n"

    suggestion = _parse_fix_response(flag, response)

    assert suggestion.rationale == "my_snippet"


# ---------------------------------------------------------------------------
# generate_fixes — cap and eligible filtering
# ---------------------------------------------------------------------------


def test_generate_fixes_skips_flags_without_line():
    flag_no_line = _flag("touches_migration", "migrations/001.sql", None)
    flag_with_line = _flag("modifies_auth", "src/auth.py", 10)

    response = "CONFIDENCE: high\nRATIONALE: Fix auth.\nPATCH:\nfixed()\n"
    provider = _provider(response)

    suggestions, extra = generate_fixes(provider, [flag_no_line, flag_with_line], [])

    assert len(suggestions) == 1
    assert suggestions[0].flag.flag == "modifies_auth"
    assert extra == 0


def test_generate_fixes_caps_at_three():
    flags = [_flag("modifies_auth", f"src/f{i}.py", i) for i in range(5)]
    provider = _provider("CONFIDENCE: high\nRATIONALE: r\nPATCH:\nfixed()\n")

    suggestions, extra = generate_fixes(provider, flags, [], max_fixes=3)

    assert len(suggestions) == 3
    assert extra == 2


def test_generate_fixes_returns_all_when_under_cap():
    flags = [_flag("modifies_auth", "src/auth.py", 1), _flag("modifies_auth", "src/api.py", 2)]
    provider = _provider("CONFIDENCE: medium\nRATIONALE: r\nPATCH:\nfixed()\n")

    suggestions, extra = generate_fixes(provider, flags, [])

    assert len(suggestions) == 2
    assert extra == 0


def test_generate_fixes_handles_provider_error_gracefully():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("API down")

    suggestions, extra = generate_fixes(provider, [flag], [])

    assert len(suggestions) == 1
    assert suggestions[0].confidence == "low"
    assert suggestions[0].patch is None


# ---------------------------------------------------------------------------
# is_block_eligible (confidence.py)
# ---------------------------------------------------------------------------


def test_high_confidence_with_patch_is_eligible():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="high")
    assert is_block_eligible(suggestion) is True


def test_medium_confidence_with_patch_is_eligible():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="medium")
    assert is_block_eligible(suggestion) is True


def test_low_confidence_not_eligible():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch=None, rationale="r", confidence="low")
    assert is_block_eligible(suggestion) is False


def test_high_confidence_without_patch_not_eligible():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch=None, rationale="r", confidence="high")
    assert is_block_eligible(suggestion) is False


# ---------------------------------------------------------------------------
# format_suggestion_block / format_prose_note (confidence.py)
# ---------------------------------------------------------------------------


def test_format_suggestion_block_contains_details_tag():
    flag = _flag("modifies_auth", "src/auth.py", 42)
    suggestion = FixSuggestion(flag=flag, patch="fixed()", rationale="Hash the token.", confidence="high")

    block = format_suggestion_block(suggestion)

    assert "<details>" in block
    assert "</details>" in block
    assert "fixed()" in block
    assert "Hash the token." in block
    assert "src/auth.py:42" in block


def test_format_suggestion_block_uses_language_fenced_block():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="x = 1", rationale="r", confidence="medium")

    block = format_suggestion_block(suggestion)

    assert "```python" in block
    assert "```suggestion" not in block


def test_format_prose_note_no_code_block():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    suggestion = FixSuggestion(flag=flag, patch=None, rationale="Cannot determine fix.", confidence="low")

    note = format_prose_note(suggestion)

    assert "```" not in note
    assert "Cannot determine fix." in note
    assert "src/auth.py:5" in note


def test_format_prose_note_shows_confidence():
    flag = _flag("modifies_auth", "src/auth.py", 5)
    suggestion = FixSuggestion(flag=flag, patch=None, rationale="r", confidence="low")

    note = format_prose_note(suggestion)

    assert "low" in note


# ---------------------------------------------------------------------------
# format_fix_section (comment_poster.py)
# ---------------------------------------------------------------------------


def test_format_fix_section_returns_empty_when_no_suggestions():
    assert format_fix_section([]) == ""


def test_format_fix_section_includes_heading():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="high")

    section = format_fix_section([suggestion])

    assert "Fix Suggestions" in section


def test_format_fix_section_extra_count_plural():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="high")

    section = format_fix_section([suggestion], extra_count=2)

    assert "2 more issues" in section


def test_format_fix_section_extra_count_singular():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="high")

    section = format_fix_section([suggestion], extra_count=1)

    assert "1 more issue" in section


def test_format_fix_section_no_trailing_note_when_extra_is_zero():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    suggestion = FixSuggestion(flag=flag, patch="fix()", rationale="r", confidence="high")

    section = format_fix_section([suggestion], extra_count=0)

    assert "more issue" not in section


def test_format_fix_section_mix_eligible_and_ineligible():
    flag = _flag("modifies_auth", "src/auth.py", 1)
    high = FixSuggestion(flag=flag, patch="fix()", rationale="Hash it.", confidence="high")
    low = FixSuggestion(flag=flag, patch=None, rationale="Unsure.", confidence="low")

    section = format_fix_section([high, low])

    assert "<details>" in section
    assert "Unsure." in section
