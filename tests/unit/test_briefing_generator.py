"""Tests for briefing.generator — structured briefing generation with senior-voice prompting."""
from unittest.mock import MagicMock

from src.analyzers.diff_parser import FileChange
from src.analyzers.risk_scorer import RiskFlag
from src.briefing.generator import Briefing, generate_briefing, _parse_sections


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


def test_generate_briefing_with_mock_provider():
    """Test that generate_briefing calls provider and returns Briefing."""
    mock_provider = MagicMock()
    mock_provider.generate.return_value = (
        "1. WHAT CHANGED\nAdded authentication middleware.\n"
        "2. BLAST RADIUS\nAll HTTP handlers.\n"
        "3. RISK FLAGS\n- Auth changes\n"
        "4. QUESTIONS\n1. Does this handle edge cases?\n2. What about performance?\n3. Tested?"
    )

    changes = [_make_change(path="src/auth.py", added=["middleware"])]
    symbols = {"src/auth.py": ["auth_middleware"]}
    flags = [RiskFlag(flag="modifies_auth", file="src/auth.py", line=10, snippet="token_validation")]

    briefing = generate_briefing(mock_provider, changes, symbols, flags)

    assert isinstance(briefing, Briefing)
    assert "Added authentication" in briefing.what_changed
    assert "All HTTP handlers" in briefing.blast_radius
    assert "Auth changes" in briefing.risk_flags
    assert "edge cases" in briefing.questions
    mock_provider.generate.assert_called_once()


def test_parse_sections_numbered():
    """Test parsing of numbered sections from LLM response."""
    response = (
        "1. WHAT CHANGED\nThis PR adds database pooling.\n\n"
        "2. BLAST RADIUS\nDatabases queries across all services.\n\n"
        "3. RISK FLAGS\n- performance_critical\n- schema_change\n\n"
        "4. QUESTIONS\n"
        "1. Why this library?\n"
        "2. Connection limits set correctly?\n"
        "3. Backward compatible?"
    )

    sections = _parse_sections(response)

    assert "adds database pooling" in sections["what_changed"]
    assert "across all services" in sections["blast_radius"]
    assert "performance_critical" in sections["risk_flags"]
    assert "Why this library" in sections["questions"]


def test_parse_sections_with_extra_content():
    """Test parsing handles extra text gracefully."""
    response = (
        "Here's my analysis:\n\n"
        "1. WHAT CHANGED\nAdded caching layer.\n\n"
        "2. BLAST RADIUS\nSelf-contained.\n\n"
        "3. RISK FLAGS\nNone.\n\n"
        "4. QUESTIONS\n1. Test coverage?\n2. Invalidation strategy?"
    )

    sections = _parse_sections(response)

    assert "caching" in sections["what_changed"]
    assert "Self-contained" in sections["blast_radius"]


def test_prompt_includes_file_metadata():
    """Test that _assemble_prompt includes file change information."""
    from src.briefing.generator import _assemble_prompt

    changes = [
        _make_change(path="src/auth.py", added=["line1", "line2"], removed=["oldline"]),
        _make_change(path="tests/test.py", is_new=True, added=["test1", "test2", "test3"]),
    ]
    symbols = {"src/auth.py": ["validate_token"]}

    prompt = _assemble_prompt(changes, symbols, [])

    assert "src/auth.py" in prompt
    assert "tests/test.py" in prompt
    assert "validate_token" in prompt
    assert "+2" in prompt  # added lines for auth.py
    assert "-1" in prompt  # removed lines for auth.py
    assert "new file" in prompt


def test_prompt_includes_risk_flags():
    """Test that _assemble_prompt includes risk flags."""
    from src.briefing.generator import _assemble_prompt

    flags = [
        RiskFlag(flag="modifies_auth", file="src/auth.py", line=42, snippet="token_secret"),
        RiskFlag(flag="touches_migration", file="migrations/001.sql", line=None, snippet="migrations/001.sql"),
    ]

    prompt = _assemble_prompt([], {}, flags)

    assert "modifies_auth" in prompt
    assert "touches_migration" in prompt
    assert ":42" in prompt  # line number for auth flag
    assert "token_secret" in prompt


def test_parse_sections_with_malformed_headers():
    """Test parsing handles slightly malformed section headers gracefully."""
    response = (
        "1. WHAT CHANGED\nFixed a bug.\n\n"
        "2. BLAST RADIUS\nNone.\n\n"
        "3. RISK FLAGS\nNone.\n\n"
        "4. QUESTIONS\n1. Test?\n2. Docs?\n3. Perf?"
    )

    sections = _parse_sections(response)

    # All sections should parse correctly
    assert "Fixed a bug" in sections["what_changed"]
    assert "None" in sections["blast_radius"]


