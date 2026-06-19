from __future__ import annotations

from pathlib import Path
from string import Template

from dispatcher.models import Config, Issue


def render_template(
    template: str, issue: Issue, config: Config, worktree: Path, branch: str
) -> str:
    values = {
        "base_branch": config.base_branch,
        "branch": branch,
        "issue_number": str(issue.number),
        "issue_title": issue.title,
        "issue_url": issue.url,
        "label": config.label,
        "plan_path": str(worktree / ".ai" / "assets" / "branches" / branch / "plan.md"),
        "project_dir": str(config.paths.project_dir),
        "repo": config.repo or "",
        "worktree": str(worktree),
    }
    return Template(template).safe_substitute(values)


def default_worktree_command() -> str:
    return (
        "Create a git worktree for GitHub issue #$issue_number "
        "($issue_title): from $project_dir, fetch origin $base_branch if needed, "
        "create $worktree using branch $branch based on $base_branch, then copy "
        "seed config files such as .env and .env.local from $project_dir into "
        "$worktree. Do not modify code."
    )


def default_plan_command() -> str:
    return (
        "Read GitHub issue #$issue_number for this repo. Save the feature "
        "implementation plan under branch assets using the project "
        "instructions. Do not modify code."
    )


def default_build_command() -> str:
    return (
        "Read the implementation plan from the branch assets for GitHub issue "
        "#$issue_number. implement it, run relevant checks, push commit to "
        "remote, and open a PR with the configured GitHub MCP when it is "
        "available. Do not require the gh CLI for PR creation. Stop after PR "
        "creation."
    )


def default_review_plan_command() -> str:
    return (
        "Review the implementation for GitHub issue #$issue_number against the "
        "saved branch plan at $plan_path. Reply with exactly one verdict line: "
        "VERDICT: approved or VERDICT: changes_requested. Include concise "
        "feedback after the verdict only when changes are needed."
    )


def default_review_quality_command() -> str:
    return (
        "Review the code quality, edge cases, and test coverage for GitHub "
        "issue #$issue_number in $worktree. Reply with exactly one verdict "
        "line: VERDICT: approved or VERDICT: changes_requested. Include "
        "concise feedback after the verdict only when changes are needed."
    )


def default_open_pr_command() -> str:
    return (
        "From the worktree at $worktree (use `git -C $worktree ...`), push "
        "branch $branch for GitHub issue #$issue_number to the remote and open "
        "a pull request against $base_branch. Write the PR body to a file "
        "under /tmp (e.g. /tmp/pr-body-$issue_number.md), then call "
        "`gh pr create --body-file <that-file> --head $branch --base "
        "$base_branch -R $repo`. The PR body must include Closes "
        "#$issue_number. Do not edit any files inside $worktree. Print the PR "
        "URL when done."
    )
