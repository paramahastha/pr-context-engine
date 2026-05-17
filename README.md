# PR Context Engine

[![CI](https://github.com/paramahastha/pr-context-engine/actions/workflows/pr-review.yml/badge.svg)](https://github.com/paramahastha/pr-context-engine/actions/workflows/pr-review.yml)
[![PyPI version](https://img.shields.io/pypi/v/pr-context-engine)](https://pypi.org/project/pr-context-engine/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> An AI tool that reads every PR and writes the briefing — and the fixes — a senior engineer would, with the calibration data to prove it's not just guessing.

## What it does

Every PR opens with three problems for the reviewer: _what is this actually doing_, _what could it break_, and _what should I push back on_. A diff doesn't answer any of those.

PR Context Engine reads the diff plus surrounding code, recent git history, and semantically similar code from elsewhere in the repo, then posts a terse briefing written like a senior backend engineer would write it:

```markdown
## PR Briefing

**What changed**
Refactors the session token storage from an in-memory dict to Redis, adding a
configurable TTL. The auth middleware is updated to hit Redis on every request.

**Blast radius**
Any caller of `get_session()` now depends on Redis being reachable. If Redis is
down, all authenticated requests will 401. The previous in-memory store had no
such single point of failure.

**Risk flags**
- `modifies_auth`: src/auth/session.py line 42 — `token = generate_token(user_id)`

**Questions for the reviewer**

1. The Redis client is initialised once at import time — is there a reconnect
   strategy if the connection drops mid-deploy?
2. `SESSION_TTL` defaults to 3600 but the old in-memory store had no TTL — have
   existing sessions been migrated or will they all expire immediately after deploy?
3. There are no tests for the Redis-down path — is 401-on-outage the intended
   degradation, or should it fall back to the old store?
```

No praise. No filler. No "this LGTM." Just the context a reviewer needs.

## Quickstart (5 minutes)

### Option A — GitHub Action (recommended)

1. Get a free [Groq API key](https://console.groq.com/keys) — no credit card.
2. Add it as a secret: **Settings → Secrets → Actions → New secret** → `GROQ_API_KEY`.
3. Enable write permissions: **Settings → Actions → General → Workflow permissions → Read and write**.
4. Add this to `.github/workflows/pr-briefing.yml`:

```yaml
name: PR Briefing
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
      - uses: paramahastha/pr-context-engine@main
        with:
          groq-api-key: ${{ secrets.GROQ_API_KEY }}
```

That's it. Every new PR gets a briefing comment automatically.

### Option B — CLI (any CI or local)

```bash
pipx install pr-context-engine
export GROQ_API_KEY=<your-groq-key>
export GITHUB_TOKEN=$(gh auth token)

# Check your setup first
pr-context-engine quickstart

# Dry-run: see the briefing without posting it
pr-context-engine review --pr 42 --repo owner/name --dry-run

# Post the real comment
pr-context-engine review --pr 42 --repo owner/name
```

## Switching LLM providers

Set `LLM_PROVIDER` to any of `groq` (default), `gemini`, `ollama`, or `anthropic`. Nothing downstream changes.

| Provider | Key env var | Notes |
|---|---|---|
| `groq` *(default)* | `GROQ_API_KEY` | Free, ~1 000 req/day, fast |
| `gemini` | `GEMINI_API_KEY` | Free-tier fallback; auto-engaged on Groq 429 |
| `ollama` | — | Local, offline, no rate limits |
| `anthropic` | `ANTHROPIC_API_KEY` | BYO key, no free tier |

**Automatic failover:** if `GEMINI_API_KEY` is set, the tool fails over to Gemini on any Groq 429 or error and notes it in the PR comment footer. See [ADR-7](docs/design-decisions.md).

## Fix suggestions (opt-in)

When `ENABLE_FIXES=true`, the tool generates confidence-gated patch suggestions for located issues. Only `high`/`medium` confidence suggestions become one-click GitHub suggestion blocks; `low` confidence produces prose notes only. Max 3 suggestions per PR.

```yaml
- uses: paramahastha/pr-context-engine@main
  with:
    groq-api-key: ${{ secrets.GROQ_API_KEY }}
    enable-fixes: "true"
```

See [ADR-5](docs/design-decisions.md) for why this is opt-in and confidence-gated.

## Eval results

`pytest tests/eval/` produces a scorecard across five rubric dimensions (Accuracy, Blast radius, Risk flags, Question quality, Brevity) plus fix correctness and calibration rate.

```
pytest tests/eval/ -v
```

Results are committed to `tests/eval/scores/` so improvements are visible in git history. The headline metrics are **fix correctness rate** and **false-confidence rate** (when the model said `high` confidence, how often was the patch actually correct).

## Architecture

```
Front door A:                    Front door B:
GitHub Action wrapper            pipx install + run in any CI / locally
(paramahastha/pr-context-engine@main)
     │                                 │
     └────────────┬────────────────────┘
                  ▼
     ┌─────────────────────────────────────┐
     │  CLI core (src/cli.py + orchestrator)│
     └─────────────────────────────────────┘
                  │
     ├──► analyzers/   diff → FileChange objects, AST symbols, risk flags
     ├──► context/     git history, sqlite-vec codebase index (RAG)
     ├──► briefing/    prompt assembly → LLM call → structured output
     ├──► fixes/       confidence-gated patch suggestions (opt-in)
     ├──► llm/         pluggable providers + FailoverProvider
     └──► github_api/  fetch diff, post comment + suggestion blocks
```

The CLI is the product; the GitHub Action is a thin wrapper. See [docs/architecture.md](docs/architecture.md) and [docs/design-decisions.md](docs/design-decisions.md).

## Data & privacy

**What leaves your machine:**

- The PR diff and parsed metadata (file paths, function names, changed lines) are sent to the active LLM provider (Groq or Gemini by default).
- No source code beyond the diff is sent to any external API. The codebase index (RAG) runs entirely locally via `fastembed` + `sqlite-vec`.
- Git history and PR metadata are fetched from the GitHub API using your `GITHUB_TOKEN`.

**Provider data policies:**

- Groq and Gemini free tiers may use inputs for model improvement. See their respective privacy policies before using on private/sensitive repos.
- Use `LLM_PROVIDER=ollama` or `LLM_PROVIDER=anthropic` (with `ANTHROPIC_API_KEY`) if you need a provider with stronger data-isolation guarantees.
- The tool has no shared backend. Your API key, your quota, your data.

## Configuration

See [CONFIG.md](CONFIG.md) for the full reference of every env var and flag.

## Design decisions

See [docs/design-decisions.md](docs/design-decisions.md) for ADRs covering: why provider abstraction is built early, why SQLite over Pinecone, why fixes are opt-in, why MIT license, and more.

## Cost

**$0/month** for a portfolio-scale project on public repos.

- GitHub Actions: free for public repos.
- Groq: free tier, ~1 000 req/day.
- Gemini fallback: free tier (~1 500 req/day).
- Local embeddings (`fastembed`): $0, no API.
- The tool has no shared backend — your usage costs stay yours regardless of how many repos adopt it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and feature requests go in [Issues](https://github.com/paramahastha/pr-context-engine/issues).
