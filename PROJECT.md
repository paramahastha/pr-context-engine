# PR Context Engine

> An AI tool that reads every new pull request and posts a senior-engineer-style briefing as a comment: what actually changed, blast radius, risk flags, and three sharp review questions — with optional, confidence-gated fix suggestions. A `pipx`-installable CLI at its core, with a one-line GitHub Action wrapper. Runs in any CI or locally. Free to run.

---

## How to use this file with Claude Code

1. Create a new GitHub repo (public, free).
2. Drop this `PROJECT.md` at the root.
3. Open the repo in Claude Code and run:

   > "Read PROJECT.md and build the project. Start with Milestone 1 only. Stop after each milestone so I can review and test."

4. Work through milestones one at a time. Do not let Claude Code skip or reorder them — the value of this project is in the eval, the architecture, and the adoption layer, each of which only lands if the layers beneath it are solid. In particular: the CLI-core entrypoint (M1) and provider abstraction (M2) are deliberately early because retrofitting them later is expensive.

---

## Vision (one paragraph)

Every PR opens with three problems for the reviewer: _what is this actually doing_, _what could it break_, and _what should I push back on_. A diff doesn't answer any of those — it just shows lines. PR Context Engine reads the diff plus surrounding code, recent history, and similar past PRs, then produces a terse briefing written like a senior backend engineer would write it. No praise, no filler, no "this LGTM" — just the context a reviewer needs and the questions worth asking.

## Non-goals

- Not an auto-approver. Never approves or blocks PRs.
- Not a linter. Style/format issues are out of scope — existing tools do that.
- Not an auto-fixer. It _proposes_ fixes (opt-in, confidence-gated, Milestone 8); it never edits or commits. The human always applies.
- Not a "the AI thinks your code is great" bot. If there's nothing risky, the briefing is short. A wrong fix is treated as worse than no fix.

---

## Architecture

```
   Front door A:                    Front door B:
   GitHub Action wrapper            pipx install + run in any CI / locally
   (yourname/pr-context-engine@v1)  (pr-context-engine review --pr 123)
        │                                 │
        └────────────┬────────────────────┘
                     ▼
        ┌─────────────────────────────────────┐
        │  CLI core (src/cli.py → orchestrator)│
        └─────────────────────────────────────┘
                     │
        ├──► analyzers/  (diff → semantic chunks, AST, risk score)
        ├──► context/    (git history, codebase index via sqlite-vec)
        ├──► briefing/   (prompt assembly → LLM call)
        ├──► fixes/      (opt-in: confidence-gated patch suggestions)
        ├──► llm/        (pluggable: Groq / Gemini / Anthropic / Ollama)
        └──► github/     (post comment + collapsed suggestion blocks)
```

Design principle: **the CLI is the product; the GitHub Action is a thin wrapper around it.** No logic lives in the workflow YAML. This makes the tool testable locally, runnable in any CI (GitLab, CircleCI, Jenkins), and not hostage to GitHub — while still giving newcomers a one-line install.

### Why this stack

| Decision            | Choice                                                  | Reason                                                                                                                               |
| ------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Runtime             | GitHub Actions (wrapping the CLI)                       | Free for public repos. No server to host.                                                                                            |
| Distribution        | `pipx`-installable CLI + published GitHub Action        | CLI is the engine; Action is the easy on-ramp. Works in any CI, not just GitHub.                                                     |
| CLI framework       | `typer`                                                 | Minimal, type-hint-driven, auto-generates `--help`.                                                                                  |
| Language            | Python 3.12                                             | Best AST + LLM SDK ecosystem.                                                                                                        |
| Vector store        | SQLite + `sqlite-vec`                                   | File-based, commits with the repo, no external DB.                                                                                   |
| LLM access          | Pluggable provider interface (built early, Milestone 2) | This is the project's key design decision — see ADR below. Free LLM tiers are volatile; the abstraction is insurance, not polish.    |
| Default LLM (prod)  | Groq (`llama-3.3-70b-versatile`)                        | Free tier, no credit card, ~1,000 req/day, strong code reasoning, very fast.                                                         |
| Fallback LLM (prod) | Google Gemini (`gemini-2.5-flash`)                      | Free tier still generous (~1,500 req/day) but Google cut free quotas 50-80% in Dec 2025 with little warning — hence not the default. |
| Default LLM (dev)   | Ollama (`qwen2.5-coder:7b`)                             | Local, free, offline, no rate limits while iterating.                                                                                |
| Package manager     | `uv`                                                    | Fast, modern, single-binary.                                                                                                         |

