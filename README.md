# PR Context Engine

> An AI tool that reads every new pull request and posts a senior-engineer-style
> briefing as a comment: what actually changed, blast radius, risk flags, and three
> sharp review questions.

> 🚧 **Under construction.** This project is built milestone by milestone per
> [`PROJECT.md`](PROJECT.md). The complete README — quickstart, architecture, eval
> results, data & privacy — is a Milestone 11 deliverable. What follows covers only
> the current milestone.

## Milestone 1 — end-to-end skeleton

A [`typer`](https://typer.tiangolo.com/) CLI that fetches a pull request's diff, asks
Groq to summarize it, and posts the summary back as a PR comment. The GitHub Action in
[`.github/workflows/pr-review.yml`](.github/workflows/pr-review.yml) is a thin wrapper
that only invokes the CLI — no logic lives in the workflow.

### Run it locally

```bash
uv sync                                    # install dependencies
export GROQ_API_KEY=<your-groq-key>        # free key: https://console.groq.com/keys
export GITHUB_TOKEN=$(gh auth token)       # a token with pull-requests: write
uv run pr-context-engine review --pr <N> --repo <owner>/<name>
```
