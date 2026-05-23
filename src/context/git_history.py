"""Git history context for changed files.

Fetches the last N commit messages per file via git log, and optionally
resolves the most recent merged PRs that touched the same files via the
GitHub REST API.

Degrades gracefully on shallow clones (workflow uses fetch-depth: 50) or
when git/network is unavailable — callers receive limited_history=True and
an empty commit list rather than an exception.  See docs/design-decisions.md
for the deliberate shallow-clone tradeoff.
"""
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests

from src.github_api import GITHUB_API_URL

logger = logging.getLogger(__name__)

_GIT_LOG_LIMIT = 5
_PR_MERGE_SCAN = 30  # merge commits to scan when searching for PR numbers
_MAX_PRS = 3
_REQUEST_TIMEOUT = 10


@dataclass
class CommitRecord:
    """A single commit's abbreviated hash and subject line."""

    sha: str
    message: str


@dataclass
class FileHistory:
    """Recent commit history for one changed file."""

    file_path: str
    recent_commits: list[CommitRecord] = field(default_factory=list)
    limited_history: bool = False


@dataclass
class RecentPR:
    """A recently merged PR that touched one of the changed files."""

    number: int
    title: str
    body_first_line: str


def get_file_histories(
    file_paths: list[str],
    repo_root: str = ".",
    max_commits: int = _GIT_LOG_LIMIT,
) -> dict[str, FileHistory]:
    """Return recent commit history for each file path.

    Args:
        file_paths: Repo-relative paths of changed files.
        repo_root: Root of the git repository.
        max_commits: Maximum commits to fetch per file.

    Returns:
        Mapping of file_path -> FileHistory. Files with no discoverable
        history still get an entry (empty commits, limited_history=True).
    """
    root = Path(repo_root).resolve()
    return {path: _fetch_file_history(path, root, max_commits) for path in file_paths}


def get_recent_merged_prs(
    file_paths: list[str],
    repo: str,
    github_token: str,
    repo_root: str = ".",
    max_prs: int = _MAX_PRS,
) -> list[RecentPR]:
    """Find the most recent merged PRs that touched any of the given files.

    Uses git merge-commit messages to locate PR numbers, then fetches details
    via the GitHub API.  Returns an empty list when git or the API is
    unavailable rather than raising.

    Args:
        file_paths: Repo-relative paths of changed files.
        repo: Repository in "owner/name" form.
        github_token: GitHub token used for API requests.
        repo_root: Root of the git repository.
        max_prs: Maximum number of PRs to return.

    Returns:
        List of RecentPR, most recent first.
    """
    if not file_paths:
        return []

    root = Path(repo_root).resolve()
    pr_numbers = _find_pr_numbers_from_merges(file_paths, root)
    if not pr_numbers:
        return []

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    prs: list[RecentPR] = []
    for pr_number in pr_numbers:
        if len(prs) >= max_prs:
            break
        pr = _fetch_pr_details(repo, pr_number, headers)
        if pr is not None:
            prs.append(pr)

    return prs


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fetch_file_history(path: str, root: Path, max_commits: int) -> FileHistory:
    """Run git log for a single file and return its FileHistory."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--follow",
                f"--max-count={max_commits}",
                "--format=%H %s",
                "--",
                path,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("git log failed for %s: %s", path, exc)
        return FileHistory(file_path=path, limited_history=True)

    commits: list[CommitRecord] = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        sha, _, message = line.partition(" ")
        commits.append(CommitRecord(sha=sha[:8], message=message))

    # git log silently returns fewer commits on shallow clones without any
    # stderr output; hitting the limit is the only reliable signal.
    limited = len(commits) == max_commits

    return FileHistory(file_path=path, recent_commits=commits, limited_history=limited)


def _find_pr_numbers_from_merges(file_paths: list[str], root: Path) -> list[int]:
    """Extract PR numbers from merge commits that touched any of the given files."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--merges",
                f"--max-count={_PR_MERGE_SCAN}",
                "--format=%s",
                "--",
                *file_paths,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("git log --merges failed: %s", exc)
        return []

    # Matches:
    #   "Merge pull request #N from ..." (GitHub standard merge)
    #   "Merge PR #N ..."               (shorthand)
    #   "feat: something (#N)"          (GitHub squash merge)
    pattern = re.compile(r"(?:(?:pull\s+request|PR)\s+#(\d+)|\(#(\d+)\))", re.IGNORECASE)
    seen: set[int] = set()
    numbers: list[int] = []

    for line in result.stdout.strip().splitlines():
        match = pattern.search(line)
        if match:
            num = int(match.group(1) or match.group(2))
            if num not in seen:
                seen.add(num)
                numbers.append(num)

    return numbers


def _fetch_pr_details(repo: str, pr_number: int, headers: dict[str, str]) -> RecentPR | None:
    """Fetch PR title and body from GitHub API; returns None when unavailable."""
    url = f"{GITHUB_API_URL}/repos/{repo}/pulls/{pr_number}"
    try:
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("GitHub API request failed for PR #%d: %s", pr_number, exc)
        return None

    data = resp.json()
    if not data.get("merged_at"):
        return None  # ignore open or closed-unmerged PRs

    title = (data.get("title") or "").strip()
    body = data.get("body") or ""
    body_first_line = body.split("\n")[0].strip()[:200]

    return RecentPR(number=pr_number, title=title, body_first_line=body_first_line)
