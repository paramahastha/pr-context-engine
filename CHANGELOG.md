# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project uses [semantic versioning](https://semver.org/).

## Unreleased

## 0.1.0 — 2026-05-17

### Added

- **Milestone 1** — End-to-end skeleton: Typer CLI entrypoint (`pr-context-engine review`), Groq LLM provider, GitHub diff fetch and PR comment posting, GitHub Actions workflow.
- **Milestone 2** — Pluggable LLM providers: `LLMProvider` abstract base, Gemini, Ollama, and Anthropic implementations, `LLM_PROVIDER` env var switching.
- **Milestone 3** — Real diff analysis: `diff_parser`, `ast_walker` (function/class name extraction), `risk_scorer` with located-issue objects (`file`, `line`, `snippet`).
- **Milestone 4** — Senior-voice prompt and structured briefing: four-section markdown output (What changed / Blast radius / Risk flags / Questions), terse system prompt.
- **Milestone 5** — Codebase index (RAG): `sqlite-vec` + `fastembed` local embeddings, semantic similar-chunk retrieval, `actions/cache` integration.
- **Milestone 6** — Git history context: per-file commit history, recent merged PR lookup, graceful shallow-clone degradation.
- **Milestone 7** — Provider failover: `FailoverProvider` (Groq → Gemini on 429), provider attribution in PR comment footer, unit test for failover path.
- **Milestone 8** — Confidence-gated fix suggestions: `fix_generator`, confidence gate (`high`/`medium` → suggestion block, `low` → prose), collapsed `<details>` + GitHub suggestion blocks, `ENABLE_FIXES` kill switch.
- **Milestone 9** — Eval harness: LLM-as-judge scoring across 5 rubric dimensions + fix correctness + calibration rate, `pytest tests/eval/` scorecard.
- **Milestone 10** — Open-source readiness: `action.yml` for one-line GitHub Action install, `--dry-run` flag, `quickstart` command, `LICENSE` (MIT), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CONFIG.md`, PyPI metadata, issue/PR templates.