### ADR-0: Why provider abstraction is built early, not last

In December 2025, Google cut Gemini's free-tier rate limits by 50–80% overnight, and in April 2026 moved Pro models behind a paywall. Any portfolio project hard-wired to one free provider is one policy change away from a broken demo. Building the `LLMProvider` interface in Milestone 2 (not as a final flourish) means the entire project is provider-agnostic from the start, the eval harness can compare providers, and the live demo can fail over. Treating provider risk as an architectural concern — rather than an afterthought — is the single clearest senior-engineer signal in this project. This reasoning belongs verbatim in `docs/design-decisions.md`.

---

## Repo layout (target)

```
pr-context-engine/
├── .github/
│   ├── workflows/
│   │   └── pr-review.yml
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── action.yml                 # makes this a usable published GitHub Action
├── src/
│   ├── __init__.py
│   ├── cli.py                 # typer entrypoint — the product
│   ├── config.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── groq_provider.py
│   │   ├── gemini_provider.py
│   │   ├── ollama_provider.py
│   │   └── anthropic_provider.py
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── diff_parser.py
│   │   ├── ast_walker.py
│   │   └── risk_scorer.py
│   ├── context/
│   │   ├── __init__.py
│   │   ├── git_history.py
│   │   └── codebase_index.py
│   ├── briefing/
│   │   ├── __init__.py
│   │   ├── prompt_templates.py
│   │   └── generator.py
│   ├── fixes/
│   │   ├── __init__.py
│   │   ├── fix_generator.py
│   │   └── confidence.py
│   └── github_api/
│       ├── __init__.py
│       └── comment_poster.py
├── tests/
│   ├── unit/
│   └── eval/
│       ├── fixtures/      # captured real PRs (sanitized)
│       ├── rubric.md
│       └── test_briefings.py
├── docs/
│   ├── architecture.md
│   ├── design-decisions.md
│   └── demo.gif
├── pyproject.toml             # includes [project.scripts] for the CLI
├── LICENSE                    # MIT
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CONFIG.md
├── CHANGELOG.md
├── README.md
└── PROJECT.md (this file)
```

---

## Milestones (build in this order)

### Milestone 1 — End-to-end skeleton (target: 1 evening)

Goal: prove the whole loop works with the dumbest possible logic.

- [ ] Init `uv` project, set up `pyproject.toml` with deps: `requests`, `groq`, `pygithub`, `python-dotenv`.
- [ ] `src/llm/base.py` — abstract `LLMProvider` class with `generate(prompt: str) -> str`.
- [ ] `src/llm/groq_provider.py` — minimal Groq implementation using `llama-3.3-70b-versatile`.
- [ ] `src/github_api/comment_poster.py` — function to post a comment to a PR via REST.
- [ ] `src/cli.py` — a `typer` CLI with one command: `pr-context-engine review --pr <N> --repo <owner/name>`. Reads config from flags **or** env vars (CI-friendly). This is the entrypoint from day one — there is no separate `main.py` script. It fetches the diff, sends `"Summarize this diff in 3 bullets:\n\n{diff}"` to Groq, posts the result.
- [ ] `pyproject.toml` — declare a `[project.scripts]` entry: `pr-context-engine = "src.cli:app"` so `pipx install` yields a working command.
- [ ] `.github/workflows/pr-review.yml` — triggers on `pull_request: [opened, synchronize]`, and simply _calls the CLI_ (`uv run pr-context-engine review --pr ${{ github.event.pull_request.number }} --repo ${{ github.repository }}`). No logic in the YAML.
- [ ] Open a test PR. Confirm comment appears. Also confirm `pipx install .` then running the command locally against a real PR works.

