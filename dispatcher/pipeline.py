from __future__ import annotations

from typing import Sequence

from dispatcher.git import (
    branch_for_issue,
    require_worktree_path,
    worktree_path_for_issue,
)
from dispatcher.models import Config, Issue, IssueState
from dispatcher.runners import build_stage_runners, run_stage
from dispatcher.state import StateStore
from dispatcher.time_utils import utc_now


def run_pipeline(issue: Issue, config: Config, store: StateStore) -> IssueState:
    existing = store.get(config.repo, issue.number)
    if existing and existing.get("status") in {"started", "planned", "built", "failed"}:
        return IssueState(**existing)

    worktree = worktree_path_for_issue(config, issue)
    branch = branch_for_issue(config, issue)
    runners = build_stage_runners(config)
    state = IssueState(
        number=issue.number,
        title=issue.title,
        url=issue.url,
        status="started",
        branch=branch,
        worktree=str(worktree),
        updated_at=utc_now(),
    )
    store.upsert(config.repo, state)

    try:
        run_stage("worktree", runners["worktree"], issue, config, worktree, branch)
        if not config.dry_run:
            require_worktree_path(worktree)
        state.status = "worktree_created"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)

        run_stage("plan", runners["plan"], issue, config, worktree, branch)
        state.status = "planned"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)

        run_stage("build", runners["build"], issue, config, worktree, branch)
        state.status = "built"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.updated_at = utc_now()
        store.upsert(config.repo, state)
        raise

    return state


def first_unstarted_issue(
    issues: Sequence[Issue], repo: str, store: StateStore
) -> Issue | None:
    for issue in issues:
        existing = store.get(repo, issue.number)
        if not existing:
            return issue
    return None
