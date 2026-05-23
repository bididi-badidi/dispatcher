from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.async_pipeline import async_run_pipeline
from dispatcher.models import Config, Issue, Paths
from dispatcher.queue import Task, TaskType
from dispatcher.runners import AgentRunner
from dispatcher.state import StateStore
from tests.helpers import make_config


class AsyncPipelineTests(unittest.TestCase):
    def test_dry_run_records_state_and_logs(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                repo_root = Path(temp_dir) / "repo"
                main_checkout = repo_root / "main"
                main_checkout.mkdir(parents=True)
                config = make_config(main_checkout)
                config = Config(
                    repo=config.repo,
                    label=config.label,
                    base_branch=config.base_branch,
                    branch_prefix=config.branch_prefix,
                    paths=Paths(
                        project_dir=main_checkout,
                        worktree_root=repo_root,
                        state_file=config.paths.state_file,
                        log_dir=config.paths.log_dir,
                    ),
                    commands=config.commands,
                    dry_run=True,
                )
                store = StateStore(config.paths.state_file)
                issue = Issue(9, "Async build", "https://example.test/9")
                task = Task(config.repo, issue)

                with patch.object(AgentRunner, "version", return_value="test"):
                    state = await async_run_pipeline(
                        task, config, store, 1, asyncio.Event()
                    )

                self.assertEqual(state.status, "built")
                self.assertEqual(state.task_type, "fresh")
                self.assertIsNone(state.worker_id)
                saved_issue = store.get("example/repo", 9)
                self.assertIsNotNone(saved_issue)
                self.assertEqual(saved_issue["status"], "built")
                self.assertEqual(saved_issue["worker_id"], None)
                repo_log_dir = config.paths.log_dir / "example" / "repo"
                self.assertTrue((repo_log_dir / "issue-9-worktree.log").exists())
                self.assertTrue((repo_log_dir / "issue-9-plan.log").exists())
                self.assertTrue((repo_log_dir / "issue-9-build.log").exists())

        asyncio.run(scenario())

    def test_review_requires_existing_worktree(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root, dry_run=False)
                store = StateStore(config.paths.state_file)
                issue = Issue(10, "Review fix", "https://example.test/10")
                task = Task(config.repo, issue, TaskType.REVIEW)

                with patch("dispatcher.async_pipeline.async_run_stage") as run_stage:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "without creating the expected worktree directory",
                    ):
                        await async_run_pipeline(
                            task, config, store, 0, asyncio.Event()
                        )

                run_stage.assert_not_called()
                saved_issue = store.get("example/repo", 10)
                self.assertIsNotNone(saved_issue)
                self.assertEqual(saved_issue["status"], "failed")
                self.assertEqual(saved_issue["task_type"], "review")

        asyncio.run(scenario())
