from __future__ import annotations

from dataclasses import replace
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
                    {
                        "number": 3,
                        "title": "Ship it",
                        "url": "https://example.test/3",
                        "labels": [{"name": "automate"}],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(issues, [Issue(3, "Ship it", "https://example.test/3")])
            command = run_json.call_args.args[0]
            self.assertIn("--label", command)
            self.assertIn("automate", command)
            self.assertIn("owner/repo", command)
            self.assertIn("number,title,url,labels", command)

    def test_list_triggered_issues_sets_plan_model_for_opus_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 4,
                        "title": "Plan with Opus",
                        "url": "https://example.test/4",
                        "labels": [
                            {"name": "automate"},
                            {"name": "automate:opus"},
                        ],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(
                issues,
                [
                    Issue(
                        4,
                        "Plan with Opus",
                        "https://example.test/4",
                        plan_model="claude-opus-4-7",
                    )
                ],
            )

    def test_list_triggered_issues_requires_trigger_label_for_plan_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 5,
                        "title": "Missing trigger",
                        "url": "https://example.test/5",
                        "labels": [{"name": "automate:opus"}],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertIsNone(issues[0].plan_model)

    def test_list_triggered_issues_supports_custom_opus_label_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                make_config(root),
                opus_label="needs-opus",
                opus_model="claude-opus-4-5",
            )
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 6,
                        "title": "Custom escalation",
                        "url": "https://example.test/6",
                        "labels": [
                            {"name": "automate"},
                            {"name": "needs-opus"},
                        ],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(issues[0].plan_model, "claude-opus-4-5")
