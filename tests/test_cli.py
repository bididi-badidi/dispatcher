from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as legacy_main
from dispatcher.cli import _run_daemon, main, run_polling_loop
from dispatcher.state import StateStore
from tests.helpers import make_config


class CliTests(unittest.TestCase):
    def test_main_runs_daemon_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with (
                patch("pathlib.Path.cwd", return_value=dispatcher_dir),
                patch("dispatcher.cli._run_daemon", return_value=0) as run_daemon,
            ):
                result = main(["--repo", "owner/target-repo", "--daemon"])

            self.assertEqual(result, 0)
            self.assertEqual(run_daemon.call_count, 1)
            self.assertIs(legacy_main.main, main)

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
                with self.assertRaises(KeyboardInterrupt):
                    run_polling_loop(
                        config,
                        store,
                        sleep=lambda seconds: (_ for _ in ()).throw(
                            KeyboardInterrupt()
                        ),
                    )

            run_once.assert_called_once_with(config, store)

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
                with self.assertRaises(KeyboardInterrupt):
                    run_polling_loop(config, store, sleep=sleep)

            self.assertEqual(calls, [120.0])