**Definition of done:** a real PR gets a comment both (a) via the workflow and (b) by running the installed CLI locally. The CLI is the single entrypoint.

### Milestone 2 — Pluggable LLM providers (moved up — see ADR-0)

Goal: lock in provider independence _before_ building everything else on top of one API. This is deliberately early.

- [ ] Confirm `src/llm/base.py` interface is clean: one method, `generate(prompt: str) -> str`, no provider-specific types leaking out.
- [ ] `src/llm/gemini_provider.py` — Gemini (`gemini-2.5-flash`) implementation.
- [ ] `src/llm/ollama_provider.py` — local model support (`qwen2.5-coder:7b`), used for dev.
- [ ] `src/llm/anthropic_provider.py` — Claude support (for BYO-key users).
- [ ] `src/config.py` — reads `LLM_PROVIDER` env var (`groq` | `gemini` | `ollama` | `anthropic`) and instantiates the right provider. Default `groq`.
- [ ] One unit test per provider using a mocked HTTP response — verify the interface contract, not the model.
- [ ] README documents how to switch providers with one env var.

**Definition of done:** the same PR can be briefed by Groq, Gemini, or local Ollama by changing one environment variable. Nothing downstream knows which provider is active.

### Milestone 3 — Real diff analysis

Goal: stop sending raw diffs to the LLM. Send structured context.

