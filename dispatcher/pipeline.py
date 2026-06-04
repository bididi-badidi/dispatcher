from __future__ import annotations

import re
from typing import Sequence

from dispatcher.git import (
    branch_for_issue,
    require_worktree_path,
    worktree_path_for_issue,
)
from dispatcher.github import initial_review_cursor, pr_number_from_url
from dispatcher.models import Config, Issue, IssueState
from dispatcher.runners import build_stage_runners, run_stage
from dispatcher.s3_logs import (
    issue_stage_log_paths,
    uploader_from_config,
    write_issue_log_fallback,
)
from dispatcher.state_backend import StateBackend
from dispatcher.time_utils import utc_now

_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")
_STARTED_OR_TERMINAL_STATUSES = {
    "started",
    "planned",
    "built",
    "pr_opened",
    "pr_review_queued",
    "merged",
    "closed",
    "cleaned_up",
    "failed",
}


def run_pipeline(issue: Issue, config: Config, store: StateBackend) -> IssueState:
    repo = _require_repo(config)
    existing = store.get(repo, issue.number)
    if existing and existing.get("status") in _STARTED_OR_TERMINAL_STATUSES:
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

        build_output = run_stage(
            "build", runners["build"], issue, config, worktree, branch
        )
        pr_url = _extract_pr_url(build_output)
        if pr_url:
            state.status = "pr_opened"
            state.pr_url = pr_url
            (
                state.pr_review_cursor,
                state.pr_issue_comment_cursor,
                state.pr_review_comment_cursor,
            ) = initial_review_cursor(config, repo, pr_number_from_url(pr_url))
        elif config.dry_run:
            state.status = "built"
        else:
            raise RuntimeError("build stage did not print a GitHub PR URL")
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


def _extract_pr_url(output: str) -> str | None:
    match = _PR_URL_RE.search(output)
    return match.group(0) if match else None


def _submit_issue_upload(config: Config, issue_number: int) -> None:
    repo = _require_repo(config)
    uploader = uploader_from_config(config)
    stage_paths = issue_stage_log_paths(config.paths.log_dir, repo, issue_number)
    if not stage_paths:
        return
    if uploader is None:
        write_issue_log_fallback(config, repo, issue_number, stage_paths)
        return

    from dispatcher.background import get_default_background

    get_default_background().submit_issue_upload(
        uploader, repo, issue_number, stage_paths
    )
