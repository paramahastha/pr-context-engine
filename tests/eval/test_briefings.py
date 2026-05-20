"""Eval harness: generates PR briefings from captured fixtures and scores them.

This is the portfolio differentiator (Milestone 9). It measures briefing quality
across 15 real-world-like PR scenarios using an LLM-as-judge (different model from
the one being evaluated) against the rubric in rubric.md.

How to run
----------
Analyzer-only (no API key needed — asserts flag detection):
    pytest tests/eval/ -v -s

With briefing generation:
    GROQ_API_KEY=... pytest tests/eval/ -v -s

With LLM-as-judge scoring (Anthropic as judge, Groq as generator):
    GROQ_API_KEY=... ANTHROPIC_API_KEY=... pytest tests/eval/ -v -s

The scorecard is printed at end-of-session and appended to scores.jsonl so
improvements are visible in git history.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.analyzers.ast_walker import extract_changed_symbols
from src.analyzers.diff_parser import parse_diff
from src.analyzers.risk_scorer import RiskFlag, score as risk_score
from src.briefing.generator import Briefing, generate_briefing
from src.fixes.fix_generator import FixSuggestion, generate_fixes

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCORES_PATH = Path(__file__).parent / "scores.jsonl"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FixScore:
    """Score for a single generated fix suggestion."""

    flag_type: str
    confidence: str
    patch_present: bool
    correctness: int = -1  # 0–3, -1 = not judged
    calibration_ok: bool | None = None  # None = not judged


@dataclass
class FixtureScore:
    """Aggregated eval result for one PR fixture."""

    fixture_id: str
    flag_precision: float  # fraction of detected flags that were expected
    flag_recall: float  # fraction of expected flags that were detected
    accuracy: int = -1  # 0–3, -1 = not judged (no LLM available)
    blast_radius: int = -1
    risk_flags_score: int = -1
    question_quality: int = -1
    brevity: int = -1
    fix_scores: list[FixScore] = field(default_factory=list)
    judge_used: str = "none"
    error: str | None = None


# Accumulated by each test; read by the session teardown.
_session_scores: list[FixtureScore] = []


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def _load_fixtures() -> list[dict]:
    """Load all JSON fixtures from the fixtures directory, sorted by filename."""
    return [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------


def _get_briefing_provider():
    """Return a configured LLM provider, or None if no API key is set."""
    try:
        from src.config import get_failover_provider

        return get_failover_provider()
    except Exception:
        return None


def _get_judge_provider() -> tuple[object | None, str]:
    """Return an LLM provider that is different from the briefing provider.

    Prefers Anthropic; falls back to Gemini. This ensures the judge is
    independent of the model being evaluated (see ADR-0 and rubric.md).
    Returns (None, 'none') when no suitable judge key is available.
    """
    briefing_name = os.getenv("LLM_PROVIDER", "groq").lower()

    if briefing_name != "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            try:
                from src.llm.anthropic_provider import AnthropicProvider

                return AnthropicProvider(api_key=key), "anthropic"
            except Exception as exc:
                logger.warning("Could not initialise Anthropic judge: %s", exc)

    if briefing_name != "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if key:
            try:
                from src.llm.gemini_provider import GeminiProvider

                return GeminiProvider(api_key=key), "gemini"
            except Exception as exc:
                logger.warning("Could not initialise Gemini judge: %s", exc)

    return None, "none"


# ---------------------------------------------------------------------------
# Flag scoring helpers (deterministic, no LLM)
# ---------------------------------------------------------------------------


def _score_flags(fixture: dict, detected: list[RiskFlag]) -> tuple[float, float]:
    """Compute precision and recall for heuristic flag detection.

    precision = fraction of detected flags that match expected (no false positives)
    recall    = fraction of expected flags that were detected (no missed flags)
    """
    expected = set(fixture["expected_risk_flags"])
    detected_types = {f.flag for f in detected}

    if not expected and not detected_types:
        return 1.0, 1.0

    true_positives = len(expected & detected_types)
    precision = true_positives / len(detected_types) if detected_types else 1.0
    recall = true_positives / len(expected) if expected else 1.0
    return precision, recall


# ---------------------------------------------------------------------------
# LLM judge prompts + scoring
# ---------------------------------------------------------------------------

_BRIEFING_JUDGE_PROMPT = """\
Score this AI-generated PR briefing. Return ONLY the JSON object below — no prose.

## PR context
Title: {title}
Description: {description}
Expected risk flags: {expected_flags}
Expected trivial: {expected_trivial}
Ground-truth reviewer notes: {human_notes}

