"""GitHub REST access for a PR: fetch its unified diff and post a comment.

format_fix_section() renders Milestone 8 fix suggestions as collapsed <details>
blocks (high/medium confidence) or prose warnings (low confidence) suitable for
appending to the main briefing comment body.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests
from github import Auth, Github

from src.github_api import GITHUB_API_URL

if TYPE_CHECKING:
    from src.fixes.fix_generator import FixSuggestion

logger = logging.getLogger(__name__)

_API_VERSION = "2022-11-28"


def fetch_pr_diff(repo: str, pr_number: int, github_token: str) -> str:
    """Fetch the unified diff of a pull request.

    `repo` is in `owner/name` form. Returns the raw unified-diff text.
    """
    url = f"{GITHUB_API_URL}/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github.diff",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    logger.info("Fetching diff for %s PR #%d", repo, pr_number)
    response = requests.get(url, headers=headers, timeout=30)
    if not response.ok:
        logger.error("GitHub API error %d: %s", response.status_code, response.text[:300])
    response.raise_for_status()
    return response.text


def post_pr_comment(repo: str, pr_number: int, body: str, github_token: str) -> None:
    """Post `body` as a general (issue-level) comment on the pull request.

    `repo` is in `owner/name` form.
    """
    logger.info("Posting comment to %s PR #%d", repo, pr_number)
    gh = Github(auth=Auth.Token(github_token))
    pull_request = gh.get_repo(repo).get_pull(pr_number)
    pull_request.create_issue_comment(body)


def format_fix_section(suggestions: list[FixSuggestion], extra_count: int = 0) -> str:
    """Render fix suggestions as a markdown section for appending to the briefing comment.

    High/medium confidence suggestions with a patch become collapsed <details> blocks.
    Low confidence (or missing patch) suggestions become prose warnings only.
    If extra_count > 0, a trailing note indicates how many eligible flags were skipped.

    Args:
        suggestions: List of FixSuggestion objects (may mix confidence levels).
        extra_count: Number of fix-eligible flags beyond the 3-suggestion cap.

    Returns:
        Markdown string ready to append after the briefing's closing `---` line.
        Returns empty string if suggestions is empty.
    """
    # Deferred to avoid pulling src.fixes into comment_poster at module load time;
    # this module is imported by cli.py regardless of whether fixes are enabled.
    from src.fixes.confidence import format_prose_note, format_suggestion_block, is_block_eligible

    if not suggestions:
        return ""

    parts: list[str] = ["\n\n### 💡 Fix Suggestions\n\n"]

    for suggestion in suggestions:
        if is_block_eligible(suggestion):
            parts.append(format_suggestion_block(suggestion))
            parts.append("\n")
        else:
            parts.append(format_prose_note(suggestion))

    if extra_count > 0:
        noun = "issue" if extra_count == 1 else "issues"
        parts.append(f"\n_{extra_count} more {noun} detected — see Risk Flags above._\n")

    return "".join(parts)
