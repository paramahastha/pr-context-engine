# Contributing

## Development setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/paramahastha/pr-context-engine
cd pr-context-engine
uv sync --group dev
```

Copy `.env.example` to `.env` and fill in your API keys.

## Running tests

```bash
# Unit tests (fast, no API calls)
uv run pytest tests/unit/ -v

# Eval harness (requires a provider key; uses LLM-as-judge)
uv run pytest tests/eval/ -v
```

## Lint

```bash
uv run ruff check src/ tests/
```

## Local dry-run

```bash
export GITHUB_TOKEN=$(gh auth token)
export GROQ_API_KEY=<your-key>
uv run pr-context-engine review --pr <N> --repo <owner/name> --dry-run
```

## Milestone philosophy

Each milestone is designed so the next milestone doesn't require painful refactors of the previous one. The key early decisions — CLI-core entrypoint (M1), provider abstraction (M2), and located-issue data shape in the risk scorer (M3) — exist specifically to make M7, M8, and M9 cheap. Don't skip milestones or reorder them.

## Commit message format

```
feat(milestone-N): description
fix(milestone-N): description
refactor: description
```

## Pull request checklist

- [ ] `uv run ruff check src/ tests/` passes
- [ ] `uv run pytest tests/unit/ -v` passes
- [ ] New behaviour is covered by a test in `tests/unit/`
- [ ] No new required env vars without updating `CONFIG.md`

## Reporting bugs

Open an issue using the [bug report template](https://github.com/paramahastha/pr-context-engine/issues/new?template=bug_report.md).
