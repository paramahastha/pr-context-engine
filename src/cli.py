"""Typer CLI — the single entrypoint; orchestrates fetch-diff, analyze, summarize, post."""
import logging
import os

import requests
import typer
from dotenv import load_dotenv

from src.analyzers.ast_walker import extract_changed_symbols
from src.analyzers.diff_parser import FileChange, parse_diff
from src.analyzers.risk_scorer import score
from src.briefing.generator import Briefing, generate_briefing
from src.config import get_failover_provider, is_fixes_enabled
from src.context.codebase_index import CodebaseIndex, RelatedChunk
from src.context.git_history import FileHistory, RecentPR, get_file_histories, get_recent_merged_prs
from src.fixes.fix_generator import generate_fixes
from src.github_api.comment_poster import fetch_pr_diff, format_fix_section, post_pr_comment

load_dotenv()
logger = logging.getLogger(__name__)

app = typer.Typer(help="PR Context Engine — brief a pull request.")

_MAX_DIFF_LINES = 4_000  # ~8k tokens; avoids hitting provider context limits on large PRs
_MAX_RAG_FILES = 10  # query RAG only for the most-changed files to keep prompt under token budget


@app.callback()
def main() -> None:
    """PR Context Engine — brief a pull request for human reviewers.

    This callback exists so Typer keeps `review` as an explicit subcommand. A
    single-command Typer app otherwise collapses the command and drops its name,
    which would break the documented `pr-context-engine review ...` invocation.
    """
    logging.basicConfig(level=logging.INFO)


@app.command()
def review(
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    repo: str = typer.Option(..., "--repo", help="Repository in owner/name form."),
    github_token: str | None = typer.Option(
        None, envvar="GITHUB_TOKEN", help="GitHub token with pull-requests:write."
    ),
    enable_fixes: bool = typer.Option(
        False,
        "--enable-fixes/--no-enable-fixes",
        envvar="ENABLE_FIXES",
        help="Generate confidence-gated fix suggestions (opt-in, default off).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the briefing to stdout instead of posting it to GitHub.",
    ),
) -> None:
    """Fetch a PR's diff, analyze it structurally, and post an AI-generated briefing."""
    if not github_token and not dry_run:
        raise typer.BadParameter("GITHUB_TOKEN is not set (flag or env var).")

    # Typer's envvar= already handles ENABLE_FIXES for CLI invocations; this
    # covers programmatic callers of review() that bypass Typer argument parsing.
    enable_fixes = enable_fixes or is_fixes_enabled()

    raw_diff = fetch_pr_diff(repo, pr, github_token)
    logger.info("Fetched diff (%d chars)", len(raw_diff))

    changes = parse_diff(raw_diff)
    logger.info("Parsed %d file changes", len(changes))

    # Drop whole FileChanges once the running line budget is exhausted so the parser
    # always sees complete hunks — slicing raw diff text mid-file leaves incomplete objects.
    budget = _MAX_DIFF_LINES
    trimmed: list[FileChange] = []
    for change in changes:
        file_lines = len(change.added_lines) + len(change.removed_lines)
        if budget <= 0:
            break
        trimmed.append(change)
        budget -= file_lines
    if len(trimmed) < len(changes):
        logger.warning("Dropped %d files beyond %d-line budget", len(changes) - len(trimmed), _MAX_DIFF_LINES)
    changes = trimmed

    changed_symbols: dict[str, list[str]] = {}
    for change in changes:
        syms = extract_changed_symbols(change)
        if syms:
            changed_symbols[change.path] = syms

    flags = score(changes)
    logger.info("Detected %d risk flags", len(flags))

    related_code = _build_related_code(changes, changed_symbols)
    git_history, recent_prs = _build_git_context(changes, repo, github_token)

    try:
        provider = get_failover_provider()
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    try:
        briefing = generate_briefing(
            provider, changes, changed_symbols, flags, related_code, git_history, recent_prs
        )
    except RuntimeError as exc:
        logger.error("Briefing generation failed: %s", exc)
        if dry_run:
            typer.echo(_format_error(str(exc)))
        elif github_token:
            post_pr_comment(repo, pr, _format_error(str(exc)), github_token)
        raise typer.Exit(code=1)

    logger.info("Generated briefing sections (via %s)", provider.attribution())

    fix_section = ""
    if enable_fixes:
        logger.info("Fix suggestions enabled — generating for eligible flags")
        suggestions, extra_count = generate_fixes(provider, flags, changes)
        logger.info(
            "Generated %d fix suggestion(s) (%d skipped by cap)",
            len(suggestions),
            extra_count,
        )
        fix_section = format_fix_section(suggestions, extra_count)

    comment_text = _format_briefing(
        briefing,
        provider_attribution=provider.attribution(),
        fix_section=fix_section,
    )
    if dry_run:
        typer.echo(comment_text)
        logger.info("Dry-run mode — briefing printed to stdout, not posted to GitHub")
    else:
        if not github_token:
            raise RuntimeError("github_token must be set when not in dry-run mode")
        post_pr_comment(repo, pr, comment_text, github_token)
        logger.info("Comment posted to %s PR #%d", repo, pr)


