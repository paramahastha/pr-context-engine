"""Generate fix suggestions for located risk flags via a separate LLM call.

Each call targets a single RiskFlag with a concrete line number and asks the LLM
for a minimal replacement patch plus a confidence self-assessment. Low-confidence
responses intentionally produce no patch — a wrong fix is worse than no fix.
"""
import logging
from dataclasses import dataclass

from src.analyzers.diff_parser import FileChange
from src.analyzers.risk_scorer import RiskFlag
from src.briefing.prompt_templates import FIX_SYSTEM_PROMPT
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MAX_CONTEXT_LINES = 40


@dataclass
class FixSuggestion:
    """A suggested fix for a specific risk flag."""

    flag: RiskFlag
    patch: str | None  # replacement code; None when confidence is low or generation failed
    rationale: str
    confidence: str  # "high" | "medium" | "low"


def generate_fixes(
    provider: LLMProvider,
    flags: list[RiskFlag],
    changes: list[FileChange],
    max_fixes: int = 3,
) -> tuple[list[FixSuggestion], int]:
    """Generate fix suggestions for up to max_fixes eligible flags.

    Only flags with a non-null line number are fix-eligible. Returns a tuple of
    (suggestions, extra_count) where extra_count is how many eligible flags were
    skipped due to the cap.

    Args:
        provider: LLM provider instance for generation calls.
        flags: All risk flags from the current PR.
        changes: Parsed file changes (used to extract surrounding code context).
        max_fixes: Maximum number of fix suggestions to generate (default 3).

    Returns:
        Tuple of (list of FixSuggestion, number of eligible flags beyond the cap).
    """
    eligible = [f for f in flags if f.line is not None]
    capped = eligible[:max_fixes]
    extra_count = len(eligible) - len(capped)

    suggestions: list[FixSuggestion] = []
    for flag in capped:
        suggestion = _generate_single_fix(provider, flag, changes)
        suggestions.append(suggestion)

    return suggestions, extra_count


def _generate_single_fix(
    provider: LLMProvider,
    flag: RiskFlag,
    changes: list[FileChange],
) -> FixSuggestion:
    """Make one LLM call to generate a fix for a single located flag."""
    context = _get_flag_context(flag, changes)
    prompt = _build_fix_prompt(flag, context)

    try:
        response = provider.generate(prompt)
    except Exception as exc:
        logger.warning("Fix generation failed for %s:%s: %s", flag.file, flag.line, exc)
        return FixSuggestion(
            flag=flag,
            patch=None,
            rationale="Fix generation failed — see briefing for details.",
            confidence="low",
        )

    return _parse_fix_response(flag, response)


def _get_flag_context(flag: RiskFlag, changes: list[FileChange]) -> str:
    """Extract the diff hunk containing the flagged line as context.

    Checks both old-file and new-file line ranges so both modifies_auth
    (new-file lines) and deletes_public_api (old-file lines) are handled.
    Falls back to the flag snippet if no matching hunk is found.
    """
    for change in changes:
        if change.path != flag.file:
            continue
        for hunk in change.hunks:
            new_end = hunk.new_start + max(hunk.new_count, 1)
            old_end = hunk.old_start + max(hunk.old_count, 1)
            line = flag.line or 0
            if hunk.new_start <= line < new_end or hunk.old_start <= line < old_end:
                return "\n".join(hunk.lines[:_MAX_CONTEXT_LINES])
    return flag.snippet


def _build_fix_prompt(flag: RiskFlag, context: str) -> str:
    """Assemble the full prompt: system instructions + flag context."""
    user_section = (
        f"Flag type: {flag.flag}\n"
        f"File: {flag.file}\n"
        f"Line: {flag.line}\n"
        f"Flagged snippet: {flag.snippet}\n\n"
        f"Surrounding diff context:\n```\n{context}\n```"
    )
    return f"{FIX_SYSTEM_PROMPT}\n\n---\n\n{user_section}"


def _parse_fix_response(flag: RiskFlag, response: str) -> FixSuggestion:
    """Parse structured fix response (CONFIDENCE / RATIONALE / PATCH) from LLM."""
    confidence = "low"
    rationale = ""
    patch_lines: list[str] = []
    in_patch = False

    for line in response.strip().splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CONFIDENCE:"):
            raw = stripped.split(":", 1)[1].strip().lower()
            if raw in ("high", "medium", "low"):
                confidence = raw
        elif stripped.upper().startswith("RATIONALE:"):
            rationale = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("PATCH:"):
            in_patch = True
        elif in_patch:
            patch_lines.append(line)

    patch: str | None = None
    if patch_lines:
        raw_patch = "\n".join(patch_lines).strip()
        if raw_patch and raw_patch.upper() != "NO_PATCH":
            patch = raw_patch

    # Enforce hard rule: low confidence must never carry a patch block.
    if confidence == "low":
        patch = None

    return FixSuggestion(
        flag=flag,
        patch=patch,
        rationale=rationale or flag.snippet,
        confidence=confidence,
    )
