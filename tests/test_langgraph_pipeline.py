from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.langgraph_pipeline import async_run_langgraph_pipeline
from dispatcher.models import Issue
from dispatcher.queue import Task
from dispatcher.state import StateStore
from tests.helpers import make_config


class LangGraphPipelineTests(unittest.TestCase):
    def test_happy_path_opens_pr_after_parallel_reviews(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(3, "Graph workflow", "https://example.test/3")
                review_started: dict[str, float] = {}

                async def run_stage(name, runner, issue, config, worktree, branch):
                    if name == "plan":
                        plan_path = (
                            worktree
                            / ".ai"
                            / "assets"
                            / "branches"
                            / branch
                            / "plan.md"
                        )
                        plan_path.parent.mkdir(parents=True, exist_ok=True)
                        plan_path.write_text("plan", encoding="utf-8")
                    if name in {"review_plan", "review_quality"}:
                        review_started[name] = time.monotonic()
                        await asyncio.sleep(0.05)
                        return "VERDICT: approved\n"
                    if name == "open_pr":
                        return "https://github.com/example/repo/pull/12"
                    return ""

                with patch(
                    "dispatcher.langgraph_pipeline.async_run_stage",
                    side_effect=run_stage,
                ):
                    state = await async_run_langgraph_pipeline(
                        Task(config.repo, issue), config, store, 1, asyncio.Event()
                    )

                self.assertEqual(state.status, "pr_opened")
                self.assertEqual(state.build_iteration, 1)
                self.assertEqual(
                    state.pr_url, "https://github.com/example/repo/pull/12"
                )
                self.assertLess(
                    abs(
                        review_started["review_plan"] - review_started["review_quality"]
                    ),
                    0.2,
                )
                saved = store.get(config.repo, 3)
                self.assertEqual(saved["status"], "pr_opened")
                self.assertEqual(saved["plan_review"], "approved")
                self.assertEqual(saved["quality_review"], "approved")

        asyncio.run(scenario())

    def test_emits_workflow_start_and_completion_logs(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(31, "Logged workflow", "https://example.test/31")

                async def run_stage(name, runner, issue, config, worktree, branch):
                    if name == "plan":
                        plan_path = (
                            worktree
                            / ".ai"
                            / "assets"
                            / "branches"
                            / branch
                            / "plan.md"
                        )
                        plan_path.parent.mkdir(parents=True, exist_ok=True)
                        plan_path.write_text("plan", encoding="utf-8")
                    if name in {"review_plan", "review_quality"}:
                        return "VERDICT: approved\n"
                    if name == "open_pr":
                        return "https://github.com/example/repo/pull/31"
                    return ""

                with (
                    patch(
                        "dispatcher.langgraph_pipeline.async_run_stage",
                        side_effect=run_stage,
                    ),
                    self.assertLogs("dispatcher", level="INFO") as logs,
                ):
                    await async_run_langgraph_pipeline(
                        Task(config.repo, issue), config, store, 7, asyncio.Event()
                    )

            output = "\n".join(logs.output)
            self.assertIn("[DISPATCHER] Processing issue #31 in example/repo", output)
            self.assertIn(
                "[DISPATCHER] Completed #31 in example/repo status=pr_opened",
                output,
            )
            complete_record = logs.records[-1]
            self.assertEqual(complete_record.state["status"], "pr_opened")
            self.assertEqual(
                complete_record.state["worktree"], str(root.parent / "feat/issue-31")
            )

        asyncio.run(scenario())

    def test_emits_failure_log_with_state(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(32, "Failed workflow", "https://example.test/32")

                async def run_stage(name, runner, issue, config, worktree, branch):
                    if name == "build":
                        raise RuntimeError("build exploded")
                    return ""

                with (
                    patch(
                        "dispatcher.langgraph_pipeline.async_run_stage",
                        side_effect=run_stage,
                    ),
                    self.assertLogs("dispatcher", level="ERROR") as logs,
                ):
                    with self.assertRaisesRegex(RuntimeError, "build exploded"):
                        await async_run_langgraph_pipeline(
                            Task(config.repo, issue),
                            config,
                            store,
                            4,
                            asyncio.Event(),
                        )

            output = "\n".join(logs.output)
            self.assertIn("[DISPATCHER] Failed #32 in example/repo", output)
            self.assertIn("build exploded", output)
            self.assertEqual(logs.records[-1].state["status"], "failed")
            self.assertEqual(logs.records[-1].state["error"], "build exploded")

        asyncio.run(scenario())

    def test_retries_build_when_review_requests_changes(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(4, "Retry workflow", "https://example.test/4")
                calls: list[str] = []

                async def run_stage(name, runner, issue, config, worktree, branch):
                    calls.append(name)
                    if name == "review_plan" and calls.count("review_plan") == 1:
                        return "VERDICT: changes_requested\nMatch the plan."
                    if name in {"review_plan", "review_quality"}:
                        return "VERDICT: approved\n"
                    if name == "open_pr":
                        return "https://github.com/example/repo/pull/13"
                    return ""

                with patch(
                    "dispatcher.langgraph_pipeline.async_run_stage",
                    side_effect=run_stage,
                ):
                    state = await async_run_langgraph_pipeline(
                        Task(config.repo, issue), config, store, 2, asyncio.Event()
                    )

                self.assertEqual(state.status, "pr_opened")
                self.assertEqual(state.build_iteration, 2)
                self.assertEqual(calls.count("build"), 2)
                self.assertEqual(calls.count("open_pr"), 1)

        asyncio.run(scenario())

    def test_marks_failed_after_max_iterations(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(5, "Exhaust workflow", "https://example.test/5")
                calls: list[str] = []

                async def run_stage(name, runner, issue, config, worktree, branch):
                    calls.append(name)
                    if name == "review_plan":
                        return "VERDICT: approved\n"
                    if name == "review_quality":
                        return "VERDICT: changes_requested\nAdd tests."
                    return ""

                old_value = os.environ.get("DISPATCHER_MAX_ITERATIONS")
                os.environ["DISPATCHER_MAX_ITERATIONS"] = "2"
                try:
                    with patch(
                        "dispatcher.langgraph_pipeline.async_run_stage",
                        side_effect=run_stage,
                    ):
                        state = await async_run_langgraph_pipeline(
                            Task(config.repo, issue), config, store, 0, asyncio.Event()
                        )
                finally:
                    if old_value is None:
                        os.environ.pop("DISPATCHER_MAX_ITERATIONS", None)
                    else:
                        os.environ["DISPATCHER_MAX_ITERATIONS"] = old_value

                self.assertEqual(state.status, "failed")
                self.assertEqual(state.build_iteration, 2)
                self.assertIn("review changes requested", state.error or "")
                self.assertNotIn("open_pr", calls)

        asyncio.run(scenario())

    def test_shutdown_mid_graph_marks_issue_failed(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                issue = Issue(6, "Shutdown workflow", "https://example.test/6")
                shutdown_event = asyncio.Event()

                async def run_stage(name, runner, issue, config, worktree, branch):
                    if name == "plan":
                        shutdown_event.set()
                    return ""

                with patch(
                    "dispatcher.langgraph_pipeline.async_run_stage",
                    side_effect=run_stage,
                ):
                    with self.assertRaisesRegex(RuntimeError, "shutdown requested"):
                        await async_run_langgraph_pipeline(
                            Task(config.repo, issue),
                            config,
                            store,
                            0,
                            shutdown_event,
                        )

                saved = store.get(config.repo, 6)
                self.assertEqual(saved["status"], "failed")
                self.assertEqual(saved["error"], "shutdown requested")

        asyncio.run(scenario())
