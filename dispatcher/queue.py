from __future__ import annotations

import asyncio
import enum
import signal
import sys
from dataclasses import dataclass

from dispatcher.github import list_triggered_issues
from dispatcher.langgraph_pipeline import async_run_langgraph_pipeline
from dispatcher.models import Config, Issue
from dispatcher.state import StateStore


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
        self, config: Config, store: StateStore, max_workers: int | None = None
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
        self._in_flight: set[int] = set()
        self._active: dict[int, Task | None] = {
            worker_id: None for worker_id in range(self.max_workers)
        }
        self._completed_count = 0
        self._failed_count = 0

    async def run(self) -> None:
        self._install_signal_handlers()
        print(
            f"Polling {self.config.repo} for label {self.config.label!r} every "
            f"{self.config.poll_interval_seconds:g} seconds with "
            f"{self.max_workers} worker(s). Press Ctrl-C to stop."
        )
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
                await self._enqueue_triggered_issues()
            except Exception as exc:
                print(f"Polling cycle failed: {exc}", file=sys.stderr)

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.config.poll_interval_seconds,
                )
            except TimeoutError:
                pass

    async def _enqueue_triggered_issues(self) -> None:
        issues = await asyncio.to_thread(list_triggered_issues, self.config)
        for issue in issues:
            if self._should_skip_issue(issue, skip_existing=True):
                continue
            task = Task(self.config.repo, issue)
            await self._enqueue_task(task)

    async def _worker(self, worker_id: int) -> None:
        while True:
            task = await self._queue.get()
            if task is None:
                self._queue.task_done()
                break

            self._active[worker_id] = task
            try:
                await async_run_langgraph_pipeline(
                    task, self.config, self.store, worker_id, self._shutdown
                )
                self._completed_count += 1
            except Exception as exc:
                self._failed_count += 1
                print(
                    f"Worker {worker_id} failed issue #{task.issue.number}: {exc}",
                    file=sys.stderr,
                )
            finally:
                self._active[worker_id] = None
                self._in_flight.discard(task.issue.number)
                self._queue.task_done()

    def enqueue_review(self, issue: Issue) -> bool:
        task = Task(self.config.repo, issue, TaskType.REVIEW)
        if self._should_skip_issue(issue, skip_existing=False):
            return False

        self._mark_queued(task)
        try:
            self._queue.put_nowait(task)
        except asyncio.QueueFull:
            self._in_flight.discard(task.issue.number)
            return False
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

    def _should_skip_issue(self, issue: Issue, *, skip_existing: bool) -> bool:
        if issue.number in self._in_flight:
            return True

        return (
            skip_existing and self.store.get(self.config.repo, issue.number) is not None
        )

    def _mark_queued(self, task: Task) -> None:
        self._in_flight.add(task.issue.number)

    async def _enqueue_task(self, task: Task) -> bool:
        self._mark_queued(task)
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._queue.put(task),
                    timeout=self._QUEUE_PUT_TIMEOUT_SECONDS,
                )
                return True
            except TimeoutError:
                pass

        self._in_flight.discard(task.issue.number)
        return False

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_number, self.request_shutdown)
            except NotImplementedError:
                pass