def _build_related_code(
    changes: list[FileChange],
    changed_symbols: dict[str, list[str]],
) -> dict[str, list[RelatedChunk]]:
    """Build and query the codebase index for each changed file.

    Returns an empty dict if indexing fails (e.g. sqlite-vec extension unavailable
    on this platform) so the briefing still works without RAG context.
    """
    try:
        index = CodebaseIndex(repo_root=".")
        index.build_or_update()
    except Exception as exc:
        logger.warning("Codebase index unavailable — skipping related-code context: %s", exc)
        return {}

    exclude = {c.path for c in changes}
    top_files = sorted(changes, key=lambda c: len(c.added_lines) + len(c.removed_lines), reverse=True)[:_MAX_RAG_FILES]
    related: dict[str, list[RelatedChunk]] = {}
    for change in top_files:
        query_text = _file_change_query(change, changed_symbols.get(change.path, []))
        chunks = index.query(query_text, exclude_paths=exclude, top_k=5)
        if chunks:
            related[change.path] = chunks

    return related


def _file_change_query(change: FileChange, symbols: list[str]) -> str:
    """Build a query string representing a file change for embedding lookup."""
    parts = [change.path]
    if symbols:
        parts.append("functions: " + ", ".join(symbols[:10]))
    if change.added_lines:
        parts.append("\n".join(change.added_lines[:20]))
    return "\n".join(parts)


def _build_git_context(
    changes: list[FileChange],
    repo: str,
    github_token: str | None,
) -> tuple[dict[str, FileHistory], list[RecentPR]]:
    """Fetch git history and recent merged PRs for changed files.

    Returns an empty dict/list on any failure so the briefing still works
    without history context.
    """
    file_paths = [c.path for c in changes]

    try:
        git_history = get_file_histories(file_paths, repo_root=".")
        logger.info("Fetched git history for %d files", len(git_history))
    except Exception as exc:
        logger.warning("Git history unavailable: %s", exc)
        git_history = {}

    recent_prs: list[RecentPR] = []
    if github_token:
        try:
            recent_prs = get_recent_merged_prs(file_paths, repo, github_token, repo_root=".")
            logger.info("Found %d recent merged PRs", len(recent_prs))
        except Exception as exc:
            logger.warning("Recent PR lookup failed: %s", exc)

    return git_history, recent_prs


