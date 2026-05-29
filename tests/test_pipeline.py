from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dispatcher.models import Config, Issue, IssueState, Paths
from dispatcher.pipeline import first_unstarted_issue, run_pipeline
from dispatcher.state import StateStore
from dispatcher.time_utils import utc_now
from tests.helpers import make_config


class PipelineTests(unittest.TestCase):
    def test_first_unstarted_issue_skips_known_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json")
            store.upsert(
                "example/repo",
                IssueState(
                    number=1,
                    title="Started",
                    url="https://example.test/1",
                    status="started",
                    branch="feat/issue-1",
                    worktree="/tmp/one",
                    updated_at=utc_now(),
                ),
            )

            issue = first_unstarted_issue(
                [
                    Issue(1, "Started", "https://example.test/1"),
                    Issue(2, "New", "https://example.test/2"),
                ],
                "example/repo",
                store,
            )

            self.assertIsNotNone(issue)
            self.assertEqual(issue.number, 2)

    def test_first_unstarted_issue_scopes_issue_numbers_to_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(root / "state.json")
            store.upsert(
                "example/one",
                IssueState(
                    number=1,
                    title="Started",
                    url="https://example.test/one/1",
                    status="started",
                    branch="feat/issue-1",
                    worktree="/tmp/one",
                    updated_at=utc_now(),
                ),
            )

            issue = first_unstarted_issue(
                [Issue(1, "Same number", "https://example.test/two/1")],
                "example/two",
                store,
            )

            self.assertIsNotNone(issue)
            self.assertEqual(issue.number, 1)
            store.upsert(
                "example/two",
                IssueState(
                    number=1,
                    title=issue.title,
                    url=issue.url,
                    status="started",
                    branch="feat/issue-1",
                    worktree="/tmp/two",
                    updated_at=utc_now(),
                ),
            )
            self.assertEqual(store.get("example/one", 1)["worktree"], "/tmp/one")
            self.assertEqual(store.get("example/two", 1)["worktree"], "/tmp/two")

    def test_reports_missing_expected_worktree_after_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root, dry_run=False)
            store = StateStore(config.paths.state_file)

            with patch("dispatcher.pipeline.run_stage") as run_stage:
                with self.assertRaisesRegex(
                    RuntimeError, "without creating the expected worktree directory"
                ):
                    run_pipeline(
                        Issue(1, "Missing worktree", "https://example.test/1"),
                        config,
                        store,
                    )

            self.assertEqual(run_stage.call_count, 1)

    def test_dry_run_records_state_and_stage_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            main_checkout = repo_root / "main"
            main_checkout.mkdir(parents=True)
            config = make_config(main_checkout)
            config = Config(
                repo=config.repo,
                label=config.label,
                opus_label=config.opus_label,
                opus_model=config.opus_model,
                base_branch=config.base_branch,
                branch_prefix=config.branch_prefix,
                paths=Paths(
                    project_dir=main_checkout,
                    worktree_root=repo_root,
                    state_file=config.paths.state_file,
                    log_dir=config.paths.log_dir,
                ),
                commands=config.commands,
                dry_run=config.dry_run,
            )
            store = StateStore(config.paths.state_file)
            issue = Issue(7, "Build the thing", "https://example.test/7")

            state = run_pipeline(issue, config, store)

            self.assertEqual(state.status, "built")
            saved = json.loads(config.paths.state_file.read_text(encoding="utf-8"))
            saved_issue = saved["repositories"]["example/repo"]["issues"]["7"]
            self.assertEqual(saved_issue["branch"], "feat/issue-7")
            self.assertEqual(
                saved_issue["worktree"],
                str(repo_root / "feat" / "issue-7"),
            )
            repo_log_dir = config.paths.log_dir / "example" / "repo"
            self.assertTrue((repo_log_dir / "issue-7-worktree.log").exists())
            self.assertTrue((repo_log_dir / "issue-7-plan.log").exists())
            self.assertTrue((repo_log_dir / "issue-7-build.log").exists())

    def test_records_pr_url_from_build_stage_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            main_checkout = repo_root / "main"
            main_checkout.mkdir(parents=True)
            config = make_config(main_checkout, dry_run=False)
            config = Config(
                repo=config.repo,
                label=config.label,
                opus_label=config.opus_label,
                opus_model=config.opus_model,
                base_branch=config.base_branch,
                branch_prefix=config.branch_prefix,
                paths=Paths(
                    project_dir=main_checkout,
                    worktree_root=repo_root,
                    state_file=config.paths.state_file,
                    log_dir=config.paths.log_dir,
                ),
                commands=config.commands,
                dry_run=config.dry_run,
            )
            store = StateStore(config.paths.state_file)
            issue = Issue(12, "Open a PR", "https://example.test/12")
            worktree = repo_root / "feat" / "issue-12"
            worktree.mkdir(parents=True)

            with patch("dispatcher.pipeline.run_stage") as run_stage:
                with patch(
                    "dispatcher.pipeline.initial_review_cursor", return_value=(77, 0, 0)
                ) as cursor:
                    run_stage.side_effect = [
                        "",
                        "",
                        "Done: https://github.com/example/repo/pull/12",
                    ]

                    state = run_pipeline(issue, config, store)

            cursor.assert_called_once_with(config, "example/repo", "12")
            self.assertEqual(state.status, "pr_opened")
            self.assertEqual(state.pr_url, "https://github.com/example/repo/pull/12")
            self.assertEqual(state.pr_review_cursor, 77)
            saved_issue = store.get("example/repo", 12)
            self.assertEqual(saved_issue["status"], "pr_opened")
            self.assertEqual(
                saved_issue["pr_url"], "https://github.com/example/repo/pull/12"
            )
            self.assertEqual(saved_issue["pr_review_cursor"], 77)

    def test_build_stage_must_emit_pr_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            main_checkout = repo_root / "main"
            main_checkout.mkdir(parents=True)
            config = make_config(main_checkout, dry_run=False)
            config = Config(
                repo=config.repo,
                label=config.label,
                opus_label=config.opus_label,
                opus_model=config.opus_model,
                base_branch=config.base_branch,
                branch_prefix=config.branch_prefix,
                paths=Paths(
                    project_dir=main_checkout,
                    worktree_root=repo_root,
                    state_file=config.paths.state_file,
                    log_dir=config.paths.log_dir,
                ),
                commands=config.commands,
                dry_run=config.dry_run,
            )
            store = StateStore(config.paths.state_file)
            issue = Issue(13, "Missing PR URL", "https://example.test/13")
            worktree = repo_root / "feat" / "issue-13"
            worktree.mkdir(parents=True)

            with patch("dispatcher.pipeline.run_stage") as run_stage:
                run_stage.side_effect = ["", "", "build finished"]

                with self.assertRaisesRegex(RuntimeError, "did not print"):
                    run_pipeline(issue, config, store)

            saved_issue = store.get("example/repo", 13)
            self.assertEqual(saved_issue["status"], "failed")
            self.assertIn("did not print", saved_issue["error"])
