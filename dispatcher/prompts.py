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
        "project_dir": str(config.paths.project_dir),
        "repo": config.repo,
        "worktree": str(worktree),
    }
    return Template(template).safe_substitute(values)


def default_worktree_command() -> str:
    return (
        "Create a git worktree for GitHub issue #$issue_number "
        "($issue_title) based on $base_branch at $worktree using branch $branch."
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
