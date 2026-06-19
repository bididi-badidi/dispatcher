from __future__ import annotations

import asyncio
import enum
import logging
import signal
from dataclasses import dataclass
from pathlib import Path

from dispatcher.cleanup import cleanup_merged_branch
from dispatcher.github import (
    list_terminal_prs,
    list_prs_needing_review_response,
    list_triggered_issues,
)
from dispatcher.langgraph_pipeline import async_run_langgraph_pipeline
from dispatcher.models import Config, Issue, IssueState
from dispatcher.repo_context import config_for_repo
from dispatcher.state_backend import StateBackend
from dispatcher.time_utils import utc_now

LOGGER = logging.getLogger(__name__)


class TaskType(enum.Enum):
    FRESH = "fresh"
    REVIEW = "review"


@dataclass(frozen=True)
class Task:
    repo: str
    issue: Issue
    task_type: TaskType = TaskType.FRESH


@dataclass(frozen=True)
class QueueSnapshot:
    pending: tuple[Task, ...]
    active: dict[int, Task | None]
    completed_count: int
    failed_count: int


class Dispatcher:
    _QUEUE_PUT_TIMEOUT_SECONDS = 0.5

    def __init__(
        self, config: Config, store: StateBackend, max_workers: int | None = None
    ) -> None:
        self.config = config
        self.store = store
        self.max_workers = (
            max_workers if max_workers is not None else config.max_workers
        )
        if self.max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")

        self._queue: asyncio.Queue[Task | None] = asyncio.Queue(maxsize=20)
        self._shutdown = asyncio.Event()
        self._in_flight: set[tuple[str, int]] = set()
        self._active: dict[int, Task | None] = {
            worker_id: None for worker_id in range(self.max_workers)
        }
        self._completed_count = 0
        self._failed_count = 0

    async def run(self) -> None:
        self._install_signal_handlers()
        LOGGER.info(self._startup_message())
        poller = asyncio.create_task(self._poller())
        workers = [
            asyncio.create_task(self._worker(worker_id))
            for worker_id in range(self.max_workers)
        ]

        try:
            await self._shutdown.wait()
        finally:
            await poller
            for _ in workers:
                await self._queue.put(None)
            await asyncio.gather(*workers)

    async def _poller(self) -> None:
        while not self._shutdown.is_set():
            try:
                for repo in self._get_repos():
                    await self._enqueue_triggered_issues(repo)
                    await self._cleanup_merged_issues(repo)
                    await self._enqueue_review_responses(repo)
            except Exception as exc:
                LOGGER.exception("Polling cycle failed: %s", exc)

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.config.poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def _enqueue_triggered_issues(self, repo: str) -> None:
        repo_config = config_for_repo(self.config, repo)
        issues = await asyncio.to_thread(list_triggered_issues, repo_config, repo)
        for issue in issues:
            if self._should_skip_issue(repo, issue, skip_existing=True):
                continue
            task = Task(repo, issue)
            await self._enqueue_task(task)

    async def _enqueue_review_responses(self, repo: str) -> None:
        repo_config = config_for_repo(self.config, repo)
        pending = await asyncio.to_thread(
            list_prs_needing_review_response, repo_config, repo, self.store
        )
        for issue, feedback, new_cursors in pending:
            if (repo, issue.number) in self._in_flight:
                continue

            existing = self.store.get(repo, issue.number)
            if not existing:
                continue

            state = IssueState(**existing)
            state.pr_review_cursor = new_cursors[0]
            state.pr_issue_comment_cursor = new_cursors[1]
            state.pr_review_comment_cursor = new_cursors[2]
            state.status = "pr_review_queued"
            state.build_iteration = 0
            state.build_feedback = feedback
            state.updated_at = utc_now()
            self.store.upsert(repo, state)
            await self._enqueue_task(Task(repo, issue, TaskType.REVIEW))

    async def _cleanup_merged_issues(self, repo: str) -> None:
        repo_config = config_for_repo(self.config, repo)
        terminal_prs = await asyncio.to_thread(
            list_terminal_prs, repo_config, repo, self.store
        )
        for terminal_pr in terminal_prs:
            issue = terminal_pr.issue
            if (repo, issue.number) in self._in_flight:
                continue

            existing = self.store.get(repo, issue.number)
            if not existing:
                continue

            state = IssueState(**existing)
            state.status = terminal_pr.status
            state.updated_at = utc_now()
            self.store.upsert(repo, state)

            try:
                await asyncio.to_thread(
                    cleanup_merged_branch,
                    state.branch,
                    Path(state.worktree),
                    repo_config.paths.project_dir,
                )
                state.status = "cleaned_up"
            except Exception as exc:
                LOGGER.warning(
                    "cleanup failed for issue #%d: %s",
                    issue.number,
                    exc,
                )
            finally:
                state.updated_at = utc_now()
                self.store.upsert(repo, state)

    async def _worker(self, worker_id: int) -> None:
        while True:
            task = await self._queue.get()
            if task is None:
                self._queue.task_done()
                break

            self._active[worker_id] = task
            try:
                await async_run_langgraph_pipeline(
                    task,
                    config_for_repo(self.config, task.repo),
                    self.store,
                    worker_id,
                    self._shutdown,
                )
                self._completed_count += 1
            except Exception as exc:
                self._failed_count += 1
                LOGGER.exception(
                    "Worker %d failed issue #%d: %s",
                    worker_id,
                    task.issue.number,
                    exc,
                )
            finally:
                self._active[worker_id] = None
                self._in_flight.discard((task.repo, task.issue.number))
                self._queue.task_done()

    def enqueue_review(self, issue: Issue, repo: str | None = None) -> bool:
        task_repo = repo or self._require_single_repo()
        task = Task(task_repo, issue, TaskType.REVIEW)
        if self._should_skip_issue(task_repo, issue, skip_existing=False):
            return False

        self._mark_queued(task)
        try:
            self._queue.put_nowait(task)
        except asyncio.QueueFull:
            self._in_flight.discard((task.repo, task.issue.number))
            return False
        self._log_enqueued(task)
        return True

    def snapshot(self) -> QueueSnapshot:
        # Compatibility note: asyncio.Queue has no public API for enumerating
        # pending items. Snapshot is diagnostic/test-only, so keep the private
        # access isolated here instead of spreading Queue internals elsewhere.
        pending = tuple(
            task
            for task in list(self._queue._queue)  # type: ignore[attr-defined]
            if isinstance(task, Task)
        )
        return QueueSnapshot(
            pending=pending,
            active=dict(self._active),
            completed_count=self._completed_count,
            failed_count=self._failed_count,
        )

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def _should_skip_issue(
        self, repo: str, issue: Issue, *, skip_existing: bool
    ) -> bool:
        if (repo, issue.number) in self._in_flight:
            return True

        return skip_existing and self.store.get(repo, issue.number) is not None

    def _mark_queued(self, task: Task) -> None:
        self._in_flight.add((task.repo, task.issue.number))

    def _log_enqueued(self, task: Task) -> None:
        if not LOGGER.isEnabledFor(logging.INFO):
            return

        task_id = f"{task.repo}#{task.issue.number}:{task.task_type.value}"
        LOGGER.info(
            "task queued | id=%s repo=%s issue=%s type=%s queued_at=%s queue_depth=%d",
            task_id,
            task.repo,
            task.issue.number,
            task.task_type.value,
            utc_now(),
            self._queue.qsize(),
        )

    async def _enqueue_task(self, task: Task) -> bool:
        self._mark_queued(task)
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._queue.put(task),
                    timeout=self._QUEUE_PUT_TIMEOUT_SECONDS,
                )
                self._log_enqueued(task)
                return True
            except TimeoutError:
                pass

        self._in_flight.discard((task.repo, task.issue.number))
        return False

    def _get_repos(self) -> list[str]:
        if hasattr(self.store, "get_repos"):
            try:
                return list(self.store.get_repos())  # type: ignore[attr-defined]
            except Exception as exc:
                LOGGER.warning(
                    "redis unavailable, skipping repo refresh: %s",
                    exc,
                )
                return []
        if self.config.repo:
            return [self.config.repo]
        return []

    def _startup_message(self) -> str:
        return (
            f"Polling for label {self.config.label!r} every "
            f"{self.config.poll_interval_seconds:g} seconds with "
            f"{self.max_workers} worker(s). Press Ctrl-C to stop."
        )

    def _require_single_repo(self) -> str:
        if self.config.repo is None:
            raise RuntimeError("review enqueue requires an explicit repository")
        return self.config.repo

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_number, self.request_shutdown)
            except NotImplementedError:
                pass
