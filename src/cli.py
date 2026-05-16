"""Typer CLI — the single entrypoint; orchestrates fetch-diff, analyze, summarize, post."""
import logging

import typer
from dotenv import load_dotenv

from src.analyzers.ast_walker import extract_changed_symbols
from src.analyzers.diff_parser import FileChange, parse_diff
from src.analyzers.risk_scorer import RiskFlag, score
from src.config import get_provider
from src.github_api.comment_poster import fetch_pr_diff, post_pr_comment

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer(help="PR Context Engine — brief a pull request.")

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
    """Fetch a PR's diff, analyze it structurally, and post an AI-generated briefing."""
    if not github_token:
        raise typer.BadParameter("GITHUB_TOKEN is not set (flag or env var).")

    raw_diff = fetch_pr_diff(repo, pr, github_token)
    logger.info("Fetched diff (%d chars)", len(raw_diff))
    if len(raw_diff) > _MAX_DIFF_CHARS:
        logger.warning("Diff truncated from %d to %d chars", len(raw_diff), _MAX_DIFF_CHARS)
        raw_diff = raw_diff[:_MAX_DIFF_CHARS]

    changes = parse_diff(raw_diff)
    logger.info("Parsed %d file changes", len(changes))

    changed_symbols: dict[str, list[str]] = {}
    for change in changes:
        syms = extract_changed_symbols(change)
        if syms:
            changed_symbols[change.path] = syms

    flags = score(changes)
    logger.info("Detected %d risk flags", len(flags))

    prompt = _build_prompt(changes, changed_symbols, flags)

    try:
        provider = get_provider()
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc

    summary = provider.generate(prompt)
    logger.info("Generated summary (%d chars)", len(summary))

    post_pr_comment(repo, pr, summary, github_token)
    logger.info("Comment posted to %s PR #%d", repo, pr)


def _build_prompt(
    changes: list[FileChange],
    changed_symbols: dict[str, list[str]],
    flags: list[RiskFlag],
) -> str:
    """Assemble a structured context prompt from parsed diff data.

    Sends file-level metadata, touched symbol names, and risk flags instead of
    raw diff text so the LLM reasons about intent rather than line noise.
    """
    parts: list[str] = [
        "Summarize this pull request as a senior backend engineer would.\n",
        "## Changed files\n",
    ]

    for change in changes:
        if change.is_new_file:
            action = "new file"
        elif change.is_deleted_file:
            action = "deleted"
        else:
            action = "modified"

        symbols = changed_symbols.get(change.path, [])
        symbol_str = f" — symbols: {', '.join(symbols)}" if symbols else ""
        parts.append(
            f"- `{change.path}` ({change.language}, {action})"
            f" +{len(change.added_lines)}/-{len(change.removed_lines)} lines{symbol_str}"
        )

    parts.append("\n## Risk flags\n")
    if flags:
        for flag in flags:
            loc = f":{flag.line}" if flag.line is not None else ""
            parts.append(f"- [{flag.flag}] `{flag.file}{loc}` — {flag.snippet}")
    else:
        parts.append("None detected.")

    parts.append(
        "\n## Instructions\n"
        "Be terse. No praise. No 'this looks good.' "
        "Summarize what changed, what could break, and the top risk. "
        "Under 150 words."
    )

    return "\n".join(parts)


if __name__ == "__main__":
    app()
