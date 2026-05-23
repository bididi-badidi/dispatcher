from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.github import list_triggered_issues
from dispatcher.models import Issue
from tests.helpers import make_config


class GitHubTests(unittest.TestCase):
    def test_list_triggered_issues_uses_gh_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {"number": 3, "title": "Ship it", "url": "https://example.test/3"}
                ]

                issues = list_triggered_issues(config)

            self.assertEqual(issues, [Issue(3, "Ship it", "https://example.test/3")])
            command = run_json.call_args.args[0]
            self.assertIn("--label", command)
            self.assertIn("automate", command)
