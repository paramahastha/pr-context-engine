# Design Decisions

Architectural decision records (ADRs) for PR Context Engine. Each entry captures the choice made, the alternatives considered, and why — so the reasoning doesn't rot with time.

---

## ADR-0: Provider abstraction built early

**Decision:** The `LLMProvider` interface (`src/llm/base.py`) was built in Milestone 2, before any feature logic, instead of being retrofitted later.

**Context:** In December 2025 Google cut Gemini's free-tier rate limits by 50–80% overnight. In April 2026 Pro models moved behind a paywall. Any project hard-wired to one free provider is one policy change away from a broken demo.

**Consequences:** The entire project is provider-agnostic from day one. The eval harness can compare providers. The live demo can fail over. Treating provider risk as an architectural concern — not an afterthought — is the single clearest senior-engineer signal in this project.

---

## ADR-1: CLI-core with two front doors

**Decision:** The CLI (`src/cli.py`) is the product; the GitHub Action is a thin wrapper that calls the CLI. Zero logic lives in the YAML.

**Alternatives considered:** Logic directly in the workflow YAML (common for simple Actions).

**Why CLI-core:** The tool is testable locally, runnable in any CI (GitLab, CircleCI, Jenkins), and not hostage to GitHub. Adding a new CI target requires only a new thin wrapper, not duplicating orchestration logic. The CLI-core architecture also makes `pipx install` meaningful — it's the same entry point as CI, not a stripped-down version.

---

## ADR-2: SQLite + sqlite-vec over a hosted vector store

**Decision:** Codebase embeddings are stored in a local `index.db` file using `sqlite-vec`, not Pinecone, Weaviate, or any hosted database.

**Alternatives considered:** Pinecone free tier, Chroma in-process.

**Why SQLite:** No API key, no external service, no cost, no latency. The file is cached across Action runs via `actions/cache`. It commits with the repo if desired. The tool's cost model is $0/month regardless of adoption scale — there is no shared backend to pay for as usage grows. `sqlite-vec` provides ANN search within the SQLite process, which is fast enough for repo-scale workloads (thousands of chunks, not billions).

---

## ADR-3: Local embeddings via fastembed

**Decision:** The codebase index uses `fastembed` with `BAAI/bge-small-en-v1.5` for embedding, running in-process on CPU. No embedding API is called.

**Why:** Groq has no embeddings endpoint. Calling an external API for embeddings would add latency, cost, and a second API key requirement. `fastembed` downloads the model weights on first run (~130 MB) and embeds entirely locally thereafter — free, offline, no rate limits. `bge-small-en-v1.5` is small enough to run on a GitHub Actions runner without timeout concerns.

---

## ADR-4: Shallow clone tradeoff in CI (fetch-depth: 50)

**Decision:** The GitHub Actions workflow uses `fetch-depth: 50` rather than a full clone (`fetch-depth: 0`).

**Context:** Git history context (Milestone 6) requires commit history for touched files. A full clone is the only way to guarantee complete history.

**Tradeoff:** Full clones on large or old repositories can take minutes and consume significant bandwidth on every PR — an unacceptable CI cost for a portfolio-scale tool. `fetch-depth: 50` covers the last ~50 commits, which is sufficient for the vast majority of active files. For rarely-touched files in long-lived repos, history beyond that window is simply unavailable in CI.

**How the code handles it:** `_fetch_file_history` detects the `"shallow"` warning in `git log` stderr and sets `limited_history=True` on the returned `FileHistory`. The briefing prompt surfaces this explicitly ("history may be truncated — shallow clone") rather than silently omitting it or erroring. The feature degrades gracefully: the briefing still runs, it just says "limited history" for files where the clone depth ran out.

**If deeper history matters:** Set `fetch-depth: 0` in `pr-review.yml` at the cost of slower CI. The code handles both transparently.

---

## ADR-5: Opt-in fix suggestions with confidence gating (Milestone 8)

**Decision:** Fix suggestions are disabled by default (`ENABLE_FIXES=false`) and only generate suggestion blocks for `high`/`medium` confidence assessments. `low` confidence produces prose-only notes.

**Why:** A confidently-wrong auto-fix is worse than no fix. The discipline to measure and bound the fix feature — including the calibration metric in the eval harness — is the portfolio point. Over-generating suggestions erodes trust faster than under-generating them.

---

## ADR-7: Provider failover order and motivation

**Decision:** `FailoverProvider` (Milestone 7) tries providers in this order: Groq → Gemini → hard error. Gemini failover is enabled automatically whenever `GEMINI_API_KEY` is present in the environment, regardless of `LLM_PROVIDER`.

**Context:** This is the runtime payoff for ADR-0. In December 2025 Google cut Gemini's free-tier rate limits by 50–80% overnight; by April 2026 Pro models moved behind a paywall. Groq's free tier allows ~1,000 requests/day, which is exhausted by a busy open-source repo during a release sprint. Without failover, a brief rate-limit window leaves every PR un-briefed and the tool's value collapses exactly when it's most needed.

**Why Groq first, Gemini second:** Groq is faster and has the higher daily cap on a fresh key. Gemini is the designated fallback because it has a separate quota pool — rate-limiting on one does not imply rate-limiting on the other. Ollama/Anthropic are not in the automatic failover chain: Ollama requires a local server (not available in CI), and Anthropic is BYO-key only with no free tier.

**How it surfaces to users:** The PR comment footer shows which provider was actually used — "via groq", "via gemini (groq rate-limited)", etc. — so maintainers can see failovers without digging through CI logs.

**If all providers fail:** The bot posts a brief error comment to the PR instead of silently failing, so the reviewer knows a briefing was attempted but couldn't be generated.

**Tradeoff accepted:** Auto-failover means a misconfigured primary silently routes to Gemini rather than failing loudly. The INFO log line ("Gemini failover enabled") and the footer attribution are the safety signals. If hard failure is preferred, set `LLM_PROVIDER=gemini` explicitly to disable the fallback.

---

## ADR-8: Python 3.12 as the implementation language

**Decision:** Python 3.12, not Go, TypeScript, or Rust.

**Why Python:** Three reasons that compound:
- **AST ecosystem** — `ast` (stdlib) gives first-class Python AST walking with zero dependencies. `tree-sitter` Python bindings are the de facto standard for multi-language symbol extraction. No equivalent exists at this maturity in Go or Rust.
- **LLM SDK ecosystem** — every major provider (Groq, Gemini, Anthropic, Ollama) publishes an official Python SDK first. Using them means staying on the maintained path rather than maintaining thin HTTP wrappers.
- **Speed of iteration for a portfolio project** — the bottleneck here is LLM call latency (hundreds of ms), not CPU. Python's overhead is irrelevant; its expressiveness and library depth are not.

**What was given up:** A Go or Rust binary would start faster and produce a single distributable file. Neither matters for a tool whose hot path is an LLM network call. `pipx` handles distribution cleanly; `uv` handles dependency resolution at Go-like speed.

---

## ADR-6: MIT license

**Decision:** MIT, not Apache 2.0, GPL, or AGPL.

**Why:** MIT is the most permissive widely-recognized license. It imposes no conditions on downstream users beyond attribution. For a developer tool intended for broad adoption, friction reduction matters: Apache 2.0 adds patent clauses that some legal teams flag; GPL would prevent commercial integration. MIT has the lowest adoption tax.