## Briefing to score
{briefing_text}

## Rubric (score each dimension 0-3)
- accuracy: Does "What Changed" describe the actual intent (not just file names)?
- blast_radius: Does it name real callers/services/contracts that could break?
- risk_flags: Are risk flags present when expected? Are false positives absent?
- question_quality: Are the 3 questions sharp, specific, worth asking?
- brevity: Is it under 200 words with no filler or praise?

If expected_trivial is true, score based on whether the briefing correctly
identifies the PR as trivial and skips the full four-section format.

Return exactly this JSON (no other text):
{{"accuracy": 0, "blast_radius": 0, "risk_flags": 0, "question_quality": 0, "brevity": 0, "reasoning": "one sentence"}}"""

_FIX_JUDGE_PROMPT = """\
Evaluate this code fix suggestion. Return ONLY the JSON object below — no prose.

## Bug description
{bug_description}

## Expected correct fix approach
{correct_fix_description}

## Suggested fix
Confidence: {confidence}
Rationale: {rationale}
Patch:
{patch}

## Scoring
correctness (0-3):
  0 = wrong or harmful
  1 = partial fix (addresses symptom but not root cause)
  2 = correct but non-minimal
  3 = correct and minimal

calibration_ok: true if the stated confidence level matches the actual quality;
false if e.g. "high" confidence but the fix is wrong, or "low" when the fix is obviously correct.

