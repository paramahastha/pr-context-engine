"""Unit tests for src/context/git_history."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.context.git_history import (
    CommitRecord,
    FileHistory,
    RecentPR,
    _fetch_file_history,
    _fetch_pr_details,
    _find_pr_numbers_from_merges,
    get_file_histories,
    get_recent_merged_prs,
)


# ---------------------------------------------------------------------------
# _fetch_file_history
# ---------------------------------------------------------------------------


def _make_completed_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    import subprocess

    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class TestFetchFileHistory:
    def test_parses_commits(self, tmp_path):
        stdout = (
            "a1b2c3d4e5f6 feat: add retry logic\n"
            "b2c3d4e5f6a1 fix: handle null response\n"
        )
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.file_path == "src/foo.py"
        assert len(history.recent_commits) == 2
        assert history.recent_commits[0] == CommitRecord(sha="a1b2c3d4", message="feat: add retry logic")
        assert history.recent_commits[1] == CommitRecord(sha="b2c3d4e5", message="fix: handle null response")
        assert history.limited_history is False

    def test_sets_limited_history_when_commit_count_hits_limit(self, tmp_path):
        # Exactly max_commits lines returned → may be truncated (shallow clone).
        stdout = "".join(f"{'a' * 12}{i} commit {i}\n" for i in range(5))
        with patch(
            "subprocess.run",
            return_value=_make_completed_process(stdout=stdout),
        ):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.limited_history is True
        assert len(history.recent_commits) == 5

    def test_does_not_set_limited_history_when_below_limit(self, tmp_path):
        stdout = "abc12345 some commit\n"
        with patch(
            "subprocess.run",
            return_value=_make_completed_process(stdout=stdout),
        ):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.limited_history is False
        assert len(history.recent_commits) == 1

    def test_returns_limited_on_subprocess_error(self, tmp_path):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.limited_history is True
        assert history.recent_commits == []

    def test_returns_limited_on_timeout(self, tmp_path):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.limited_history is True
        assert history.recent_commits == []

    def test_returns_limited_when_git_not_found(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.limited_history is True

    def test_ignores_blank_lines(self, tmp_path):
        stdout = "\nabc12345 first commit\n\n"
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert len(history.recent_commits) == 1

    def test_sha_truncated_to_8_chars(self, tmp_path):
        stdout = "abcdef1234567890 some message\n"
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            history = _fetch_file_history("src/foo.py", tmp_path, max_commits=5)

        assert history.recent_commits[0].sha == "abcdef12"

    def test_empty_output(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed_process(stdout="")):
            history = _fetch_file_history("src/new.py", tmp_path, max_commits=5)

        assert history.recent_commits == []
        assert history.limited_history is False


# ---------------------------------------------------------------------------
# _find_pr_numbers_from_merges
# ---------------------------------------------------------------------------


class TestFindPrNumbers:
    def test_parses_standard_github_merge_messages(self, tmp_path):
        stdout = (
            "Merge pull request #42 from user/branch\n"
            "Merge pull request #17 from user/other\n"
        )
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == [42, 17]

    def test_parses_pr_shorthand(self, tmp_path):
        stdout = "Merge PR #99 into main\n"
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == [99]

    def test_parses_squash_merge_format(self, tmp_path):
        stdout = "feat: add retry logic (#123)\n"
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == [123]

    def test_deduplicates_pr_numbers(self, tmp_path):
        stdout = (
            "Merge pull request #10 from user/a\n"
            "Merge pull request #10 from user/b\n"
        )
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == [10]

    def test_returns_empty_on_no_merges(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed_process(stdout="")):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == []

    def test_returns_empty_on_subprocess_error(self, tmp_path):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == []

    def test_returns_empty_on_timeout(self, tmp_path):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            numbers = _find_pr_numbers_from_merges(["src/foo.py"], tmp_path)

        assert numbers == []


# ---------------------------------------------------------------------------
# _fetch_pr_details
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchPrDetails:
    _headers = {"Authorization": "token fake"}

    def test_returns_pr_for_merged(self):
        data = {
            "merged_at": "2024-01-15T12:00:00Z",
            "title": "Add retry logic",
            "body": "This adds exponential backoff.\nSee issue #5.",
        }
        with patch("requests.get", return_value=_mock_response(data)):
            pr = _fetch_pr_details("owner/repo", 42, self._headers)

        assert pr is not None
        assert pr.number == 42
        assert pr.title == "Add retry logic"
        assert pr.body_first_line == "This adds exponential backoff."

    def test_returns_none_for_open_pr(self):
        data = {"merged_at": None, "title": "WIP", "body": ""}
        with patch("requests.get", return_value=_mock_response(data)):
            pr = _fetch_pr_details("owner/repo", 1, self._headers)

        assert pr is None

    def test_returns_none_on_request_exception(self):
        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            pr = _fetch_pr_details("owner/repo", 42, self._headers)

        assert pr is None

    def test_body_first_line_truncated(self):
        long_body = "A" * 300 + "\nSecond line"
        data = {"merged_at": "2024-01-01T00:00:00Z", "title": "T", "body": long_body}
        with patch("requests.get", return_value=_mock_response(data)):
            pr = _fetch_pr_details("owner/repo", 1, self._headers)

        assert pr is not None
        assert len(pr.body_first_line) == 200

    def test_handles_null_body(self):
        data = {"merged_at": "2024-01-01T00:00:00Z", "title": "T", "body": None}
        with patch("requests.get", return_value=_mock_response(data)):
            pr = _fetch_pr_details("owner/repo", 1, self._headers)

        assert pr is not None
        assert pr.body_first_line == ""


# ---------------------------------------------------------------------------
# get_file_histories (integration of _fetch_file_history calls)
# ---------------------------------------------------------------------------


class TestGetFileHistories:
    def test_returns_history_for_all_paths(self, tmp_path):
        stdout = "abc12345 some message\n"
        with patch("subprocess.run", return_value=_make_completed_process(stdout=stdout)):
            result = get_file_histories(["a.py", "b.py"], repo_root=str(tmp_path))

        assert set(result.keys()) == {"a.py", "b.py"}
        assert all(len(h.recent_commits) == 1 for h in result.values())

    def test_empty_file_list(self, tmp_path):
        result = get_file_histories([], repo_root=str(tmp_path))
        assert result == {}


# ---------------------------------------------------------------------------
# get_recent_merged_prs
# ---------------------------------------------------------------------------


class TestGetRecentMergedPrs:
    def test_returns_empty_for_no_files(self):
        result = get_recent_merged_prs([], "owner/repo", "token")
        assert result == []

    def test_full_flow(self, tmp_path):
        git_stdout = "Merge pull request #7 from user/feat\n"
        pr_data = {
            "merged_at": "2024-02-01T10:00:00Z",
            "title": "Add feature X",
            "body": "Implements feature X per spec.",
        }

        with patch(
            "subprocess.run",
            return_value=_make_completed_process(stdout=git_stdout),
        ), patch("requests.get", return_value=_mock_response(pr_data)):
            prs = get_recent_merged_prs(
                ["src/foo.py"], "owner/repo", "token", repo_root=str(tmp_path)
            )

        assert len(prs) == 1
        assert prs[0].number == 7
        assert prs[0].title == "Add feature X"

    def test_respects_max_prs(self, tmp_path):
        git_stdout = (
            "Merge pull request #1 from u/a\n"
            "Merge pull request #2 from u/b\n"
            "Merge pull request #3 from u/c\n"
            "Merge pull request #4 from u/d\n"
        )
        pr_data = {"merged_at": "2024-01-01T00:00:00Z", "title": "PR", "body": ""}

        with patch(
            "subprocess.run",
            return_value=_make_completed_process(stdout=git_stdout),
        ), patch("requests.get", return_value=_mock_response(pr_data)):
            prs = get_recent_merged_prs(
                ["src/foo.py"],
                "owner/repo",
                "token",
                repo_root=str(tmp_path),
                max_prs=2,
            )

        assert len(prs) == 2

    def test_returns_empty_when_no_merge_commits(self, tmp_path):
        with patch(
            "subprocess.run", return_value=_make_completed_process(stdout="")
        ):
            prs = get_recent_merged_prs(
                ["src/foo.py"], "owner/repo", "token", repo_root=str(tmp_path)
            )

        assert prs == []
