"""GitHub REST access for a PR: fetch its unified diff and post a comment."""
import logging

import requests
from github import Auth, Github

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_API_VERSION = "2022-11-28"


def fetch_pr_diff(repo: str, pr_number: int, github_token: str) -> str:
    """Fetch the unified diff of a pull request.

    `repo` is in `owner/name` form. Returns the raw unified-diff text.
    """
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github.diff",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    logger.info("Fetching diff for %s PR #%d", repo, pr_number)
    response = requests.get(url, headers=headers, timeout=30)
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
