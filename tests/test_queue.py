from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from dispatcher.models import Issue, IssueState
from dispatcher.queue import Dispatcher, Task, TaskType
from dispatcher.state import StateStore
from dispatcher.time_utils import utc_now
from tests.helpers import make_config


class QueueTests(unittest.TestCase):
    def test_enqueues_unseen_issues_once(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                store.upsert(
                    "example/repo",
                    IssueState(
                        number=1,
                        title="Known",
                        url="https://example.test/1",
                        status="built",
                        branch="feat/issue-1",
                        worktree="/tmp/one",
                        updated_at=utc_now(),
                    ),
                )
                dispatcher = Dispatcher(config, store, max_workers=2)

                with patch("dispatcher.queue.list_triggered_issues") as list_issues:
                    list_issues.return_value = [
                        Issue(1, "Known", "https://example.test/1"),
                        Issue(2, "New", "https://example.test/2"),
                        Issue(2, "New", "https://example.test/2"),
                    ]
                    await dispatcher._enqueue_triggered_issues(config.repo)

                snapshot = dispatcher.snapshot()
                self.assertEqual(
                    [task.issue.number for task in snapshot.pending],
                    [2],
                )
                self.assertEqual(snapshot.active, {0: None, 1: None})
                self.assertFalse(
                    dispatcher.enqueue_review(Issue(2, "New", "https://example.test/2"))
                )

        asyncio.run(scenario())

    def test_review_enqueue_allows_completed_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "example/repo",
                IssueState(
                    number=4,
                    title="Needs review fix",
                    url="https://example.test/4",
                    status="built",
                    branch="feat/issue-4",
                    worktree="/tmp/four",
                    updated_at=utc_now(),
                ),
            )
            dispatcher = Dispatcher(config, store, max_workers=1)

            accepted = dispatcher.enqueue_review(
                Issue(4, "Needs review fix", "https://example.test/4")
            )

            self.assertTrue(accepted)
            snapshot = dispatcher.snapshot()
            self.assertEqual(snapshot.pending[0].task_type, TaskType.REVIEW)

    def test_enqueue_stops_when_shutdown_requested_with_full_queue(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                dispatcher = Dispatcher(config, store, max_workers=1)
                dispatcher._QUEUE_PUT_TIMEOUT_SECONDS = 0.01

                for issue_number in range(20):
                    dispatcher._queue.put_nowait(
                        Task(
                            config.repo,
                            Issue(
                                issue_number,
                                f"Queued {issue_number}",
                                f"https://example.test/{issue_number}",
                            ),
                        )
                    )

                with patch("dispatcher.queue.list_triggered_issues") as list_issues:
                    list_issues.return_value = [
                        Issue(99, "Blocked", "https://example.test/99")
                    ]
                    enqueue = asyncio.create_task(
                        dispatcher._enqueue_triggered_issues(config.repo)
                    )
                    await asyncio.sleep(0.02)
                    dispatcher.request_shutdown()
                    result = await asyncio.wait_for(enqueue, timeout=1)

                self.assertIsNone(result)
                self.assertNotIn((config.repo, 99), dispatcher._in_flight)

        asyncio.run(scenario())

    def test_get_repos_uses_redis_store_repo_list(self) -> None:
        class RedisLikeStore:
            def get_repos(self) -> list[str]:
                return ["example/one", "example/two"]

            def get(self, repo: str, issue_number: int) -> None:
                return None

            def upsert(self, repo, state) -> None:
                raise AssertionError("unexpected write")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(Path(temp_dir), repo=None)
            dispatcher = Dispatcher(config, RedisLikeStore(), max_workers=1)

            self.assertEqual(dispatcher._get_repos(), ["example/one", "example/two"])

    def test_worker_failure_logs_without_stdout(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                dispatcher = Dispatcher(config, store, max_workers=1)
                stdout = io.StringIO()

                async def fail_pipeline(*args, **kwargs):
                    raise RuntimeError("pipeline exploded")

                with (
                    patch(
                        "dispatcher.queue.async_run_langgraph_pipeline",
                        side_effect=fail_pipeline,
                    ),
                    self.assertLogs("dispatcher.queue", level="ERROR") as logs,
                    redirect_stdout(stdout),
                ):
                    worker = asyncio.create_task(dispatcher._worker(0))
                    await dispatcher._queue.put(
                        Task(
                            config.repo,
                            Issue(42, "Broken", "https://example.test/42"),
                        )
                    )
                    await dispatcher._queue.put(None)
                    await asyncio.wait_for(worker, timeout=1)

                self.assertEqual(stdout.getvalue(), "")
                self.assertTrue(logs.records)
                self.assertIn("Worker 0 failed issue #42", logs.output[0])
                self.assertEqual(dispatcher.snapshot().failed_count, 1)

        asyncio.run(scenario())


def test_worker_failure_keeps_stdout_silent(capsys) -> None:
    async def scenario() -> Dispatcher:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            dispatcher = Dispatcher(config, store, max_workers=1)

            async def fail_pipeline(*args, **kwargs):
                raise RuntimeError("pipeline exploded")

            with (
                patch(
                    "dispatcher.queue.async_run_langgraph_pipeline",
                    side_effect=fail_pipeline,
                ),
                patch("dispatcher.queue.LOGGER.exception") as log_exception,
            ):
                worker = asyncio.create_task(dispatcher._worker(0))
                await dispatcher._queue.put(
                    Task(
                        config.repo,
                        Issue(42, "Broken", "https://example.test/42"),
                    )
                )
                await dispatcher._queue.put(None)
                await asyncio.wait_for(worker, timeout=1)

            log_exception.assert_called_once()
            return dispatcher

    dispatcher = asyncio.run(scenario())
    out, _ = capsys.readouterr()
    assert out == ""
    assert dispatcher.snapshot().failed_count == 1