- [ ] `src/analyzers/diff_parser.py` — parse unified diff into `FileChange` objects: `path`, `language`, `added_lines`, `removed_lines`, `hunks`.
- [ ] `src/analyzers/ast_walker.py` — for Python/JS/TS/Go files, extract the _names_ of changed functions and classes (use `ast` for Python, tree-sitter for others if time; otherwise regex fallback).
- [ ] `src/analyzers/risk_scorer.py` — heuristic flags. Each flag is a **located issue object**, not a bare string: `{flag: str, file: str, line: int | None, snippet: str}`. (Milestone 8's fix generator depends on `file` + `line` being present — design this data shape now, even though fixes come later. A bare string list would force a painful refactor in M8.) Flags to detect:
  - file paths matching `migrations/`, `alembic/`, `*.sql` → `touches_migration`
  - keywords `auth`, `token`, `password`, `secret`, `permission` → `modifies_auth` (capture the line)
  - `.env*`, `config.*`, `*.yaml` at repo root → `changes_config`
  - deletions of top-level functions → `deletes_public_api` (capture the function name + line)
    Flags where a specific line genuinely doesn't apply (e.g. a whole-file config change) may set `line: None`; M8 will treat `line: None` flags as briefing-only, never fix-eligible.
- [ ] Update the CLI orchestrator (`src/cli.py` and the module it calls) to assemble structured context before prompting.

**Definition of done:** the prompt sent to the LLM is now a structured object, not raw diff text.

### Milestone 4 — Senior-voice prompt + structured output

Goal: make the comment actually feel like a senior wrote it.

- [ ] `src/briefing/prompt_templates.py` — system prompt below.
- [ ] `src/briefing/generator.py` — assembles final prompt, calls LLM, parses response.
- [ ] Briefing must follow this exact markdown structure:

  ```markdown
  ## 🤖 PR Briefing

  **What changed**
  <2-3 sentences, semantic not line-by-line>

  **Blast radius**
  <which callers, services, or contracts could break — omit if trivial>

  **Risk flags**
  <bullets, only present if risk_scorer found something>

  **Questions for the reviewer**

  1. <sharp question>
  2. <sharp question>
  3. <sharp question>

  ---

  <sub>Generated by [PR Context Engine](https://github.com/YOUR_USERNAME/pr-context-engine). Not a substitute for human review.</sub>
  ```

- [ ] Prompt must include the instruction: _"Be terse. No praise. No 'this looks good.' If a section has nothing meaningful to say, write 'None.' and move on."_

**Definition of done:** the comments now read like a senior reviewer wrote them.

### Milestone 5 — Codebase index (RAG)

Goal: pull in context from the rest of the repo, not just the diff.

- [ ] `src/context/codebase_index.py` — uses `sqlite-vec`. On first run, walks the repo, chunks files by function/class, embeds, stores in `index.db`. Note: Groq has no embeddings API — use a local embedding model (`fastembed` with `BAAI/bge-small-en-v1.5`, runs in-process, no API, no key) so indexing stays provider-independent and free.
- [ ] On subsequent runs, only re-embeds files whose git hash changed.
- [ ] For each `FileChange`, query the index for top-5 semantically similar chunks elsewhere in the repo. Include these in the prompt as "related code."
- [ ] `index.db` is cached across Action runs via `actions/cache`.

**Definition of done:** the briefing references functions and patterns from elsewhere in the repo when relevant.

### Milestone 6 — Git history context

Goal: use the past to inform the present.

- [ ] `src/context/git_history.py` — for each touched file, fetch the last 5 commit messages that modified it. Include in prompt as "recent activity on these files."
- [ ] Bonus: find the last 3 _merged_ PRs that touched any of the same files. Include their titles + first line of description.
- [ ] Note the shallow-clone tradeoff: the workflow uses `fetch-depth: 50`, so on large/old repos history for rarely-touched files may be truncated. This is an accepted tradeoff (full clones are slow/expensive in CI). Degrade gracefully — if history is unavailable, say "limited history" rather than erroring. Document this in `docs/design-decisions.md` as a deliberate CI-cost-vs-completeness call.

**Definition of done:** briefing can say things like "this is the third migration to `users` this month; previous one introduced [issue]."

### Milestone 7 — Provider failover & resilience

Goal: turn the early provider abstraction (Milestone 2) into real resilience — the payoff for ADR-0.

- [ ] `src/llm/__init__.py` — a `FailoverProvider` that wraps an ordered list of providers: try Groq, fall back to Gemini on rate-limit/error, fall back to a clear error comment if all fail.
- [ ] Detect 429 / quota errors specifically and log which provider was used in the PR comment footer (e.g. "Generated by Groq" / "Generated by Gemini (Groq rate-limited)").
- [ ] Add a unit test that simulates the primary provider 429-ing and asserts failover fires.
- [ ] Document the failover order and the December 2025 Gemini-quota-cut anecdote in `docs/design-decisions.md` as the concrete motivation.

**Definition of done:** kill the primary provider's key and the bot still posts a briefing via the fallback, noting which model it used.

### Milestone 8 — Suggested fixes (opt-in, guard-railed)

Goal: go from "here's a problem" to "here's a fix you can apply in one click" — **without becoming a noisy, confidently-wrong bot.** The discipline here is the portfolio point. A bad version of this feature is worse than not having it; the guardrails below are not optional.

**Dependencies (read before starting):** This milestone consumes the located-issue objects from Milestone 3's `risk_scorer` (the `file` + `line` fields). Only issues with a non-null `line` are fix-eligible; everything else stays briefing-only. This milestone also _extends_ the Milestone 4 system prompt — it must **add** a fix-format contract as an appended section, not rewrite the briefing prompt. The M4 briefing behavior must remain byte-for-byte unchanged when `ENABLE_FIXES=false`. Verify M4's eval still passes after this milestone.

**Hard rules (build these as actual code constraints, not prompt suggestions):**

- A fix is **only** generated when `risk_scorer` produced a located issue (`line` is not null) for a _concrete, specific_ problem. No fixes for vague observations or `line: None` flags.
- Every suggestion is posted as a GitHub **suggestion block** (` ```suggestion `) inside a **collapsed `<details>`** section, so the diff isn't cluttered and the human opts in by expanding + clicking "Commit suggestion."
- Every suggestion carries a one-line **rationale** and a **confidence label** (`high` / `medium` / `low`). `low` confidence suggestions are _described in prose only_ — no auto-applicable block. The model must never present a guess as a fix.
- **Max 3 suggestions per PR.** If more issues exist, say "N more issues — see briefing" rather than flooding the diff.
- The bot never edits; it only proposes. The human always commits.

**Tasks:**

- [ ] `src/fixes/fix_generator.py` — takes a flagged issue + surrounding code, asks the LLM for a minimal patch + rationale + self-assessed confidence. Returns structured output, not raw text.
- [ ] `src/fixes/confidence.py` — gate logic: only `high`/`medium` become suggestion blocks; `low` becomes a prose note.
- [ ] `src/github_api/comment_poster.py` — extend to post line-anchored suggestion blocks inside collapsed `<details>`.
- [ ] Extend the system prompt with a strict fix-format contract, **appended as a separate section** so the Milestone 4 briefing prompt is untouched. Include the instruction: _"If you are not confident the patch is correct and complete, label it 'low' and do not produce a suggestion block. A wrong fix is worse than no fix."_ The fix section is only included in the prompt when `ENABLE_FIXES=true`.
- [ ] Add a kill switch: `ENABLE_FIXES` env var (default `false`) so the feature is explicitly opt-in per repo.

**Definition of done:** on a PR with a real, located bug, the bot posts a collapsed suggestion the maintainer can apply in one click — and on a PR where it's unsure, it says so in prose instead of guessing.

### Milestone 9 — Eval harness (the portfolio differentiator)

This is what separates "AI side project" from "engineer who knows what they're doing." **Do not skip.** With Milestone 8 added, this milestone now also measures whether the _fixes are actually correct_ — which is the hardest and most credible thing to measure in the whole project.

- [ ] `tests/eval/fixtures/` — 15-20 real PRs you've captured (diff + actual review comments, sanitized). Pull from open-source repos if your own are private. Include several with a _known, real bug_ so fix-correctness can be scored.
- [ ] `tests/eval/rubric.md` — a scoring rubric. Briefing dimensions (0-3 each):
  1. **Accuracy** — does the "what changed" actually describe the change?
  2. **Blast radius** — does it identify real risk areas?
  3. **Risk flags** — are flags present when they should be? false positives?
  4. **Question quality** — would a senior reviewer actually ask these?
  5. **Brevity** — is it terse, or does it pad?
  - Plus, for the fix feature: **Fix correctness** — does the patch actually resolve the flagged issue without breaking anything? (0 = wrong/harmful, 1 = partial, 2 = correct but non-minimal, 3 = correct and minimal). And **Calibration** — when the bot said `high` confidence, was it actually right? Track false-confidence rate explicitly; this number is the headline metric.
- [ ] `tests/eval/test_briefings.py` — runs each fixture, generates briefing + fixes, uses an LLM-as-judge (different model from the one being evaluated) to score against the rubric. Where possible, run the suggested patch against the repo's tests to verify fix correctness empirically, not just by judge opinion.
- [ ] Print a summary table. Commit historical scores so improvements are visible in git history.

**Definition of done:** `pytest tests/eval/` produces a scorecard including a fix-correctness rate and a false-confidence rate. README shows both.

### Milestone 10 — Open-source readiness (the adoption layer)

Goal: make a stranger able to install and trust this in 5 minutes with zero prior context. A tool nobody can install is just a private script. These items are what separate "starred and forgotten" from "actually used."

**The 5-minute install path (must work exactly as written in the README):**

- [ ] Publish the GitHub Action: add `action.yml` at repo root so others can use `uses: YOUR_USERNAME/pr-context-engine@v1` with just a `GROQ_API_KEY` secret. This is the newcomer on-ramp.
- [ ] Publish the CLI to PyPI so `pipx install pr-context-engine` works for the power-user / other-CI path. (Test on TestPyPI first.)
- [ ] A `quickstart` CLI command that interactively checks: is a provider key set? does the GitHub token have the right scope? — and prints exactly what's missing. First-run failure is the #1 reason OSS tools get abandoned; this catches it.
- [ ] `--dry-run` flag: generate the briefing and print it to stdout _without_ posting. Lets a new user see value before granting write access. Critical for trust.

**Trust & safety for adopters:**

- [ ] A clear, prominent statement in the README: what data leaves their machine, which provider sees their code, and that free-tier providers may train on inputs (link the design-decisions ADR). Engineers will not adopt a code tool that's vague about this.
- [ ] `CONFIG.md` documenting every env var / flag, defaults, and a minimal vs. full example.
- [ ] Sensible defaults so the tool is useful with _zero_ config beyond one API key. Every required-config item is an adoption tax.

**Project hygiene (signals the project is alive and safe to depend on):**

- [ ] `LICENSE` — MIT (most permissive, lowest adoption friction; state this choice in an ADR).
- [ ] `CONTRIBUTING.md` — how to set up dev env, run tests, the milestone philosophy.
- [ ] `CODE_OF_CONDUCT.md` — standard Contributor Covenant.
- [ ] Issue + PR templates in `.github/`.
- [ ] CI badge, PyPI version badge, license badge in README.
- [ ] A `CHANGELOG.md` and real semver git tags (`v0.1.0` …). Dependents need to pin versions.
- [ ] Dogfood it: the repo runs its own Action on its own PRs. The best possible demo is the tool reviewing its own development.

**Definition of done:** a fresh machine with only `pipx` can install the tool and get a `--dry-run` briefing on a public PR using only a free Groq key, following only the README, in under 5 minutes — verified by actually doing it (or having someone else do it).

### Milestone 11 — Portfolio polish

- [ ] `docs/architecture.md` — the architecture section above, expanded, with a Mermaid diagram.
- [ ] `docs/design-decisions.md` — short ADRs for the top choices: why SQLite over Pinecone, why Actions over a server, why Python, why fixes are opt-in and confidence-gated, why CLI-core over Action-only, why MIT. Each ADR shows you understood a tradeoff.
- [ ] `docs/demo.gif` — record a real PR getting briefed _and_ a suggestion being one-click applied. Embed in README.
- [ ] README sections in order: Demo GIF → What it does → 5-minute Quickstart → Live example → Architecture diagram → Eval results (incl. fix-correctness + calibration) → Data & privacy → Design decisions → Cost analysis → Contributing.
- [ ] Pin the repo on your GitHub profile.

---

## The system prompt (Milestone 4)

Paste this verbatim into `prompt_templates.py`:

```
You are a senior backend engineer reviewing a pull request. You have 90 seconds.
Your job is to brief the human reviewer so they can review effectively.

You will receive:
- A list of changed files with parsed function/class names
- Risk flags detected by static heuristics
- Recent commit history on touched files
- Semantically related code from elsewhere in the repo

Produce a briefing with exactly four sections:

1. WHAT CHANGED — 2-3 sentences. Describe the *intent* of the change, not the
   lines. Do not list files. If you can't tell the intent, say so.

2. BLAST RADIUS — Which callers, services, contracts, or data could break?
   Be specific. If the change is internal and self-contained, write "Self-contained."

3. RISK FLAGS — Bullet list. Only include flags that are actually present.
   If none, write "None."

4. QUESTIONS — Exactly three questions a senior reviewer would ask before
   approving. Questions must be answerable and specific. Bad question:
   "Did you test this?" Good question: "The new retry loop in fetch_user
   has no backoff — is that intentional given this is called per-request?"

Rules:
- Be terse. Aim for under 200 words total.
- No praise. No "this looks good." No emojis except the section icons.
- If the PR is trivial (typo fix, doc change), say so in one line and skip
  the other sections.
- Never speculate about things you can't see. If you don't have the context,
  say "Cannot tell from diff."
```

---

## GitHub Actions workflow (Milestone 1)

`.github/workflows/pr-review.yml`:

```yaml
name: PR Context Briefing

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  brief:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 50 # tradeoff: enough history for most files, fast clone; see Milestone 6 note

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: pip install uv

      - name: Restore index cache
        uses: actions/cache@v4
        with:
          path: index.db
          key: pr-engine-index-${{ github.event.pull_request.base.sha }}
          restore-keys: pr-engine-index-

      - name: Install dependencies
        run: uv sync

      - name: Generate briefing
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          LLM_PROVIDER: groq
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }} # fallback (Milestone 7)
        run: >
          uv run pr-context-engine review
          --pr ${{ github.event.pull_request.number }}
          --repo ${{ github.repository }}
