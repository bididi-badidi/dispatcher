from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import main as legacy_main
from dispatcher.cli import (
    _configure_logging,
    _log_tracking_summary,
    _run_daemon,
    main,
    run_polling_loop,
)
from dispatcher.git import BranchLookup
from dispatcher.state import StateStore
from tests.helpers import make_config


class CliTests(unittest.TestCase):
    def test_configure_logging_defaults_to_info_message_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))

            with patch("dispatcher.cli.logging.basicConfig") as basic_config:
                _configure_logging(config)

            basic_config.assert_called_once_with(
                level=logging.INFO, format="%(message)s", force=True
            )

    def test_configure_logging_uses_debug_level_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir))
            config = replace(config, debug=True)

            with patch("dispatcher.cli.logging.basicConfig") as basic_config:
                _configure_logging(config)

            basic_config.assert_called_once_with(
                level=logging.DEBUG, format="%(message)s", force=True
            )

    def test_main_runs_daemon_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
                patch(
                    "dispatcher.config.lookup_branch",
                    return_value=BranchLookup.PRESENT,
                ),
                patch("dispatcher.config.checkout_exists", return_value=True),
                patch("dispatcher.cli._run_daemon", return_value=0) as run_daemon,
            ):
                result = main(["--daemon"])

            self.assertEqual(result, 0)
            self.assertEqual(run_daemon.call_count, 1)
            self.assertIs(legacy_main.main, main)

    def test_tracking_summary_printed_on_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
                patch(
                    "dispatcher.config.lookup_branch",
                    return_value=BranchLookup.PRESENT,
                ),
                patch("dispatcher.config.checkout_exists", return_value=True),
                patch("dispatcher.cli.run_once", return_value=False),
                patch("builtins.print") as print_,
            ):
                result = main(["--once"])

            self.assertEqual(result, 0)
            print_.assert_any_call(
                "tracking 1 repo(s) base_branch=main fallback_branch=main"
            )

    def test_tracking_summary_printed_before_polling_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()

            def stop_polling(config, store) -> None:
                print(
                    f"Polling for label {config.label!r} every "
                    f"{config.poll_interval_seconds:g} seconds. Press Ctrl-C to stop."
                )
                raise KeyboardInterrupt()

            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
                patch(
                    "dispatcher.config.lookup_branch",
                    return_value=BranchLookup.PRESENT,
                ),
                patch("dispatcher.config.checkout_exists", return_value=True),
                patch("dispatcher.cli.run_polling_loop", side_effect=stop_polling),
                patch("builtins.print") as print_,
            ):
                result = main([])

            self.assertEqual(result, 130)
            calls = [call.args[0] for call in print_.call_args_list]
            self.assertLess(
                calls.index("tracking 1 repo(s) base_branch=main fallback_branch=main"),
                calls.index(
                    "Polling for label 'automate' every "
                    "120 seconds. Press Ctrl-C to stop."
                ),
            )

    def test_tracking_summary_reflects_redis_repo_count(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = make_config(root, repo=None)

        class RedisStore:
            def get_repos(self) -> list[str]:
                return ["a/b", "c/d"]

            def get(self, repo: str, issue_number: int) -> None:
                return None

            def upsert(self, repo, state) -> None:
                raise AssertionError("unexpected write")

        with patch("builtins.print") as print_:
            _log_tracking_summary(config, RedisStore())

        print_.assert_called_once_with(
            "tracking 2 repo(s) base_branch=main fallback_branch=main"
        )

    def test_tracking_summary_printed_on_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
                patch(
                    "dispatcher.config.lookup_branch",
                    return_value=BranchLookup.PRESENT,
                ),
                patch("dispatcher.config.checkout_exists", return_value=True),
                patch("dispatcher.cli._run_daemon", return_value=0),
                patch("builtins.print") as print_,
            ):
                result = main(["--daemon"])

            self.assertEqual(result, 0)
            print_.assert_any_call(
                "tracking 1 repo(s) base_branch=main fallback_branch=main"
            )

    def test_daemon_returns_keyboard_interrupt_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)

            with (
                patch("dispatcher.queue.Dispatcher.run", side_effect=KeyboardInterrupt),
                patch("builtins.print") as print_,
            ):
                result = _run_daemon(config, store)

            self.assertEqual(result, 130)
            print_.assert_called_once_with("Stopping dispatcher daemon.")

    def test_polling_loop_repeats_after_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)

            with patch("dispatcher.cli.run_once") as run_once:
                with (
                    patch("builtins.print") as print_,
                    self.assertRaises(KeyboardInterrupt),
                ):
                    run_polling_loop(
                        config,
                        store,
                        sleep=lambda seconds: (_ for _ in ()).throw(
                            KeyboardInterrupt()
                        ),
                    )

            run_once.assert_called_once_with(config, store)
            print_.assert_called_once_with(
                "Polling for label 'automate' every 120 seconds. Press Ctrl-C to stop."
            )

    def test_polling_loop_continues_after_cycle_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            calls = []

            def sleep(seconds: float) -> None:
                calls.append(seconds)
                raise KeyboardInterrupt()

            with patch("dispatcher.cli.run_once", side_effect=RuntimeError("boom")):
                with (
                    patch("builtins.print"),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    run_polling_loop(config, store, sleep=sleep)

            self.assertEqual(calls, [120.0])

    def test_tracking_summary_tolerates_repo_count_error(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = make_config(root, repo=None)

        class FailingRepoStore:
            def get_repos(self) -> list[str]:
                raise RuntimeError("redis unavailable")

            def get(self, repo: str, issue_number: int) -> None:
                return None

            def upsert(self, repo, state) -> None:
                raise AssertionError("unexpected write")

        with patch("builtins.print") as print_:
            _log_tracking_summary(config, FailingRepoStore())

        print_.assert_called_once_with(
            "tracking unknown repo(s) base_branch=main fallback_branch=main"
        )

    def test_main_uses_local_store_without_redis_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch.dict(
                    "os.environ", {"DISPATCHER_REPO": "owner/target-repo"}, clear=True
                ),
                patch(
                    "dispatcher.config.lookup_branch",
                    return_value=BranchLookup.PRESENT,
                ),
                patch("dispatcher.config.checkout_exists", return_value=True),
                patch("dispatcher.cli.StateStore") as state_store,
                patch("dispatcher.cli.run_once", return_value=False),
            ):
                result = main(["--once"])

            self.assertEqual(result, 0)
            self.assertEqual(state_store.call_count, 1)

    def test_run_once_skips_empty_redis_repo_list(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = make_config(root, repo=None)

        class EmptyRedisStore:
            def get_repos(self) -> list[str]:
                return []

            def get(self, repo: str, issue_number: int) -> None:
                return None

            def upsert(self, repo, state) -> None:
                raise AssertionError("unexpected write")

        with patch("dispatcher.cli.list_triggered_issues") as list_issues:
            result = legacy_main.run_once(config, EmptyRedisStore())

        self.assertFalse(result)
        list_issues.assert_not_called()
