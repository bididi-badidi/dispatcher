from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.cleanup import cleanup_merged_branch, remove_local_worktree


class CleanupTests(unittest.TestCase):
    def test_cleanup_merged_branch_deletes_remote_and_local_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            worktree = project_dir.parent / "repo" / "feat" / "issue-9"

            with patch("dispatcher.cleanup.subprocess.run") as run:
                cleanup_merged_branch("feat/issue-9", worktree, project_dir)

            self.assertEqual(
                [call.args[0] for call in run.call_args_list],
                [
                    ["git", "push", "origin", "--delete", "feat/issue-9"],
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    ["git", "branch", "-d", "feat/issue-9"],
                ],
            )

    def test_remove_local_worktree_force_deletes_branch_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            worktree = project_dir.parent / "repo" / "feat" / "issue-9"

            with patch("dispatcher.cleanup.subprocess.run") as run:
                run.side_effect = [
                    None,
                    subprocess.CalledProcessError(1, ["git", "branch", "-d"]),
                    None,
                ]

                remove_local_worktree(worktree, "feat/issue-9", project_dir)

            self.assertEqual(
                [call.args[0] for call in run.call_args_list],
                [
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    ["git", "branch", "-d", "feat/issue-9"],
                    ["git", "branch", "-D", "feat/issue-9"],
                ],
            )
