"""Typer CLI — the single entrypoint; orchestrates fetch-diff, analyze, summarize, post."""
import logging

import typer
from dotenv import load_dotenv

from src.analyzers.ast_walker import extract_changed_symbols
from src.analyzers.diff_parser import FileChange, parse_diff
from src.analyzers.risk_scorer import score
from src.briefing.generator import Briefing, generate_briefing
from src.config import get_provider
from src.context.codebase_index import CodebaseIndex, RelatedChunk
from src.github_api.comment_poster import fetch_pr_diff, post_pr_comment

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer(help="PR Context Engine — brief a pull request.")

_MAX_DIFF_LINES = 4_000  # ~8k tokens; avoids hitting provider context limits on large PRs


@app.callback()
def main() -> None:
    """PR Context Engine — brief a pull request for human reviewers.

    This callback exists so Typer keeps `review` as an explicit subcommand. A
    single-command Typer app otherwise collapses the command and drops its name,
    which would break the documented `pr-context-engine review ...` invocation.
    """


@app.command()
def review(
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    repo: str = typer.Option(..., "--repo", help="Repository in owner/name form."),
    github_token: str | None = typer.Option(
        None, envvar="GITHUB_TOKEN", help="GitHub token with pull-requests:write."
    ),
) -> None:
    """Fetch a PR's diff, analyze it structurally, and post an AI-generated briefing."""
    if not github_token:
        raise typer.BadParameter("GITHUB_TOKEN is not set (flag or env var).")

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

    try:
        provider = get_provider()
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc

    briefing = generate_briefing(provider, changes, changed_symbols, flags, related_code)
    logger.info("Generated briefing sections")

    comment_text = _format_briefing(briefing)
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
    related: dict[str, list[RelatedChunk]] = {}
    for change in changes:
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


def _format_briefing(briefing: Briefing) -> str:
    """Format structured briefing into markdown comment for GitHub.

    Produces a professional briefing with sections for what changed, blast
    radius, risk flags, and review questions.
    """
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
        "\n<sub>Generated by [PR Context Engine](https://github.com/anthropics/pr-context-engine). "
        "Not a substitute for human review.</sub>",
    ]

    return "".join(parts)


if __name__ == "__main__":
    app()