```

Note: the workflow contains zero logic — it just invokes the CLI. That's the point of the CLI-core design (see ADR). Once `action.yml` is published (Milestone 10), other repos skip even this and use a single `uses:` line.

---

## Setup checklist (one-time, by you)

- [ ] Create a new public repo on GitHub.
- [ ] Get a free Groq API key at https://console.groq.com/keys (no credit card).
- [ ] (Optional, for failover) Get a free Gemini key at https://aistudio.google.com/apikey.
- [ ] In repo Settings → Secrets and variables → Actions → add `GROQ_API_KEY` (and `GEMINI_API_KEY` if using failover).
- [ ] In repo Settings → Actions → General → enable "Read and write permissions" for `GITHUB_TOKEN`.
- [ ] Drop this file in. Open Claude Code. Tell it to start Milestone 1.

---

## Rules for Claude Code while building this

- **One milestone per session.** Stop and let the human test before moving on.
- **No new dependencies without asking.** Justify each addition.
- **Every module gets a docstring** explaining its single responsibility.
- **Unit tests for `analyzers/` and `context/`** — pure functions, easy to test.
- **No try/except: pass.** If something fails, fail loudly with context.
- **Type hints on every public function.**
- **No print statements in `src/`** — use `logging`.
- **Commit message format:** `feat(milestone-N): description` or `fix(milestone-N): description`.

---

## Cost expectation

- GitHub Actions: $0 (public repo, well under 2000-min/month free tier).
- Groq free tier: $0 (~1,000 requests/day — you'd need 1,000 PRs in a day to exhaust it).
- Local embeddings (`fastembed`): $0, no API.
- Gemini fallback: $0 (only hit if Groq is rate-limited).
- Total: $0/month for a portfolio-scale project.

Free LLM tiers change without warning (Google cut Gemini's by 50–80% in Dec 2025). The Milestone 7 failover design means a single provider's policy change degrades gracefully instead of breaking. And because the tool is BYO-key, anyone who adopts it runs on their _own_ free Groq key at their own $0 — there's no shared backend you pay for as it gets popular. The project's cost does not scale with its adoption, which is exactly what you want for an OSS tool.

---

## README guidance

The authoritative README structure lives in **Milestone 11** (it accounts for the fix feature, eval/calibration results, the data & privacy section, and the 5-minute quickstart). Do not use an older/shorter structure — build the README from the Milestone 11 checklist.

The one-line pitch to lead with: _"An AI tool that reads every PR and writes the briefing — and the fixes — a senior engineer would, with the calibration data to prove it's not just guessing."_

---

## Why this project works as a portfolio piece

It checks all three boxes a senior backend role looks for:

- **AI depth** — RAG over a real codebase (M5), context engineering (M3–M6), and an eval harness with an LLM-as-judge and empirical fix verification (M9).
- **Product thinking** — the terse-senior-reviewer voice, the no-praise prompt rules, opt-in confidence-gated fixes (M8), and a deliberate 5-minute install path (M10).
- **Systems design** — a CLI-core with two front doors, provider abstraction built early (M2), and real failover (M7).

The two hardest-to-fake signals: the fix feature _plus its calibration metric_ (M8 + M9) shows you can ship a risky capability and the discipline to measure and bound it; and real adoption (M10) — strangers installing and depending on it — is something no résumé bullet can manufacture. Build it in order; the early decisions (CLI-core, provider abstraction, located-issue data shape) exist specifically so the later milestones don't require painful refactors.
