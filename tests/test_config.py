from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.config import build_config, load_env_file
from dispatcher.git import worktree_path_for_issue
from dispatcher.models import Issue
from dispatcher.repo_context import config_for_repo


class ConfigTests(unittest.TestCase):
    def test_defaults_to_repo_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                config = build_config([])

            repo_root = (Path("/Projects") / "target-repo").resolve()
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
            self.assertEqual(config.opus_label, "automate:opus")
            self.assertEqual(config.opus_model, "claude-opus-4-7")

    def test_dispatcher_root_dir_env_overrides_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd_dir = Path(temp_dir) / "cwd"
            root_dir = Path(temp_dir) / "dispatcher-root"
            cwd_dir.mkdir()
            root_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=cwd_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/target-repo",
                        "DISPATCHER_ROOT_DIR": str(root_dir),
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

            repo_root = (Path("/Projects") / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)
            self.assertEqual(
                config.paths.state_file,
                (root_dir / ".dispatcher" / "state.json").resolve(),
            )
            self.assertEqual(
                config.paths.log_dir,
                (root_dir / ".dispatcher" / "logs").resolve(),
            )

    def test_projects_dir_env_overrides_default_repo_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            projects_dir = Path(temp_dir) / "custom-projects"
            dispatcher_dir.mkdir()
            projects_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/target-repo",
                        "DISPATCHER_PROJECTS_DIR": str(projects_dir),
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

            repo_root = (projects_dir / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)

    def test_dispatcher_root_dir_unset_falls_back_to_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                config = build_config([])

            repo_root = (Path("/Projects") / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)
            self.assertEqual(
                config.paths.state_file,
                (dispatcher_dir / ".dispatcher" / "state.json").resolve(),
            )

    def test_dispatcher_root_dir_expands_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd_dir = Path(temp_dir) / "cwd"
            home_dir = Path(temp_dir) / "home"
            cwd_dir.mkdir()
            home_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=cwd_dir),
                patch.dict(
                    "os.environ",
                    {
                        "HOME": str(home_dir),
                        "DISPATCHER_REPO": "owner/target-repo",
                        "DISPATCHER_ROOT_DIR": "~/dispatcher",
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

            root_dir = (home_dir / "dispatcher").resolve()
            self.assertEqual(
                config.paths.state_file,
                (root_dir / ".dispatcher" / "state.json").resolve(),
            )

    def test_dispatcher_root_dir_resolves_relative_paths(self) -> None:
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                with patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/target-repo",
                        "DISPATCHER_ROOT_DIR": "relative-dispatcher",
                    },
                    clear=True,
                ):
                    config = build_config([])
            finally:
                os.chdir(previous_cwd)

            root_dir = (Path(temp_dir) / "relative-dispatcher").resolve()
            self.assertEqual(
                config.paths.state_file,
                (root_dir / ".dispatcher" / "state.json").resolve(),
            )
            self.assertTrue(config.paths.state_file.is_absolute())

    def test_repo_context_ignores_dispatcher_root_dir_for_repo_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd_dir = Path(temp_dir) / "cwd"
            root_dir = Path(temp_dir) / "dispatcher-root"
            state_dir = Path(temp_dir) / "custom-state"
            cwd_dir.mkdir()
            root_dir.mkdir()
            state_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=cwd_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/source-repo",
                        "DISPATCHER_ROOT_DIR": str(root_dir),
                    },
                    clear=True,
                ),
            ):
                config = build_config(["--state-file", str(state_dir / "state.json")])
                repo_config = config_for_repo(config, "owner/target-repo")

            repo_root = (Path("/Projects") / "target-repo").resolve()
            self.assertEqual(repo_config.paths.project_dir, repo_root / "main")
            self.assertEqual(repo_config.paths.worktree_root, repo_root)

    def test_repo_context_uses_projects_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            projects_dir = Path(temp_dir) / "custom-projects"
            state_dir = Path(temp_dir) / "custom-state"
            dispatcher_dir.mkdir()
            projects_dir.mkdir()
            state_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/source-repo",
                        "DISPATCHER_PROJECTS_DIR": str(projects_dir),
                    },
                    clear=True,
                ),
            ):
                config = build_config(["--state-file", str(state_dir / "state.json")])
                repo_config = config_for_repo(config, "owner/target-repo")

            repo_root = (projects_dir / "target-repo").resolve()
            self.assertEqual(repo_config.paths.project_dir, repo_root / "main")
            self.assertEqual(repo_config.paths.worktree_root, repo_root)

    def test_reads_opus_label_and_model_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/target-repo",
                        "DISPATCHER_OPUS_LABEL": "needs-opus",
                        "DISPATCHER_OPUS_MODEL": "claude-opus-4-5",
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

            self.assertEqual(config.opus_label, "needs-opus")
            self.assertEqual(config.opus_model, "claude-opus-4-5")

    def test_repo_paths_do_not_derive_from_dispatcher_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_main = Path(temp_dir) / "dispatcher" / "main"
            dispatcher_main.mkdir(parents=True)
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_main),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                config = build_config([])

            repo_root = (Path("/Projects") / "target-repo").resolve()
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
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                config = build_config(["--poll-interval", "30", "--once"])

            self.assertEqual(config.poll_interval_seconds, 30.0)
            self.assertTrue(config.once)

    def test_accepts_daemon_mode_and_worker_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                config = build_config(
                    [
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
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
            ):
                with self.assertRaises(SystemExit):
                    build_config(["--once", "--daemon"])

    def test_reads_redis_url_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {"DISPATCHER_REDIS_URL": "redis://localhost:6379/0"},
                    clear=True,
                ),
            ):
                config = build_config([])

        self.assertIsNone(config.repo)
        self.assertEqual(config.redis_url, "redis://localhost:6379/0")
        self.assertEqual(config.redis_poll_interval, 60)

    def test_reads_single_repo_fallback_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
            ):
                config = build_config([])

        self.assertEqual(config.repo, "owner/repo")
        self.assertIsNone(config.redis_url)

    def test_loads_dotenv_before_reading_environment_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            (dispatcher_dir / ".env").write_text(  # pragma: allowlist secret
                "\n".join(
                    [
                        "DISPATCHER_REPO=owner/dotenv-repo",
                        "DISPATCHER_LABEL='from-dotenv' # comment",
                        "DISPATCHER_POLL_INTERVAL_SECONDS=45 # seconds",
                    ]
                )
            )

            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {}, clear=True),
            ):
                config = build_config([])

        self.assertEqual(config.repo, "owner/dotenv-repo")
        self.assertEqual(config.label, "from-dotenv")
        self.assertEqual(config.poll_interval_seconds, 45.0)

    def test_dotenv_does_not_override_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "DISPATCHER_REPO=owner/from-dotenv\n"  # pragma: allowlist secret
            )

            with patch.dict(
                "os.environ", {"DISPATCHER_REPO": "owner/from-shell"}, clear=True
            ):
                load_env_file(env_file)

                self.assertEqual(os.environ["DISPATCHER_REPO"], "owner/from-shell")

    def test_requires_redis_url_or_single_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {}, clear=True),
            ):
                with self.assertRaisesRegex(SystemExit, "DISPATCHER_REDIS_URL"):
                    build_config([])
