from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.git import (
    BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS,
    BranchLookup,
    branch_exists,
    lookup_branch,
)


class GitTests(unittest.TestCase):
    def test_branch_exists_accepts_remote_tracking_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            local_missing = subprocess.CompletedProcess(args=[], returncode=1)
            remote_tracking_exists = subprocess.CompletedProcess(args=[], returncode=0)

            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=[local_missing, remote_tracking_exists],
            ) as run:
                exists = branch_exists("main", cwd=cwd)

            self.assertTrue(exists)
            self.assertEqual(run.call_count, 2)
            run.assert_any_call(
                ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
                capture_output=True,
                cwd=cwd,
                text=True,
            )
            run.assert_any_call(
                ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/main"],
                capture_output=True,
                cwd=cwd,
                text=True,
            )

    def test_branch_exists_falls_back_to_origin_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            missing_ref = subprocess.CompletedProcess(args=[], returncode=1)
            origin_has_branch = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="abc123\trefs/heads/dev\n",
                stderr="",
            )

            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=[missing_ref, missing_ref, origin_has_branch],
            ) as run:
                self.assertTrue(branch_exists("dev", cwd=cwd))
        run.assert_any_call(
            ["git", "ls-remote", "--heads", "origin", "dev"],
            capture_output=True,
            cwd=cwd,
            text=True,
            timeout=BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS,
        )

    def test_lookup_branch_without_cwd_returns_unknown(self) -> None:
        with patch("dispatcher.git.subprocess.run") as run:
            result = lookup_branch("main")

        self.assertIs(result, BranchLookup.UNKNOWN)
        run.assert_not_called()

    def test_lookup_branch_returns_absent_for_clean_remote_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            missing_ref = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            )
            remote_missing = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=[missing_ref, missing_ref, remote_missing],
            ):
                result = lookup_branch("missing", cwd=cwd)

        self.assertIs(result, BranchLookup.ABSENT)

    def test_lookup_branch_returns_unknown_when_git_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=FileNotFoundError("git"),
            ):
                result = lookup_branch("main", cwd=cwd)

        self.assertIs(result, BranchLookup.UNKNOWN)

    def test_lookup_branch_returns_unknown_when_remote_lookup_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            missing_ref = subprocess.CompletedProcess(args=[], returncode=1)

            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=[
                    missing_ref,
                    missing_ref,
                    subprocess.TimeoutExpired(
                        ["git", "ls-remote", "--heads", "origin", "dev"],
                        BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS,
                    ),
                ],
            ):
                result = lookup_branch("dev", cwd=cwd)

        self.assertIs(result, BranchLookup.UNKNOWN)

    def test_branch_exists_returns_false_when_origin_lookup_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            missing_ref = subprocess.CompletedProcess(args=[], returncode=1)

            with patch(
                "dispatcher.git.subprocess.run",
                side_effect=[
                    missing_ref,
                    missing_ref,
                    subprocess.TimeoutExpired(
                        ["git", "ls-remote", "--heads", "origin", "dev"],
                        BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS,
                    ),
                ],
            ):
                self.assertFalse(branch_exists("dev", cwd=cwd))

    def test_branch_exists_returns_false_for_missing_cwd(self) -> None:
        with patch("dispatcher.git.subprocess.run") as run:
            exists = branch_exists("main", cwd=Path("/missing/repo"))

        self.assertFalse(exists)
        run.assert_not_called()

    def test_lookup_branch_returns_unknown_for_missing_cwd(self) -> None:
        with patch("dispatcher.git.subprocess.run") as run:
            result = lookup_branch("main", cwd=Path("/missing/repo"))

        self.assertIs(result, BranchLookup.UNKNOWN)
        run.assert_not_called()