def test_parse_sections_with_missing_final_section():
    """Test parsing when final section is completely missing."""
    response = (
        "1. WHAT CHANGED\nAdded feature.\n\n"
        "2. BLAST RADIUS\nImpacts services.\n\n"
        "3. RISK FLAGS\nCritical"
    )

    sections = _parse_sections(response)

    assert "Added feature" in sections["what_changed"]
    assert "Impacts services" in sections["blast_radius"]
    assert "Critical" in sections["risk_flags"]
    # Missing section returns empty string
    assert sections["questions"] == ""


def test_parse_sections_with_section_header_in_content():
    """Test parsing when content mistakenly contains next section's header text."""
    response = (
        "1. WHAT CHANGED\nThis change raises QUESTIONS about backwards compatibility.\n\n"
        "2. BLAST RADIUS\nAll users.\n\n"
        "3. RISK FLAGS\nNone.\n\n"
        "4. QUESTIONS\n1. Backwards compat?\n2. Testing?\n3. Docs?"
    )

    sections = _parse_sections(response)

    # Content before the actual section header should be captured correctly
    assert "raises QUESTIONS about" in sections["what_changed"]
    # Actual QUESTIONS section should also be captured
    assert "Backwards compat" in sections["questions"]


def test_parse_sections_completely_empty_response():
    """Test parsing with an empty or unintelligible response."""
    response = "I cannot analyze this PR."

    sections = _parse_sections(response)

    # All sections should be empty
    assert sections["what_changed"] == ""
    assert sections["blast_radius"] == ""
    assert sections["risk_flags"] == ""
    assert sections["questions"] == ""


def test_parse_sections_with_section_header_variations():
    """Test that parser only matches exact section headers."""
    response = (
        "1. WHAT CHANGED\nFixed bug.\n\n"
        "2. BLAST RADIUS\nAll modules.\n\n"
        "3. RISK FLAGS\nNone.\n\n"
        "4. QUESTIONS\n1. Done?\n2. Tested?\n3. Ready?"
    )

    sections = _parse_sections(response)

    # Should parse all sections correctly with the expected format
    assert "Fixed bug" in sections["what_changed"]
    assert "All modules" in sections["blast_radius"]
    assert "None" in sections["risk_flags"]
    assert "Done" in sections["questions"]


# --- Regression tests for markdown-decorated headers (llama-3.3-70b production failure) ---
# When all sections were empty in prod, the LLM had wrapped headers in ** or ##.
# The parser now normalizes lines before matching so these all parse correctly.

def test_parse_sections_bold_markdown_headers():
    """Regression: LLM wraps headers in ** markdown (e.g. **1. WHAT CHANGED**)."""
    response = (
        "**1. WHAT CHANGED**\nAdded OAuth support.\n\n"
        "**2. BLAST RADIUS**\nAll login flows.\n\n"
        "**3. RISK FLAGS**\n- Touches auth\n\n"
        "**4. QUESTIONS**\n1. Token expiry?\n2. Revocation?\n3. Tests?"
    )

    sections = _parse_sections(response)

    assert "OAuth" in sections["what_changed"]
    assert "login flows" in sections["blast_radius"]
    assert "Touches auth" in sections["risk_flags"]
    assert "Token expiry" in sections["questions"]


def test_parse_sections_heading_markdown_headers():
    """Regression: LLM uses ## heading syntax for section headers."""
    response = (
        "## 1. WHAT CHANGED\nRefactored caching.\n\n"
        "## 2. BLAST RADIUS\nCache-dependent endpoints.\n\n"
        "## 3. RISK FLAGS\n- Invalidation risk\n\n"
        "## 4. QUESTIONS\n1. TTL correct?\n2. Eviction policy?\n3. Metrics?"
    )

    sections = _parse_sections(response)

    assert "caching" in sections["what_changed"]
    assert "Cache-dependent" in sections["blast_radius"]
    assert "Invalidation" in sections["risk_flags"]
    assert "TTL" in sections["questions"]


def test_parse_sections_mixed_case_headers():
    """Regression: LLM uses mixed case (e.g. '1. What Changed')."""
    response = (
        "1. What Changed\nDropped legacy endpoint.\n\n"
        "2. Blast Radius\nExternal API consumers.\n\n"
        "3. Risk Flags\n- Breaking change\n\n"
        "4. Questions\n1. Versioned?\n2. Deprecation notice?\n3. Clients notified?"
    )

    sections = _parse_sections(response)

    assert "legacy endpoint" in sections["what_changed"]
    assert "External API" in sections["blast_radius"]
    assert "Breaking" in sections["risk_flags"]
    assert "Versioned" in sections["questions"]
