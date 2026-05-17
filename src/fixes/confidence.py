"""Confidence gating: decides which fix suggestions become collapsed code blocks vs prose.

High and medium confidence fixes (with a non-None patch) are formatted as collapsed
<details> blocks with a fenced code snippet. Low confidence (or missing patch) is
rendered as a prose warning only.

Note: GitHub's ```suggestion fence only works in line-level review comments, not in
general PR body comments. We use language-inferred fences so the patch renders as
readable code regardless of comment type.
"""
from src.analyzers.diff_parser import detect_language
from src.fixes.fix_generator import FixSuggestion


def _lang_from_path(path: str) -> str:
    return detect_language(path)

_CONFIDENCE_ICONS = {
    "high": "🔴",
    "medium": "🟡",
    "low": "⚠️",
}


def is_block_eligible(suggestion: FixSuggestion) -> bool:
    """True when confidence is high or medium AND a patch is present.

    Low confidence suggestions must never produce a suggestion block even if
    the LLM accidentally emitted patch text — the parser already nulls the patch
    on low confidence, but this gate adds a second layer of enforcement.
    """
    return suggestion.confidence in ("high", "medium") and suggestion.patch is not None


def format_suggestion_block(suggestion: FixSuggestion) -> str:
    """Render a high/medium confidence fix as a collapsed <details> block with a code patch."""
    icon = _CONFIDENCE_ICONS.get(suggestion.confidence, "💡")
    flag_label = suggestion.flag.flag
    location = f"`{suggestion.flag.file}:{suggestion.flag.line}`"
    lang = _lang_from_path(suggestion.flag.file)

    return (
        f"<details>\n"
        f"<summary>{icon} <strong>{suggestion.confidence} confidence</strong>"
        f" — {flag_label} in {location}</summary>\n\n"
        f"**Rationale:** {suggestion.rationale}\n\n"
        f"```{lang}\n{suggestion.patch}\n```\n\n"
        f"</details>\n"
    )


def format_prose_note(suggestion: FixSuggestion) -> str:
    """Render a low-confidence fix (or missing patch) as a prose-only warning."""
    icon = _CONFIDENCE_ICONS.get(suggestion.confidence, "⚠️")
    flag_label = suggestion.flag.flag
    location = f"`{suggestion.flag.file}:{suggestion.flag.line}`"
    return (
        f"> {icon} **{suggestion.confidence}** — {flag_label} in {location}: "
        f"{suggestion.rationale}\n"
    )
