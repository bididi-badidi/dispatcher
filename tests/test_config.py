from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.config import build_config
from dispatcher.git import worktree_path_for_issue
from dispatcher.models import Issue


class ConfigTests(unittest.TestCase):
    def test_defaults_to_repo_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                config = build_config(["--repo", "owner/target-repo"])

            repo_root = (dispatcher_dir.parent / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)
            self.assertEqual(
                worktree_path_for_issue(config, Issue(8, "Task", "url")),
                repo_root / "feat" / "issue-8",
            )
            self.assertEqual(
                config.paths.state_file,
                (dispatcher_dir / ".dispatcher" / "state.json").resolve(),
            )
            self.assertEqual(
                config.paths.log_dir,
                (dispatcher_dir / ".dispatcher" / "logs").resolve(),
            )
            self.assertEqual(config.poll_interval_seconds, 120.0)
            self.assertFalse(config.once)

    def test_defaults_to_sibling_repo_from_dispatcher_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_main = Path(temp_dir) / "dispatcher" / "main"
            dispatcher_main.mkdir(parents=True)
            with patch("pathlib.Path.cwd", return_value=dispatcher_main):
                config = build_config(["--repo", "owner/target-repo"])

            repo_root = (Path(temp_dir) / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)
            self.assertEqual(
                worktree_path_for_issue(config, Issue(8, "Task", "url")),
                repo_root / "feat" / "issue-8",
            )
            self.assertEqual(
                config.paths.state_file,
                (dispatcher_main / ".dispatcher" / "state.json").resolve(),
            )
            self.assertEqual(
                config.paths.log_dir,
                (dispatcher_main / ".dispatcher" / "logs").resolve(),
            )

    def test_accepts_poll_interval_and_once_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                config = build_config(
                    ["--repo", "owner/target-repo", "--poll-interval", "30", "--once"]
                )

            self.assertEqual(config.poll_interval_seconds, 30.0)
            self.assertTrue(config.once)

    def test_accepts_daemon_mode_and_worker_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                config = build_config(
                    [
                        "--repo",
                        "owner/target-repo",
                        "--daemon",
                        "--max-workers",
                        "5",
                    ]
                )

            self.assertTrue(config.daemon)
            self.assertEqual(config.max_workers, 5)

    def test_once_and_daemon_modes_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                with self.assertRaises(SystemExit):
                    build_config(["--repo", "owner/target-repo", "--once", "--daemon"])
