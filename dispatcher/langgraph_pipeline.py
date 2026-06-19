from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from dispatcher.async_runners import async_run_stage
from dispatcher.git import (
    branch_for_issue,
    require_worktree_path,
    worktree_path_for_issue,
)
from dispatcher.github import initial_review_cursor, pr_number_from_url
from dispatcher.models import Config, Issue, IssueState
from dispatcher.prompts import (
    default_open_pr_command,
    default_review_plan_command,
    default_review_quality_command,
)
from dispatcher.runners import (
    AgentRunner,
    ClaudeReviewRunner,
    CodexRunner,
    CodexOpenPrRunner,
    build_stage_runners,
)
from dispatcher.s3_logs import issue_stage_log_paths, uploader_from_config
from dispatcher.state_backend import StateBackend
from dispatcher.time_utils import utc_now

MAX_ITERATIONS = 3
_VERDICT_RE = re.compile(
    r"^\s*VERDICT:\s*(approved|changes_requested)\s*$", re.I | re.M
)
_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


class PipelineTask(Protocol):
    issue: Issue
    task_type: object


class PipelineState(TypedDict, total=False):
    issue_number: int
    issue_title: str
    issue_url: str
    repo: str
    base_branch: str
    task_type: str
    worker_id: int | None
    worktree: Path
    branch: str
    plan_path: Path | None
    plan_content: str | None
    build_iteration: int
    build_feedback: str | None
    plan_review: Literal["approved", "changes_requested"] | None
    plan_review_feedback: str | None
    quality_review: Literal["approved", "changes_requested"] | None
    quality_review_feedback: str | None
    max_iterations: int
    pr_url: str | None
    pr_review_cursor: int | None
    pr_issue_comment_cursor: int | None
    pr_review_comment_cursor: int | None
    status: str
    error: str | None


async def async_run_langgraph_pipeline(
    task: PipelineTask,
    config: Config,
    store: StateBackend,
    worker_id: int,
    shutdown_event: asyncio.Event,
) -> IssueState:
    issue = task.issue
    repo = _require_repo(config)
    task_type = getattr(task.task_type, "value", str(task.task_type))
    worktree = worktree_path_for_issue(config, issue)
    branch = branch_for_issue(config, issue)
    existing = store.get(repo, issue.number)
    max_iterations = int(os.getenv("DISPATCHER_MAX_ITERATIONS", str(MAX_ITERATIONS)))
    if max_iterations <= 0:
        raise ValueError("DISPATCHER_MAX_ITERATIONS must be greater than 0")

    initial_state: PipelineState = {
        "issue_number": issue.number,
        "issue_title": issue.title,
        "issue_url": issue.url,
        "repo": repo,
        "base_branch": config.base_branch,
        "task_type": task_type,
        "worker_id": worker_id,
        "worktree": worktree,
        "branch": branch,
        "plan_path": None,
        "plan_content": None,
        "build_iteration": 0,
        "build_feedback": None,
        "plan_review": None,
        "plan_review_feedback": None,
        "quality_review": None,
        "quality_review_feedback": None,
        "max_iterations": max_iterations,
        "pr_url": None,
        "pr_review_cursor": None,
        "pr_issue_comment_cursor": None,
        "pr_review_comment_cursor": None,
        "status": "started",
        "error": None,
    }
    if existing:
        initial_state["build_iteration"] = int(existing.get("build_iteration") or 0)
        initial_state["build_feedback"] = existing.get("build_feedback")
        initial_state["plan_review"] = existing.get("plan_review")
        initial_state["plan_review_feedback"] = existing.get("plan_review_feedback")
        initial_state["quality_review"] = existing.get("quality_review")
        initial_state["quality_review_feedback"] = existing.get(
            "quality_review_feedback"
        )
        initial_state["pr_url"] = existing.get("pr_url")
        initial_state["pr_review_cursor"] = existing.get("pr_review_cursor")
        initial_state["pr_issue_comment_cursor"] = existing.get(
            "pr_issue_comment_cursor"
        )
        initial_state["pr_review_comment_cursor"] = existing.get(
            "pr_review_comment_cursor"
        )

    graph = _build_graph(config, store, issue, shutdown_event)
    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as exc:
        # Preserve whatever the last persisted node wrote, if any, so failures
        # late in the graph don't overwrite useful progress in the state store.
        latest = store.get(repo, issue.number) or {}
        failed_state = dict(initial_state)
        for key in (
            "build_iteration",
            "build_feedback",
            "plan_review",
            "plan_review_feedback",
            "quality_review",
            "quality_review_feedback",
            "pr_url",
            "pr_review_cursor",
            "pr_issue_comment_cursor",
            "pr_review_comment_cursor",
        ):
            if key in latest:
                failed_state[key] = latest[key]
        failed_state["status"] = "failed"
        failed_state["error"] = str(exc)
        failed_state["worker_id"] = None
        _persist_state(config, store, failed_state)
        _submit_issue_upload(config, issue.number)
        raise

    persisted_state = _persist_state(config, store, final_state)
    _submit_issue_upload(config, issue.number)
    return persisted_state


