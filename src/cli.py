"""Typer CLI — the single entrypoint; orchestrates fetch-diff, summarize, post."""
import logging

import typer
from dotenv import load_dotenv

from src.config import get_provider
from src.github_api.comment_poster import fetch_pr_diff, post_pr_comment

load_dotenv()  # populate env from a local .env for dev; harmless no-op in CI
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer(help="PR Context Engine — brief a pull request.")

_PROMPT_TEMPLATE = "Summarize this diff in 3 bullets:\n\n{diff}"
_MAX_DIFF_CHARS = 32_000  # ~8k tokens; avoids hitting provider context limits on large PRs


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
    """Fetch a PR's diff, summarize it with the configured LLM, and post the result."""
    if not github_token:
        raise typer.BadParameter("GITHUB_TOKEN is not set (flag or env var).")

    diff = fetch_pr_diff(repo, pr, github_token)
    logger.info("Fetched diff (%d chars)", len(diff))
    if len(diff) > _MAX_DIFF_CHARS:
        logger.warning("Diff truncated from %d to %d chars", len(diff), _MAX_DIFF_CHARS)
        diff = diff[:_MAX_DIFF_CHARS]

    try:
        provider = get_provider()
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    summary = provider.generate(_PROMPT_TEMPLATE.format(diff=diff))
    logger.info("Generated summary (%d chars)", len(summary))

    post_pr_comment(repo, pr, summary, github_token)
    logger.info("Comment posted to %s PR #%d", repo, pr)


if __name__ == "__main__":
    app()
