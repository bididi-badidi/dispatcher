from __future__ import annotations

import re
from typing import Any

from dispatcher.models import Config, Issue
from dispatcher.state_backend import StateBackend
from dispatcher.subprocess_utils import run_json

_PR_NUMBER_RE = re.compile(r"/pull/(\d+)(?:\D.*)?$")


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
) -> list[tuple[Issue, str, int]]:
    pending: list[tuple[Issue, str, int]] = []
    for state in store.list_issue_states(repo):
        if state.get("status") != "pr_opened" or not state.get("pr_url"):
            continue

        pr_number = _pr_number_from_url(str(state["pr_url"]))
        reviews = run_json(
            ["gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews"],
            cwd=config.paths.project_dir,
        )
        cursor = int(state.get("pr_review_cursor") or 0)
        new_reviews = [
            review
            for review in reviews
            if int(review.get("id") or 0) > cursor
            and review.get("state") == "CHANGES_REQUESTED"
        ]
        if not new_reviews:
            continue

        issue = _issue_from_state(state)
        feedback = _format_review_feedback(new_reviews)
        new_cursor = max(int(review["id"]) for review in new_reviews)
        pending.append((issue, feedback, new_cursor))
    return pending


def list_merged_issues(
    config: Config,
    repo: str,
    store: StateBackend,
) -> list[Issue]:
    merged: list[Issue] = []
    for state in store.list_issue_states(repo):
        if state.get("status") not in {"pr_opened", "pr_review_queued", "merged"}:
            continue
        if not state.get("pr_url"):
            continue

        pr_number = _pr_number_from_url(str(state["pr_url"]))
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
            merged.append(_issue_from_state(state))
    return merged


def _pr_number_from_url(pr_url: str) -> str:
    match = _PR_NUMBER_RE.search(pr_url)
    if not match:
        raise ValueError(f"could not parse PR number from URL: {pr_url}")
    return match.group(1)


def _issue_from_state(state: dict[str, Any]) -> Issue:
    return Issue(
        number=int(state["number"]),
        title=str(state.get("title", "")),
        url=str(state.get("url", "")),
    )


def _format_review_feedback(reviews: list[dict[str, Any]]) -> str:
    feedback: list[str] = []
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        author = str(login or "unknown reviewer")
        body = str(review.get("body") or "No details provided.")
        feedback.append(f"Review #{review['id']} by {author}:\n{body}")
    return "\n\n".join(feedback)