def _format_briefing(
    briefing: Briefing,
    provider_attribution: str | None = None,
    fix_section: str = "",
) -> str:
    """Format structured briefing into markdown comment for GitHub.

    Produces a professional briefing with sections for what changed, blast
    radius, risk flags, and review questions. When fix_section is non-empty
    (ENABLE_FIXES=true), it is inserted between the questions and the footer.
    """
    via = f" via {provider_attribution}" if provider_attribution else ""
    parts: list[str] = [
        "## 🤖 PR Briefing\n",
        "**What changed**\n",
        briefing.what_changed,
        "\n\n**Blast radius**\n",
        briefing.blast_radius,
        "\n\n**Risk flags**\n",
        briefing.risk_flags,
        "\n\n**Questions for the reviewer**\n",
        briefing.questions,
        "\n\n---\n",
    ]

    if fix_section:
        parts.append(fix_section)
        parts.append("\n---\n")

    parts.append(
        f"\n<sub>Generated by [PR Context Engine](https://github.com/paramahastha/pr-context-engine){via}. "
        "Not a substitute for human review.</sub>"
    )

    return "".join(parts)


def _format_error(error: str) -> str:
    """Format a briefing-failure notice as a GitHub PR comment."""
    return (
        "## 🤖 PR Briefing\n\n"
        f"**Briefing failed:** {error}\n\n"
        "Check your API keys and rate limits.\n\n"
        "---\n"
        "\n<sub>Generated by [PR Context Engine](https://github.com/paramahastha/pr-context-engine). "
        "Not a substitute for human review.</sub>"
    )


@app.command()
def quickstart() -> None:
    """Check environment setup and print exactly what is missing before first use."""
    ok = True

    def check(name: str, present: bool, hint: str) -> None:
        nonlocal ok
        if present:
            typer.echo(f"  [ok] {name}")
        else:
            typer.echo(f"  [!!] {name} — {hint}")
            ok = False

    provider = os.environ.get("LLM_PROVIDER", "groq")
    typer.echo("\nChecking provider keys...")
    if provider == "ollama":
        typer.echo("  [ok] LLM_PROVIDER=ollama — no API key required")
    else:
        groq_key = bool(os.environ.get("GROQ_API_KEY"))
        gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
        anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        any_key = groq_key or gemini_key or anthropic_key

        check("GROQ_API_KEY (default provider)", groq_key, "get a free key at https://console.groq.com/keys")
        check("GEMINI_API_KEY (failover)", gemini_key, "optional but recommended — https://aistudio.google.com/apikey")
        if not any_key:
            typer.echo("\n  At least one provider key is required. GROQ_API_KEY is the easiest free option.")

    typer.echo("\nChecking GitHub token...")
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    check("GITHUB_TOKEN", bool(gh_token), "set via `export GITHUB_TOKEN=$(gh auth token)` or pass --github-token")

    if gh_token:
        typer.echo("\nVerifying GitHub token scope...")
        try:
            resp = requests.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {gh_token}", "X-GitHub-Api-Version": "2022-11-28"},
                timeout=8,
            )
            if resp.status_code == 200:
                login = resp.json().get("login", "unknown")
                typer.echo(f"  [ok] Authenticated as {login}")
                scopes = resp.headers.get("X-OAuth-Scopes", "")
                if not scopes:
                    # Fine-grained PATs don't expose X-OAuth-Scopes; assume correct permissions.
                    typer.echo("  [ok] Fine-grained PAT detected — scope check skipped")
                else:
                    has_repo = any(s.strip() in ("repo", "public_repo") for s in scopes.split(","))
                    check(
                        "Token scope (repo or public_repo)",
                        has_repo,
                        "the token needs pull-requests:write; regenerate with repo scope",
                    )
            else:
                typer.echo(f"  [!!] Token check failed (HTTP {resp.status_code}) — token may be invalid")
                ok = False
        except Exception as exc:
            typer.echo(f"  [!!] Could not reach GitHub API: {exc}")
            ok = False

    typer.echo("")
    if ok:
        typer.echo("All checks passed. Run a dry-run to see a briefing before granting write access:")
        typer.echo("  pr-context-engine review --pr <N> --repo <owner/name> --dry-run")
    else:
        typer.echo("Fix the issues above, then re-run `pr-context-engine quickstart`.")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
