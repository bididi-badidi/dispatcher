from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class DispatcherTests(unittest.TestCase):
    def make_config(self, root: Path, *, dry_run: bool = True) -> main.Config:
        return main.Config(
            repo="example/repo",
            label="automate",
            base_branch="main",
            branch_prefix="feat/issue-",
            paths=main.Paths(
                project_dir=root,
                worktree_root=root.parent,
                state_file=root / ".dispatcher" / "state.json",
                log_dir=root / ".dispatcher" / "logs",
            ),
            commands=main.Commands(
                worktree="worktree $issue_number $worktree $branch",
                plan="plan $issue_number $worktree",
                build="build $issue_number $branch",
            ),
            dry_run=dry_run,
        )

    def test_slugify_keeps_filesystem_friendly_text(self) -> None:
        self.assertEqual(
            main.slugify(" Add: local dispatcher! "), "add-local-dispatcher"
        )
        self.assertEqual(main.slugify("!!!"), "issue")

    def test_first_unstarted_issue_skips_known_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = main.StateStore(root / "state.json")
            store.upsert(
                main.IssueState(
                    number=1,
                    title="Started",
                    url="https://example.test/1",
                    status="started",
                    branch="feat/issue-1",
                    worktree="/tmp/one",
                    updated_at=main.utc_now(),
                )
            )
            issue = main.first_unstarted_issue(
                [
                    main.Issue(1, "Started", "https://example.test/1"),
                    main.Issue(2, "New", "https://example.test/2"),
                ],
                store,
            )
            self.assertIsNotNone(issue)
            self.assertEqual(issue.number, 2)

    def test_dry_run_pipeline_records_state_and_stage_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "dispatcher"
            root.mkdir()
            config = self.make_config(root)
            store = main.StateStore(config.paths.state_file)
            issue = main.Issue(7, "Build the thing", "https://example.test/7")

            state = main.run_pipeline(issue, config, store)

            self.assertEqual(state.status, "built")
            saved = json.loads(config.paths.state_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["issues"]["7"]["branch"], "feat/issue-7")
            self.assertIn(
                "dispatcher-7-build-the-thing", saved["issues"]["7"]["worktree"]
            )
            self.assertTrue((config.paths.log_dir / "issue-7-worktree.log").exists())
            self.assertTrue((config.paths.log_dir / "issue-7-plan.log").exists())
            self.assertTrue((config.paths.log_dir / "issue-7-build.log").exists())

    def test_list_triggered_issues_uses_gh_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            with patch("main.run_json") as run_json:
                run_json.return_value = [
                    {"number": 3, "title": "Ship it", "url": "https://example.test/3"}
                ]

                issues = main.list_triggered_issues(config)

            self.assertEqual(
                issues, [main.Issue(3, "Ship it", "https://example.test/3")]
            )
            command = run_json.call_args.args[0]
            self.assertIn("--label", command)
            self.assertIn("automate", command)


if __name__ == "__main__":
    unittest.main()
