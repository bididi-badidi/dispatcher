from __future__ import annotations

import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import dispatcher.config as config_module
from dispatcher.config import build_config, load_env_file
from dispatcher.git import worktree_path_for_issue
from dispatcher.models import Issue
from dispatcher.repo_context import config_for_repo


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        config_module._WARNED_BASE_BRANCH_FALLBACKS.clear()
        self.branch_exists_patcher = patch(
            "dispatcher.config.branch_exists", return_value=True
        )
        self.branch_exists_patcher.start()
        self.addCleanup(self.branch_exists_patcher.stop)
        self.checkout_exists_patcher = patch(
            "dispatcher.config.checkout_exists", return_value=True
        )
        self.checkout_exists_patcher.start()
        self.addCleanup(self.checkout_exists_patcher.stop)

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
            self.assertFalse(config.debug)
            self.assertEqual(config.opus_label, "automate:opus")
            self.assertEqual(config.opus_model, "claude-opus-4-7")

    def test_base_branch_exists_is_used_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
                patch("dispatcher.config.branch_exists", return_value=True),
            ):
                config = build_config(["--base-branch", "dev"])

        self.assertEqual(config.base_branch, "dev")

    def test_missing_base_branch_warns_and_falls_back_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                with patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True
                ):
                    with patch(
                        "dispatcher.config.branch_exists",
                        side_effect=lambda branch, cwd=None: branch == "main",
                    ):
                        with self.assertWarns(UserWarning) as warning:
                            config = build_config(["--base-branch", "dev"])

        self.assertEqual(config.base_branch, "main")
        warning_message = str(warning.warning)
        self.assertEqual(
            warning_message,
            "Branch 'dev' unavailable for owner/repo; "
            "using 'main' (missing checkout: /Projects/repo/dev).",
        )
        self.assertNotIn("Branch check context", warning_message)

    def test_missing_base_branch_checkout_falls_back_to_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            projects_dir = Path(temp_dir) / "Projects"
            dispatcher_dir.mkdir()
            projects_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/Portfolio-Web",
                        "DISPATCHER_PROJECTS_DIR": str(projects_dir),
                    },
                    clear=True,
                ),
                patch(
                    "dispatcher.config.checkout_exists",
                    side_effect=lambda path: path.name == "main",
                ),
                patch("dispatcher.config.branch_exists", return_value=True),
                self.assertWarns(UserWarning) as warning,
            ):
                config = build_config(["--base-branch", "dev"])

        repo_root = (projects_dir / "Portfolio-Web").resolve()
        self.assertEqual(config.base_branch, "main")
        self.assertEqual(config.paths.project_dir, repo_root / "main")
        warning_message = str(warning.warning)
        self.assertEqual(
            warning_message,
            "Branch 'dev' unavailable for owner/Portfolio-Web; "
            f"using 'main' (missing checkout: {repo_root / 'dev'}).",
        )
        self.assertNotIn("Branch check context", warning_message)

    def test_missing_base_branch_and_main_raises_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
                patch("dispatcher.config.branch_exists", return_value=False),
                self.assertWarns(UserWarning),
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "fallback 'main' is not available",
                ):
                    build_config(["--base-branch", "dev"])

    def test_missing_base_branch_error_includes_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
                patch("dispatcher.config.branch_exists", return_value=False),
                self.assertWarns(UserWarning),
            ):
                with self.assertRaises(SystemExit) as raised:
                    build_config(["--base-branch", "dev"])

        message = str(raised.exception)
        self.assertIn("branch 'dev' is not available", message)
        self.assertIn("repo=owner/repo", message)
        self.assertIn("requested_branch=dev", message)
        self.assertIn("fallback_branch=main", message)
        self.assertIn("check_cwd=", message)
        self.assertIn("project_dir=", message)
        self.assertIn("worktree_root=", message)

    def test_missing_default_base_branch_raises_without_fallback_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
                patch("dispatcher.config.branch_exists", return_value=False),
            ):
                with warnings.catch_warnings(record=True) as caught:
                    with self.assertRaisesRegex(
                        SystemExit,
                        "branch 'main' is not available",
                    ):
                        build_config([])

            self.assertEqual(caught, [])

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

    def test_loads_env_file_from_dispatcher_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd_dir = Path(temp_dir) / "cwd"
            root_dir = Path(temp_dir) / "dispatcher-root"
            cwd_dir.mkdir()
            root_dir.mkdir()
            (cwd_dir / ".env").write_text("DISPATCHER_REPO=owner/cwd-repo\n")
            (root_dir / ".env").write_text("DISPATCHER_REPO=owner/root-repo\n")
            with (
                patch("pathlib.Path.cwd", return_value=cwd_dir),
                patch.dict(
                    "os.environ",
                    {"DISPATCHER_ROOT_DIR": str(root_dir)},
                    clear=True,
                ),
            ):
                config = build_config([])

            self.assertEqual(config.repo, "owner/root-repo")
            repo_root = (Path("/Projects") / "root-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(
                config.paths.state_file,
                (root_dir / ".dispatcher" / "state.json").resolve(),
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

    def test_repo_context_falls_back_when_repo_branch_checkout_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            projects_dir = Path(temp_dir) / "Projects"
            dispatcher_dir.mkdir()
            projects_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REDIS_URL": "redis://example",
                        "DISPATCHER_PROJECTS_DIR": str(projects_dir),
                    },
                    clear=True,
                ),
                patch(
                    "dispatcher.config.checkout_exists",
                    side_effect=lambda path: path.name == "main",
                ),
                patch("dispatcher.config.branch_exists", return_value=True),
                self.assertWarns(UserWarning),
            ):
                config = build_config(["--base-branch", "dev"])
                repo_config = config_for_repo(config, "owner/Portfolio-Web")

            repo_root = (projects_dir / "Portfolio-Web").resolve()
            self.assertEqual(config.base_branch, "dev")
            self.assertEqual(repo_config.base_branch, "main")
            self.assertEqual(repo_config.paths.project_dir, repo_root / "main")

    def test_repo_context_warns_once_for_repeated_branch_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            projects_dir = Path(temp_dir) / "Projects"
            dispatcher_dir.mkdir()
            projects_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REDIS_URL": "redis://example",
                        "DISPATCHER_PROJECTS_DIR": str(projects_dir),
                    },
                    clear=True,
                ),
                patch(
                    "dispatcher.config.checkout_exists",
                    side_effect=lambda path: path.name == "main",
                ),
                patch("dispatcher.config.branch_exists", return_value=True),
                warnings.catch_warnings(record=True) as caught,
            ):
                warnings.simplefilter("always")
                config = build_config(["--base-branch", "dev"])
                first = config_for_repo(config, "bididi-badidi/deep-research")
                second = config_for_repo(config, "bididi-badidi/deep-research")

            self.assertEqual(first.base_branch, "main")
            self.assertEqual(second.base_branch, "main")
            branch_warnings = [
                warning
                for warning in caught
                if "Branch 'dev' unavailable" in str(warning.message)
            ]
            self.assertEqual(len(branch_warnings), 1)

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

    def test_reads_debug_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/repo",
                        "DISPATCHER_DEBUG": "1",
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

        self.assertTrue(config.debug)

    def test_accepts_debug_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
            ):
                config = build_config(["--debug"])

        self.assertTrue(config.debug)

    def test_aws_s3_log_bucket_env_populates_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ",
                    {
                        "DISPATCHER_REPO": "owner/repo",
                        "AWS_S3_LOG_BUCKET": "dispatcher-logs",
                        "AWS_S3_LOG_KEY_PREFIX": "prod",
                    },
                    clear=True,
                ),
            ):
                config = build_config([])

        self.assertEqual(config.s3_log_bucket, "dispatcher-logs")
        self.assertEqual(config.s3_log_key_prefix, "prod")

    def test_aws_s3_log_bucket_unset_leaves_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict("os.environ", {"DISPATCHER_REPO": "owner/repo"}, clear=True),
            ):
                config = build_config([])

        self.assertIsNone(config.s3_log_bucket)

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
