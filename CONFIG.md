# Configuration Reference

All configuration is via environment variables or CLI flags. CLI flags take precedence over env vars.

## Minimal config (one API key is enough)

```bash
export GROQ_API_KEY=<your-groq-key>
export GITHUB_TOKEN=<your-github-token>
pr-context-engine review --pr 42 --repo owner/name
```

## Full reference

### Provider selection

| Env var | Default | Values | Description |
|---|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq` \| `gemini` \| `ollama` \| `anthropic` | Primary LLM provider. |

### API keys

| Env var | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes (if `LLM_PROVIDER=groq`) | Free at https://console.groq.com/keys. ~1 000 req/day. |
| `GEMINI_API_KEY` | No | Failover when Groq is rate-limited. Also used as primary when `LLM_PROVIDER=gemini`. |
| `ANTHROPIC_API_KEY` | No | Required only when `LLM_PROVIDER=anthropic`. No free tier. |
| `GITHUB_TOKEN` | Yes (unless `--dry-run`) | Needs `pull-requests:write`. In Actions, use `${{ secrets.GITHUB_TOKEN }}`. |

### Ollama

| Env var | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL. |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model name to use via Ollama. |

### Fix suggestions (opt-in)

| Env var | CLI flag | Default | Description |
|---|---|---|---|
| `ENABLE_FIXES` | `--enable-fixes` / `--no-enable-fixes` | `false` | Generate confidence-gated fix suggestions. Opt-in per repo. See [ADR-5](docs/design-decisions.md). |

### Failover

Failover to Gemini is **automatic** whenever `GEMINI_API_KEY` is set, regardless of `LLM_PROVIDER`. The PR comment footer shows which provider was actually used (`via groq`, `via gemini (groq rate-limited)`, etc.).

To disable auto-failover, set `LLM_PROVIDER=gemini` explicitly — this makes Gemini the primary and there is no automatic fallback.

## CLI flags (review command)

```
pr-context-engine review [OPTIONS]

  --pr INTEGER          Pull request number. [required]
  --repo TEXT           Repository in owner/name form. [required]
  --github-token TEXT   GitHub token. Defaults to GITHUB_TOKEN env var.
  --enable-fixes        Generate fix suggestions (default off).
  --no-enable-fixes     Disable fix suggestions (default).
  --dry-run             Print briefing to stdout; do not post to GitHub.
  --help                Show this message and exit.
```

## CLI flags (quickstart command)

```
pr-context-engine quickstart

  Checks whether GROQ_API_KEY, GEMINI_API_KEY, and GITHUB_TOKEN are set and
  whether the GitHub token has the correct scope. Prints exactly what is missing.
```

## GitHub Actions example (full config)

```yaml
- uses: paramahastha/pr-context-engine@v1
  with:
    groq-api-key: ${{ secrets.GROQ_API_KEY }}
    gemini-api-key: ${{ secrets.GEMINI_API_KEY }}   # optional failover
    enable-fixes: "true"                             # opt-in fix suggestions
```
