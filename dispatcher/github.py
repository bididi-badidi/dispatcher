from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from dispatcher.models import Config, Issue
from dispatcher.state_backend import StateBackend
from dispatcher.subprocess_utils import run_json

_PR_NUMBER_RE = re.compile(r"/pull/(\d+)(?:\D.*)?$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TerminalPr:
    issue: Issue
    status: str


def _label_names(item: dict[object, object]) -> set[str]:
    labels = item.get("labels", [])
    if not isinstance(labels, list):
        return set()
    return {
        str(label["name"])
        for label in labels
        if isinstance(label, dict) and "name" in label
    }


def list_triggered_issues(config: Config, repo: str) -> list[Issue]:
    raw_issues = run_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            config.label,
            "--state",
            "open",
            "--json",
            "number,title,url,labels",
            "--limit",
            "20",
        ],
        cwd=config.paths.project_dir,
        debug=config.debug,
    )
    return [
        Issue(
            number=int(item["number"]),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            plan_model=(
                config.opus_model
                if {config.label, config.opus_label}.issubset(_label_names(item))
                else None
            ),
        )
        for item in raw_issues
    ]


def list_prs_needing_review_response(
    config: Config,
    repo: str,
    store: StateBackend,
) -> list[tuple[Issue, str, tuple[int, int, int]]]:
    pending: list[tuple[Issue, str, tuple[int, int, int]]] = []
    for state in store.list_issue_states(repo):
        if state.get("status") not in {"pr_opened", "failed"} or not state.get(
            "pr_url"
        ):
            continue

        if state.get("pr_review_cursor") is None:
            logger.warning(
                "PR %s for %s#%s has no review cursor; skipping feedback poll",
                state["pr_url"],
                repo,
                state.get("number"),
            )
            continue

        # Per-endpoint cursors; fall back to the single cursor for old states.
        cursor_reviews = int(state["pr_review_cursor"])
        _legacy = cursor_reviews
        cursor_issue = int(
            state["pr_issue_comment_cursor"]
            if state.get("pr_issue_comment_cursor") is not None
            else _legacy
        )
        cursor_rc = int(
            state["pr_review_comment_cursor"]
            if state.get("pr_review_comment_cursor") is not None
            else _legacy
        )

        pr_number = pr_number_from_url(str(state["pr_url"]))
        reviews = run_json(
            ["gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews"],
            cwd=config.paths.project_dir,
        )
        issue_comments = run_json(
            ["gh", "api", f"repos/{repo}/issues/{pr_number}/comments"],
            cwd=config.paths.project_dir,
        )
        review_comments = run_json(
            ["gh", "api", f"repos/{repo}/pulls/{pr_number}/comments"],
            cwd=config.paths.project_dir,
        )
        new_reviews = [
            review
            for review in reviews
            if int(review.get("id") or 0) > cursor_reviews
            and review.get("state") in {"CHANGES_REQUESTED", "COMMENTED"}
        ]
        new_issue_comments = [
            comment
            for comment in issue_comments
            if int(comment.get("id") or 0) > cursor_issue
        ]
        new_review_comments = [
            comment
            for comment in review_comments
            if int(comment.get("id") or 0) > cursor_rc
        ]
        if not new_reviews and not new_issue_comments and not new_review_comments:
            continue

        issue = _issue_from_state(state)
        feedback = _format_review_feedback(
            new_reviews, new_issue_comments, new_review_comments
        )
        new_reviews_cursor = (
            max(_feedback_ids(new_reviews)) if new_reviews else cursor_reviews
        )
        new_issue_cursor = (
            max(_feedback_ids(new_issue_comments))
            if new_issue_comments
            else cursor_issue
        )
        new_rc_cursor = (
            max(_feedback_ids(new_review_comments))
            if new_review_comments
            else cursor_rc
        )
        pending.append(
            (issue, feedback, (new_reviews_cursor, new_issue_cursor, new_rc_cursor))
        )
    return pending


def list_merged_issues(
    config: Config,
    repo: str,
    store: StateBackend,
) -> list[Issue]:
    return [
        terminal.issue
        for terminal in list_terminal_prs(config, repo, store)
        if terminal.status == "merged"
    ]


def list_terminal_prs(
    config: Config,
    repo: str,
    store: StateBackend,
) -> list[TerminalPr]:
    terminal_prs: list[TerminalPr] = []
    for state in store.list_issue_states(repo):
        if state.get("status") not in {
            "pr_opened",
            "pr_review_queued",
            "merged",
            "closed",
            "failed",
        }:
            continue
        if not state.get("pr_url"):
            continue

        pr_number = pr_number_from_url(str(state["pr_url"]))
        pr_state = run_json(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                repo,
                "--json",
                "state",
            ],
            cwd=config.paths.project_dir,
        )
        if pr_state.get("state") == "MERGED":
            terminal_prs.append(TerminalPr(_issue_from_state(state), "merged"))
        elif pr_state.get("state") == "CLOSED":
            terminal_prs.append(TerminalPr(_issue_from_state(state), "closed"))
    return terminal_prs


def initial_review_cursor(
    config: Config, repo: str, pr_number: str
) -> tuple[int, int, int]:
    results: list[int] = []
    for endpoint in _review_feedback_endpoints(repo, pr_number):
        items = run_json(["gh", "api", endpoint], cwd=config.paths.project_dir)
        ids = _safe_item_ids(items)
        results.append(max(ids) if ids else 0)
    return results[0], results[1], results[2]


def pr_number_from_url(pr_url: str) -> str:
    match = _PR_NUMBER_RE.search(pr_url)
    if not match:
        raise ValueError(f"could not parse PR number from URL: {pr_url}")
    return match.group(1)


_pr_number_from_url = pr_number_from_url


def _review_feedback_endpoints(repo: str, pr_number: str) -> tuple[str, str, str]:
    return (
        f"repos/{repo}/pulls/{pr_number}/reviews",
        f"repos/{repo}/issues/{pr_number}/comments",
        f"repos/{repo}/pulls/{pr_number}/comments",
    )


def _safe_item_ids(items: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for item in items:
        try:
            ids.append(int(item.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return ids


def _issue_from_state(state: dict[str, Any]) -> Issue:
    return Issue(
        number=int(state["number"]),
        title=str(state.get("title", "")),
        url=str(state.get("url", "")),
    )


def _format_review_feedback(
    reviews: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
) -> str:
    feedback: list[str] = []
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        author = str(login or "unknown reviewer")
        body = str(review.get("body") or "No details provided.")
        feedback.append(f"Review #{review['id']} by {author}:\n{body}")
    for comment in issue_comments:
        user = comment.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        author = str(login or "unknown commenter")
        body = str(comment.get("body") or "No details provided.")
        feedback.append(f"PR comment #{comment['id']} by {author}:\n{body}")
    for comment in review_comments:
        user = comment.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        author = str(login or "unknown commenter")
        body = str(comment.get("body") or "No details provided.")
        location = _format_review_comment_location(comment)
        feedback.append(
            f"Inline comment #{comment['id']} by {author}{location}:\n{body}"
        )
    return "\n\n".join(feedback)


def _feedback_ids(feedback_items: list[dict[str, Any]]) -> list[int]:
    return [int(item["id"]) for item in feedback_items]


def _format_review_comment_location(comment: dict[str, Any]) -> str:
    path = comment.get("path")
    line = comment.get("line") or comment.get("original_line")
    if path and line:
        return f" on {path}:{line}"
    if path:
        return f" on {path}"
    return ""
