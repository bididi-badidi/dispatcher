from __future__ import annotations

import asyncio
import tempfile
import unittest
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
                    await dispatcher._enqueue_triggered_issues()

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
                        dispatcher._enqueue_triggered_issues()
                    )
                    await asyncio.sleep(0.02)
                    dispatcher.request_shutdown()
                    result = await asyncio.wait_for(enqueue, timeout=1)

                self.assertIsNone(result)
                self.assertNotIn(99, dispatcher._in_flight)

        asyncio.run(scenario())
