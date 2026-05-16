# PR Context Engine — Eval Rubric

Used by `tests/eval/test_briefings.py` as judge instructions for LLM-as-judge scoring.
Each dimension is scored 0–3. The LLM judge uses the ground-truth notes in each fixture to calibrate.

---

## Briefing Dimensions

### 1. Accuracy (0–3)
Does the "What Changed" section correctly describe the *intent* of the PR — not just the lines?

| Score | Meaning |
|-------|---------|
| 3 | Accurately captures intent; names the right abstraction or feature being changed |
| 2 | Mostly correct but misses a secondary intent or misstates a detail |
| 1 | Partially correct — gets the file/area right but wrong about the why |
| 0 | Incorrect or generic ("several files were modified") |

### 2. Blast Radius (0–3)
Does it correctly identify what *could break* — callers, services, contracts, data?

| Score | Meaning |
|-------|---------|
| 3 | Names specific callers, contracts, or services that could be affected |
| 2 | Gets the blast radius right but misses one real risk area |
| 1 | Vague ("other code using this" without specifics) or identifies wrong area |
| 0 | Completely wrong or missing for a non-trivial change |

Special case: if the change is genuinely self-contained, writing "Self-contained" is correct and scores 3.

### 3. Risk Flags (0–3)
Are the risk flags accurate — present when they should be, absent when they shouldn't?

| Score | Meaning |
|-------|---------|
| 3 | All expected flags present; no false positives |
| 2 | Missing one flag or one minor false positive |
| 1 | Missing major flag(s) or multiple false positives |
| 0 | Flags are completely wrong or all missing when they should be present |

Special case: if no flags are expected and none are listed ("None."), that scores 3.

### 4. Question Quality (0–3)
Are the 3 reviewer questions sharp, specific, and worth asking?

| Score | Meaning |
|-------|---------|
| 3 | All 3 are concrete and specific; a senior engineer would actually ask them |
| 2 | 2 of 3 are good; one is generic or unanswerable |
| 1 | Only 1 is genuinely useful |
| 0 | All 3 are generic, vague, or obvious |

Bad question examples: "Did you test this?", "Is this change safe?", "Were docs updated?"
Good question examples: "The retry in `fetch_balance` has no backoff — intentional given it's per-request?", "Which callers of `get_user_by_email` need updating?"

### 5. Brevity (0–3)
Is the briefing terse (target: under 200 words) without padding, praise, or filler?

| Score | Meaning |
|-------|---------|
| 3 | Under 200 words, no filler, no praise |
| 2 | 200–300 words, or minor filler present |
| 1 | Over 300 words, or multiple instances of filler/praise |
| 0 | Excessively long or full of "this looks good" / "great work" language |

---

## Fix Correctness (for bug fixtures only)

### Fix Correctness (0–3)
Does the suggested patch actually resolve the described bug without introducing new issues?

| Score | Meaning |
|-------|---------|
| 3 | Correct and minimal — resolves the exact issue, no side effects |
| 2 | Correct but non-minimal — works but includes unnecessary changes |
| 1 | Partial fix — addresses the symptom but not the root cause |
| 0 | Wrong or harmful — does not fix the bug or introduces a new problem |

### Calibration
Was the confidence label appropriate given the actual correctness?

- `calibration_ok = true`: the stated confidence matched the actual quality (high confidence + correct fix, or low confidence + uncertain fix)
- `calibration_ok = false`: miscalibrated (e.g., high confidence + wrong fix, or low confidence when the fix was obviously correct)

**Headline metric**: false-confidence rate = fraction of `high`/`medium` suggestions that were actually wrong. Lower is better.

---

## Aggregate Scoring

A good overall briefing score is **2.3+ / 3.0** across all dimensions.
A good fix-correctness score is **2.5+ / 3.0** for the subset of bug fixtures.
A false-confidence rate below **15%** is acceptable; below **5%** is excellent.