Return exactly this JSON (no other text):
{{"correctness": 0, "calibration_ok": true, "reasoning": "one sentence"}}"""


def _parse_json_from_response(response: str) -> dict:
    """Extract a JSON object from an LLM response that may include prose or fences."""
    clean = re.sub(r"```(?:json)?", "", response).strip("`").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        return json.loads(clean[start : end + 1])
    return json.loads(clean)


def _judge_briefing(judge_provider, fixture: dict, briefing_text: str) -> dict:
    """Ask the judge LLM to score a briefing. Returns a dimension-score dict."""
    prompt = _BRIEFING_JUDGE_PROMPT.format(
        title=fixture["title"],
        description=fixture["description"],
        expected_flags=fixture["expected_risk_flags"],
        expected_trivial=fixture.get("expected_trivial", False),
        human_notes=fixture["human_notes"],
        briefing_text=briefing_text,
    )
    try:
        response = judge_provider.generate(prompt)
        return _parse_json_from_response(response)
    except Exception as exc:
        logger.warning("Judge scoring failed for %s: %s", fixture["id"], exc)
        return {
            "accuracy": -1,
            "blast_radius": -1,
            "risk_flags": -1,
            "question_quality": -1,
            "brevity": -1,
            "reasoning": str(exc),
        }


def _judge_fix(judge_provider, fixture: dict, suggestion: FixSuggestion) -> dict:
    """Ask the judge LLM to score a fix suggestion."""
    bug = fixture.get("known_bug") or {}
    prompt = _FIX_JUDGE_PROMPT.format(
        bug_description=bug.get("description", "unspecified bug"),
        correct_fix_description=bug.get("correct_fix_description", "not specified"),
        confidence=suggestion.confidence,
        rationale=suggestion.rationale,
        patch=suggestion.patch or "NO_PATCH",
    )
    try:
        response = judge_provider.generate(prompt)
        return _parse_json_from_response(response)
    except Exception as exc:
        logger.warning("Fix judge failed: %s", exc)
        return {"correctness": -1, "calibration_ok": None, "reasoning": str(exc)}


def _format_briefing_text(briefing: Briefing) -> str:
    """Format a Briefing object as four-section text for judge evaluation."""
    return (
        f"1. WHAT CHANGED\n{briefing.what_changed}\n\n"
        f"2. BLAST RADIUS\n{briefing.blast_radius}\n\n"
        f"3. RISK FLAGS\n{briefing.risk_flags}\n\n"
        f"4. QUESTIONS\n{briefing.questions}"
    )


# ---------------------------------------------------------------------------
# Session teardown: scorecard + history
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _eval_session_teardown():
    """Print the scorecard and save score history after all eval tests complete."""
    yield
    _print_scorecard(_session_scores)
    _save_scores(_session_scores)


def _safe_mean(values: list) -> float | None:
    valid = [v for v in values if isinstance(v, (int, float)) and v >= 0]
    return sum(valid) / len(valid) if valid else None


def _fmt(v: int | float) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) and v >= 0 else " n/a"


def _print_scorecard(scores: list[FixtureScore]) -> None:
    if not scores:
        print("\n[eval] No scores collected.")
        return

    judges = {s.judge_used for s in scores if s.judge_used != "none"}
    judge_label = "/".join(sorted(judges)) if judges else "heuristic only"
    provider_label = os.getenv("LLM_PROVIDER", "groq")

    print("\n" + "=" * 76)
    print("  PR CONTEXT ENGINE — EVAL SCORECARD")
    print(f"  Briefing model: {provider_label}   Judge: {judge_label}")
    print("=" * 76)

    row = "{:<33} {:>5} {:>5} {:>4} {:>5} {:>5} {:>5} {:>5} {:>6}"
    print(row.format("fixture", "prec", "rec", "acc", "blast", "flags", "q", "brev", "total"))
    print("-" * 76)

    for s in scores:
        dims = [s.accuracy, s.blast_radius, s.risk_flags_score, s.question_quality, s.brevity]
        total = _safe_mean(dims)
        err = " !" if s.error else ""
        print(
            row.format(
                (s.fixture_id + err)[:33],
                f"{s.flag_precision:.2f}",
                f"{s.flag_recall:.2f}",
                _fmt(s.accuracy),
                _fmt(s.blast_radius),
                _fmt(s.risk_flags_score),
                _fmt(s.question_quality),
                _fmt(s.brevity),
                f"{total:.1f}" if total is not None else " n/a",
            )
        )

    print("-" * 76)

    prec_mean = sum(s.flag_precision for s in scores) / len(scores)
    rec_mean = sum(s.flag_recall for s in scores) / len(scores)
    dim_attrs = ("accuracy", "blast_radius", "risk_flags_score", "question_quality", "brevity")
    dim_means = [_safe_mean([getattr(s, a) for s in scores]) for a in dim_attrs]

    def mf(v: float | None) -> str:
        return f"{v:.1f}" if v is not None else " n/a"

    print(
        row.format(
            "MEAN",
            f"{prec_mean:.2f}",
            f"{rec_mean:.2f}",
            mf(dim_means[0]),
            mf(dim_means[1]),
            mf(dim_means[2]),
            mf(dim_means[3]),
            mf(dim_means[4]),
            mf(_safe_mean([m for m in dim_means if m is not None])),
        )
    )

    # Fix correctness + calibration summary
    all_fix_scores = [fs for s in scores for fs in s.fix_scores]
    if all_fix_scores:
        judged_fixes = [fs for fs in all_fix_scores if fs.correctness >= 0]
        high_med = [fs for fs in all_fix_scores if fs.confidence in ("high", "medium")]
        false_conf = [fs for fs in high_med if fs.calibration_ok is False]
        print()
        if judged_fixes:
            avg_c = sum(fs.correctness for fs in judged_fixes) / len(judged_fixes)
            print(f"  Fix correctness ({len(judged_fixes)} fixes scored): {avg_c:.2f} / 3.0")
        if high_med:
            rate = len(false_conf) / len(high_med)
            print(
                f"  False-confidence rate: {rate:.0%}"
                f" ({len(false_conf)}/{len(high_med)} high/med predictions incorrect)"
            )

    print("=" * 76 + "\n")


def _save_scores(scores: list[FixtureScore]) -> None:
    """Append this run's aggregate scores to scores.jsonl (one line per run)."""
    if not scores:
        return

    dim_attrs = ("accuracy", "blast_radius", "risk_flags_score", "question_quality", "brevity")
    all_fix_scores = [fs for s in scores for fs in s.fix_scores]
    high_med = [fs for fs in all_fix_scores if fs.confidence in ("high", "medium")]

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": os.getenv("LLM_PROVIDER", "groq"),
        "n_fixtures": len(scores),
        "flag_precision_mean": sum(s.flag_precision for s in scores) / len(scores),
        "flag_recall_mean": sum(s.flag_recall for s in scores) / len(scores),
        "briefing_scores": {
            a: _safe_mean([getattr(s, a) for s in scores]) for a in dim_attrs
        },
        "fix_correctness_mean": _safe_mean([fs.correctness for fs in all_fix_scores]),
        "false_confidence_rate": (
            len([fs for fs in high_med if fs.calibration_ok is False]) / len(high_med)
            if high_med
            else None
        ),
        "per_fixture": [
            {
                "id": s.fixture_id,
                "flag_precision": s.flag_precision,
                "flag_recall": s.flag_recall,
                "accuracy": s.accuracy,
                "blast_radius": s.blast_radius,
                "risk_flags_score": s.risk_flags_score,
                "question_quality": s.question_quality,
                "brevity": s.brevity,
                "error": s.error,
                "fix_scores": [
                    {
                        "flag_type": fs.flag_type,
                        "confidence": fs.confidence,
                        "patch_present": fs.patch_present,
                        "correctness": fs.correctness,
                        "calibration_ok": fs.calibration_ok,
                    }
                    for fs in s.fix_scores
                ],
            }
            for s in scores
        ],
    }

    with SCORES_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Main parametrized eval test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["id"])
