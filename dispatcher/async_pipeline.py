from __future__ import annotations

import asyncio
from typing import Protocol

from dispatcher.async_runners import async_run_stage
from dispatcher.git import (
    branch_for_issue,
    require_worktree_path,
    worktree_path_for_issue,
)
from dispatcher.models import Config, Issue, IssueState
from dispatcher.runners import build_stage_runners
from dispatcher.state_backend import StateBackend
from dispatcher.time_utils import utc_now


class PipelineTask(Protocol):
    issue: Issue
    task_type: object


async def async_run_pipeline(
    task: PipelineTask,
    config: Config,
    store: StateBackend,
    worker_id: int,
    shutdown_event: asyncio.Event,
) -> IssueState:
    issue = task.issue
    repo = _require_repo(config)
    worktree = worktree_path_for_issue(config, issue)
    branch = branch_for_issue(config, issue)
    task_type = getattr(task.task_type, "value", str(task.task_type))
    existing = store.get(repo, issue.number)

    state = (
        IssueState(**existing)
        if existing
        else IssueState(
            number=issue.number,
            title=issue.title,
            url=issue.url,
            status="queued",
            branch=branch,
            worktree=str(worktree),
            updated_at=utc_now(),
        )
    )
    state.task_type = task_type
    state.worker_id = worker_id
    state.error = None
    state.status = "started"
    state.updated_at = utc_now()
    store.upsert(repo, state)

    runners = build_stage_runners(config)

    try:
        if task_type == "fresh":
            _raise_if_shutdown(shutdown_event)
            await async_run_stage(
                "worktree", runners["worktree"], issue, config, worktree, branch
            )
            if not config.dry_run:
                require_worktree_path(worktree)
            state.status = "worktree_created"
            state.updated_at = utc_now()
            store.upsert(repo, state)
        elif not config.dry_run:
            require_worktree_path(worktree)

        _raise_if_shutdown(shutdown_event)
        await async_run_stage("plan", runners["plan"], issue, config, worktree, branch)
        state.status = "planned"
        state.updated_at = utc_now()
        store.upsert(repo, state)

        _raise_if_shutdown(shutdown_event)
        await async_run_stage(
            "build", runners["build"], issue, config, worktree, branch
        )
        state.status = "built"
        state.worker_id = None
        state.updated_at = utc_now()
        store.upsert(repo, state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.worker_id = None
        state.updated_at = utc_now()
        store.upsert(repo, state)
        raise

    return state


def _raise_if_shutdown(shutdown_event: asyncio.Event) -> None:
    if shutdown_event.is_set():
        raise RuntimeError("shutdown requested")


def _require_repo(config: Config) -> str:
    if config.repo is None:
        raise RuntimeError("pipeline requires a concrete repository")
    return config.repo
