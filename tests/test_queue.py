from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.models import Issue, IssueState
from dispatcher.github import TerminalPr
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

    def test_enqueue_task_logs_queued_event(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                dispatcher = Dispatcher(config, store, max_workers=1)

                issue = Issue(99, "Log me", "https://example.test/99")
                task = Task(config.repo, issue)

                with patch("dispatcher.queue.LOGGER.info") as mock_info:
                    accepted = await dispatcher._enqueue_task(task)

                self.assertTrue(accepted)
                printed = " ".join(str(c) for c in mock_info.call_args_list)
                self.assertIn("[INFO] task queued", printed)
                self.assertIn("issue=99", printed)
                self.assertIn("type=fresh", printed)

        asyncio.run(scenario())

    def test_enqueue_review_logs_queued_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            dispatcher = Dispatcher(config, store, max_workers=1)

            issue = Issue(42, "Review me", "https://example.test/42")

            with patch("dispatcher.queue.LOGGER.info") as mock_info:
                accepted = dispatcher.enqueue_review(issue)

            self.assertTrue(accepted)
            printed = " ".join(str(c) for c in mock_info.call_args_list)
            self.assertIn("[INFO] task queued", printed)
            self.assertIn("issue=42", printed)
            self.assertIn("type=review", printed)

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

    def test_enqueue_review_responses_updates_state_and_queues_review(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                store.upsert(
                    "example/repo",
                    IssueState(
                        number=10,
                        title="Review fix",
                        url="https://example.test/10",
                        status="pr_opened",
                        branch="feat/issue-10",
                        worktree="/tmp/ten",
                        updated_at=utc_now(),
                        pr_url="https://github.com/example/repo/pull/10",
                    ),
                )
                dispatcher = Dispatcher(config, store, max_workers=1)

                with patch(
                    "dispatcher.queue.list_prs_needing_review_response"
                ) as list_pending:
                    list_pending.return_value = [
                        (
                            Issue(10, "Review fix", "https://example.test/10"),
                            "Please update this.",
                            (123, 45, 67),
                        )
                    ]

                    await dispatcher._enqueue_review_responses(config.repo)

                saved = store.get(config.repo, 10)
                self.assertEqual(saved["status"], "pr_review_queued")
                self.assertEqual(saved["build_feedback"], "Please update this.")
                self.assertEqual(saved["pr_review_cursor"], 123)
                self.assertEqual(saved["pr_issue_comment_cursor"], 45)
                self.assertEqual(saved["pr_review_comment_cursor"], 67)
                snapshot = dispatcher.snapshot()
                self.assertEqual(snapshot.pending[0].task_type, TaskType.REVIEW)

        asyncio.run(scenario())

    def test_enqueue_review_responses_resets_build_iteration(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                store.upsert(
                    "example/repo",
                    IssueState(
                        number=20,
                        title="Retry after failure",
                        url="https://example.test/20",
                        status="failed",
                        branch="feat/issue-20",
                        worktree="/tmp/twenty",
                        updated_at=utc_now(),
                        pr_url="https://github.com/example/repo/pull/20",
                        build_iteration=3,
                    ),
                )
                dispatcher = Dispatcher(config, store, max_workers=1)

                with patch(
                    "dispatcher.queue.list_prs_needing_review_response"
                ) as list_pending:
                    list_pending.return_value = [
                        (
                            Issue(20, "Retry after failure", "https://example.test/20"),
                            "Try again.",
                            (0, 200, 0),
                        )
                    ]

                    await dispatcher._enqueue_review_responses(config.repo)

                saved = store.get(config.repo, 20)
                self.assertEqual(saved["status"], "pr_review_queued")
                self.assertEqual(saved["build_iteration"], 0)

        asyncio.run(scenario())

    def test_cleanup_merged_issues_marks_cleaned_up(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                store.upsert(
                    "example/repo",
                    IssueState(
                        number=11,
                        title="Merged",
                        url="https://example.test/11",
                        status="pr_opened",
                        branch="feat/issue-11",
                        worktree="/tmp/eleven",
                        updated_at=utc_now(),
                        pr_url="https://github.com/example/repo/pull/11",
                    ),
                )
                dispatcher = Dispatcher(config, store, max_workers=1)

                with (
                    patch("dispatcher.queue.list_terminal_prs") as list_terminal,
                    patch("dispatcher.queue.cleanup_merged_branch") as cleanup,
                ):
                    list_terminal.return_value = [
                        TerminalPr(
                            Issue(11, "Merged", "https://example.test/11"),
                            "merged",
                        )
                    ]

                    await dispatcher._cleanup_merged_issues(config.repo)

                saved = store.get(config.repo, 11)
                self.assertEqual(saved["status"], "cleaned_up")
                cleanup.assert_called_once()

        asyncio.run(scenario())

    def test_cleanup_closed_pr_marks_closed_then_cleaned_up(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                config = make_config(root)
                store = StateStore(config.paths.state_file)
                store.upsert(
                    "example/repo",
                    IssueState(
                        number=12,
                        title="Closed",
                        url="https://example.test/12",
                        status="pr_opened",
                        branch="feat/issue-12",
                        worktree="/tmp/twelve",
                        updated_at=utc_now(),
                        pr_url="https://github.com/example/repo/pull/12",
                    ),
                )
                dispatcher = Dispatcher(config, store, max_workers=1)

                with (
                    patch("dispatcher.queue.list_terminal_prs") as list_terminal,
                    patch("dispatcher.queue.cleanup_merged_branch") as cleanup,
                ):
                    list_terminal.return_value = [
                        TerminalPr(
                            Issue(12, "Closed", "https://example.test/12"),
                            "closed",
                        )
                    ]

                    await dispatcher._cleanup_merged_issues(config.repo)

                saved = store.get(config.repo, 12)
                self.assertEqual(saved["status"], "cleaned_up")
                cleanup.assert_called_once()

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