def _build_graph(
    config: Config,
    store: StateBackend,
    issue: Issue,
    shutdown_event: asyncio.Event,
):
    runners = build_stage_runners(config)

    async def create_worktree(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        worktree = state["worktree"]
        branch = state["branch"]
        if state["task_type"] == "fresh":
            await async_run_stage(
                "worktree", runners["worktree"], issue, config, worktree, branch
            )
            if not config.dry_run:
                require_worktree_path(worktree)
        elif not config.dry_run:
            require_worktree_path(worktree)

        updates = {"status": "worktree_created", "error": None}
        _persist_state(config, store, state | updates)
        return updates

    async def plan(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        worktree = state["worktree"]
        branch = state["branch"]
        await async_run_stage("plan", runners["plan"], issue, config, worktree, branch)
        plan_path = _plan_path(worktree, branch)
        plan_content = (
            plan_path.read_text(encoding="utf-8") if plan_path.is_file() else None
        )
        updates = {
            "status": "planned",
            "plan_path": plan_path,
            "plan_content": plan_content,
            "error": None,
        }
        _persist_state(config, store, state | updates)
        return updates

    async def build(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        worktree = state["worktree"]
        branch = state["branch"]
        build_iteration = int(state.get("build_iteration", 0)) + 1
        prompt_template = config.commands.build
        if state.get("build_feedback"):
            prompt_template = (
                f"{prompt_template}\n\nReviewer feedback to address on this retry:\n"
                f"{state['build_feedback']}"
            )
        await async_run_stage(
            "build", CodexRunner(prompt_template), issue, config, worktree, branch
        )
        updates = {
            "status": "built",
            "build_iteration": build_iteration,
            "build_feedback": None,
            "plan_review": None,
            "plan_review_feedback": None,
            "quality_review": None,
            "quality_review_feedback": None,
            "error": None,
        }
        _persist_state(config, store, state | updates)
        return updates

    async def review_plan(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        output = await _run_review(
            "review_plan",
            ClaudeReviewRunner(default_review_plan_command()),
            state,
            issue,
            config,
        )
        verdict, feedback = _parse_verdict(output, config.dry_run)
        updates = {
            "plan_review": verdict,
            "plan_review_feedback": feedback,
        }
        _persist_state(config, store, state | updates)
        return updates

    async def review_quality(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        output = await _run_review(
            "review_quality",
            ClaudeReviewRunner(default_review_quality_command()),
            state,
            issue,
            config,
        )
        verdict, feedback = _parse_verdict(output, config.dry_run)
        updates = {
            "quality_review": verdict,
            "quality_review_feedback": feedback,
        }
        _persist_state(config, store, state | updates)
        return updates

    async def route_reviews(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        feedback = _combined_feedback(state)
        if feedback and int(state["build_iteration"]) >= int(state["max_iterations"]):
            updates = {
                "status": "failed",
                "error": (
                    "review changes requested after "
                    f"{state['build_iteration']} build iteration(s)"
                ),
                "build_feedback": feedback,
                "worker_id": None,
            }
        elif feedback:
            updates = {
                "status": "changes_requested",
                "build_feedback": feedback,
                "error": None,
            }
        else:
            updates = {
                "status": "approved",
                "build_feedback": None,
                "error": None,
            }
        _persist_state(config, store, state | updates)
        return updates

    async def open_pr(state: PipelineState) -> dict[str, object]:
        _raise_if_shutdown(shutdown_event)
        if state.get("task_type") == "review" and state.get("pr_url"):
            updates = {
                "status": "pr_opened",
                "worker_id": None,
                "error": None,
            }
            _persist_state(config, store, state | updates)
            return updates

        output = await async_run_stage(
            "open_pr",
            CodexOpenPrRunner(default_open_pr_command()),
            issue,
            config,
            state["worktree"],
            state["branch"],
        )
        match = _PR_URL_RE.search(output)
        pr_url = match.group(0) if match else state.get("pr_url")
        if not pr_url:
            raise RuntimeError("open_pr stage did not print a GitHub PR URL")
        _rc, _ic, _rcc = initial_review_cursor(
            config, state["repo"], pr_number_from_url(str(pr_url))
        )
        updates = {
            "status": "pr_opened",
            "pr_url": pr_url,
            "pr_review_cursor": _rc,
            "pr_issue_comment_cursor": _ic,
            "pr_review_comment_cursor": _rcc,
            "worker_id": None,
            "error": None,
        }
        _persist_state(config, store, state | updates)
        return updates

    def after_reviews(state: PipelineState) -> str:
        if state.get("status") == "failed":
            return "end"
        if state.get("build_feedback"):
            return "build"
        return "open_pr"

    workflow = StateGraph(PipelineState)
    workflow.add_node("create_worktree", create_worktree)
    workflow.add_node("plan", plan)
    workflow.add_node("build", build)
    workflow.add_node("review_plan", review_plan)
    workflow.add_node("review_quality", review_quality)
    workflow.add_node("route_reviews", route_reviews)
    workflow.add_node("open_pr", open_pr)
    workflow.add_edge(START, "create_worktree")
    workflow.add_edge("create_worktree", "plan")
    workflow.add_edge("plan", "build")
    workflow.add_edge("build", "review_plan")
    workflow.add_edge("build", "review_quality")
    workflow.add_edge(["review_plan", "review_quality"], "route_reviews")
    workflow.add_conditional_edges(
        "route_reviews",
        after_reviews,
        {"build": "build", "open_pr": "open_pr", "end": END},
    )
    workflow.add_edge("open_pr", END)
    return workflow.compile()


async def _run_review(
    name: str,
    runner: AgentRunner,
    state: PipelineState,
    issue: Issue,
    config: Config,
) -> str:
    runner.stage_name = name
    return await async_run_stage(
        name, runner, issue, config, state["worktree"], state["branch"]
    )


def _parse_verdict(
    output: str, dry_run: bool
) -> tuple[Literal["approved", "changes_requested"], str | None]:
    if dry_run and not output.strip():
        return "approved", None

    match = _VERDICT_RE.search(output)
    if not match:
        raise RuntimeError(
            "review stage did not emit 'VERDICT: approved' or "
            "'VERDICT: changes_requested'"
        )

    verdict = match.group(1).lower()
    feedback = _VERDICT_RE.sub("", output, count=1).strip() or None
    return verdict, feedback  # type: ignore[return-value]


def _combined_feedback(state: PipelineState) -> str | None:
    feedback: list[str] = []
    if state.get("plan_review") == "changes_requested":
        feedback.append(
            "Plan review requested changes:\n"
            f"{state.get('plan_review_feedback') or 'No details provided.'}"
        )
    if state.get("quality_review") == "changes_requested":
        feedback.append(
            "Quality review requested changes:\n"
            f"{state.get('quality_review_feedback') or 'No details provided.'}"
        )
    return "\n\n".join(feedback) or None


def _persist_state(
    config: Config, store: StateBackend, state: PipelineState
) -> IssueState:
    issue_state = IssueState(
        number=int(state["issue_number"]),
        title=str(state["issue_title"]),
        url=str(state["issue_url"]),
        status=str(state["status"]),
        branch=str(state["branch"]),
        worktree=str(state["worktree"]),
        updated_at=utc_now(),
        error=state.get("error"),
        task_type=str(state.get("task_type") or "fresh"),
        worker_id=state.get("worker_id"),
        build_iteration=int(state.get("build_iteration") or 0),
        build_feedback=state.get("build_feedback"),
        plan_review=state.get("plan_review"),
        plan_review_feedback=state.get("plan_review_feedback"),
        quality_review=state.get("quality_review"),
        quality_review_feedback=state.get("quality_review_feedback"),
        pr_url=state.get("pr_url"),
        pr_review_cursor=state.get("pr_review_cursor"),
        pr_issue_comment_cursor=state.get("pr_issue_comment_cursor"),
        pr_review_comment_cursor=state.get("pr_review_comment_cursor"),
    )
    store.upsert(str(state["repo"]), issue_state)
    return issue_state


def _plan_path(worktree: Path, branch: str) -> Path:
    return worktree / ".ai" / "assets" / "branches" / branch / "plan.md"


def _raise_if_shutdown(shutdown_event: asyncio.Event) -> None:
    if shutdown_event.is_set():
        raise RuntimeError("shutdown requested")


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
