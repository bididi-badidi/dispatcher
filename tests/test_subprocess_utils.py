from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.subprocess_utils import print_subprocess_command, run_json


class SubprocessUtilsTests(unittest.TestCase):
    def test_print_subprocess_command_silent_when_debug_false(self) -> None:
        with patch("builtins.print") as print_:
            print_subprocess_command(["gh", "issue", "list"], debug=False)

        print_.assert_not_called()

    def test_print_subprocess_command_verbose_when_debug_true(self) -> None:
        with patch("builtins.print") as print_:
            print_subprocess_command(["gh", "issue", "list"], debug=True)

        print_.assert_called_once_with("$ gh issue list")

    def test_run_json_is_silent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="[]", stderr=""
            )

            with (
                patch("builtins.print") as print_,
                patch(
                    "dispatcher.subprocess_utils.subprocess.run", return_value=completed
                ),
            ):
                payload = run_json(["gh", "issue", "list", "open items"], root)

            self.assertEqual(payload, [])
            print_.assert_not_called()

    def test_run_json_prints_cli_command_when_debug_true(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="[]", stderr=""
            )

            with (
                patch("builtins.print") as print_,
                patch(
                    "dispatcher.subprocess_utils.subprocess.run", return_value=completed
                ),
            ):
                payload = run_json(
                    ["gh", "issue", "list", "open items"], root, debug=True
                )

            self.assertEqual(payload, [])
            print_.assert_called_once_with("$ gh issue list 'open items'")
