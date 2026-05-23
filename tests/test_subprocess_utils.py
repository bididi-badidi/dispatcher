from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.subprocess_utils import run_json


class SubprocessUtilsTests(unittest.TestCase):
    def test_run_json_prints_cli_command_to_stdout(self) -> None:
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
            print_.assert_called_once_with("$ gh issue list 'open items'")
