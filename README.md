# PR Context Engine

> An AI tool that reads every new pull request and posts a senior-engineer-style
> briefing as a comment: what actually changed, blast radius, risk flags, and three
> sharp review questions.

> 🚧 **Under construction.** This project is built milestone by milestone per
> [`PROJECT.md`](PROJECT.md). The complete README — quickstart, architecture, eval
> results, data & privacy — is a Milestone 11 deliverable. What follows covers only
> the current milestone.

## Milestone 2 — Pluggable LLM providers

All four providers share a single interface (`LLMProvider.generate(prompt) -> str`).
Switch between them with one environment variable — nothing downstream changes.

| `LLM_PROVIDER` | Model | Key env var | Notes |
|---|---|---|---|
| `groq` *(default)* | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | Free tier, ~1 000 req/day |
| `gemini` | `gemini-2.5-flash` | `GEMINI_API_KEY` | Free tier fallback |
| `ollama` | `qwen2.5-coder:7b` | — | Local, offline, no rate limits |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | BYO key |

### Run it locally

```bash
uv sync                                    # install dependencies
export GITHUB_TOKEN=$(gh auth token)       # token with pull-requests:write

# Default (Groq)
export GROQ_API_KEY=<your-groq-key>        # free key: https://console.groq.com/keys
uv run pr-context-engine review --pr <N> --repo <owner>/<name>

# Switch to Gemini
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=<your-gemini-key>
uv run pr-context-engine review --pr <N> --repo <owner>/<name>

# Switch to local Ollama (requires ollama running with qwen2.5-coder:7b pulled)
export LLM_PROVIDER=ollama
uv run pr-context-engine review --pr <N> --repo <owner>/<name>
```

### Run the tests

```bash
uv run pytest tests/unit/ -v
```

### Additional Ollama env vars

| Var | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model to use |
