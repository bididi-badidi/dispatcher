from __future__ import annotations

from typing import Sequence

from dispatcher.git import (
    branch_for_issue,
    require_worktree_path,
    worktree_path_for_issue,
)
from dispatcher.models import Config, Issue, IssueState
from dispatcher.runners import build_stage_runners, run_stage
from dispatcher.s3_logs import issue_stage_log_paths, uploader_from_config
from dispatcher.state_backend import StateBackend
from dispatcher.time_utils import utc_now


def run_pipeline(issue: Issue, config: Config, store: StateBackend) -> IssueState:
    repo = _require_repo(config)
    existing = store.get(repo, issue.number)
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
    store.upsert(repo, state)

    try:
        run_stage("worktree", runners["worktree"], issue, config, worktree, branch)
        if not config.dry_run:
            require_worktree_path(worktree)
        state.status = "worktree_created"
        state.updated_at = utc_now()
        store.upsert(repo, state)

        run_stage("plan", runners["plan"], issue, config, worktree, branch)
        state.status = "planned"
        state.updated_at = utc_now()
        store.upsert(repo, state)

        run_stage("build", runners["build"], issue, config, worktree, branch)
        state.status = "built"
        state.updated_at = utc_now()
        store.upsert(repo, state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.updated_at = utc_now()
        store.upsert(repo, state)
        _submit_issue_upload(config, issue.number)
        raise

    _submit_issue_upload(config, issue.number)
    return state


def first_unstarted_issue(
    issues: Sequence[Issue], repo: str, store: StateBackend
) -> Issue | None:
    for issue in issues:
        existing = store.get(repo, issue.number)
        if not existing:
            return issue
    return None


def _require_repo(config: Config) -> str:
    if config.repo is None:
        raise RuntimeError("pipeline requires a concrete repository")
    return config.repo


def _submit_issue_upload(config: Config, issue_number: int) -> None:
    repo = _require_repo(config)
    uploader = uploader_from_config(config)
    if uploader is None:
        return
    stage_paths = issue_stage_log_paths(config.paths.log_dir, repo, issue_number)
    if not stage_paths:
        return

    from dispatcher.background import get_default_background

    get_default_background().submit_issue_upload(
        uploader, repo, issue_number, stage_paths
    )