def test_eval_fixture(fixture: dict) -> None:
    """Analyze a captured PR fixture, generate a briefing, and score quality.

    Phase 1 (always): run the analyzer pipeline and assert all expected risk
    flags are detected. Deterministic — must pass with no API keys.

    Phase 2 (with LLM_PROVIDER key): generate a briefing via the configured
    provider. Skipped when no key is set; a warning is printed instead.

    Phase 3 (with judge key): score the generated briefing using a different
    LLM against the rubric dimensions and store the results.

    Phase 4 (bug fixtures, both keys required): generate fix suggestions for
    flags with located line numbers, then score fix correctness and calibration.
    """
    # ------------------------------------------------------------------
    # Phase 1: Analyzer pipeline — no API calls, always runs
    # ------------------------------------------------------------------
    changes = parse_diff(fixture["diff"])
    assert changes, f"[{fixture['id']}] parse_diff returned no changes — check diff format"

    detected_flags = risk_score(changes)
    flag_precision, flag_recall = _score_flags(fixture, detected_flags)

    fixture_score = FixtureScore(
        fixture_id=fixture["id"],
        flag_precision=flag_precision,
        flag_recall=flag_recall,
    )

    # ------------------------------------------------------------------
    # Phase 2 & 3: Briefing generation + judge scoring (requires API keys)
    # ------------------------------------------------------------------
    briefing_provider = _get_briefing_provider()
    judge_provider, judge_name = _get_judge_provider()

    if briefing_provider is not None:
        changed_symbols: dict[str, list[str]] = {
            c.path: extract_changed_symbols(c) for c in changes
        }
        try:
            briefing = generate_briefing(
                briefing_provider,
                changes,
                changed_symbols,
                detected_flags,
            )
            briefing_text = _format_briefing_text(briefing)

            if judge_provider is not None:
                fixture_score.judge_used = judge_name
                raw = _judge_briefing(judge_provider, fixture, briefing_text)
                fixture_score.accuracy = raw.get("accuracy", -1)
                fixture_score.blast_radius = raw.get("blast_radius", -1)
                fixture_score.risk_flags_score = raw.get("risk_flags", -1)
                fixture_score.question_quality = raw.get("question_quality", -1)
                fixture_score.brevity = raw.get("brevity", -1)

            # Phase 4: Fix generation for eligible bug fixtures
            known_bug = fixture.get("known_bug") or {}
            if known_bug.get("eligible_for_fix") and any(f.line is not None for f in detected_flags):
                suggestions, _extra = generate_fixes(
                    briefing_provider, detected_flags, changes, max_fixes=3
                )
                for suggestion in suggestions:
                    fs = FixScore(
                        flag_type=suggestion.flag.flag,
                        confidence=suggestion.confidence,
                        patch_present=suggestion.patch is not None,
                    )
                    if judge_provider is not None:
                        raw_fix = _judge_fix(judge_provider, fixture, suggestion)
                        fs.correctness = raw_fix.get("correctness", -1)
                        fs.calibration_ok = raw_fix.get("calibration_ok")
                    fixture_score.fix_scores.append(fs)

        except Exception as exc:
            fixture_score.error = str(exc)
            logger.error("[%s] Eval pipeline error: %s", fixture["id"], exc)
    else:
        logger.info(
            "[%s] No LLM provider configured — skipping briefing generation. "
            "Set GROQ_API_KEY (or another provider key) to enable full eval.",
            fixture["id"],
        )

    # Record before asserting so the scorecard always includes this fixture
    _session_scores.append(fixture_score)

    # ------------------------------------------------------------------
    # Deterministic assertion: expected flags must be detected
    # ------------------------------------------------------------------
    expected_flag_types = set(fixture["expected_risk_flags"])
    detected_flag_types = {f.flag for f in detected_flags}
    for expected in expected_flag_types:
        assert expected in detected_flag_types, (
            f"[{fixture['id']}] Expected risk flag '{expected}' was not detected by "
            f"the heuristic analyzer. Detected: {detected_flag_types or 'none'}. "
            f"Check that the fixture diff correctly triggers the risk_scorer heuristic."
        )
