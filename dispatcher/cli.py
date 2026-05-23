from __future__ import annotations

from typing import Sequence

from dispatcher.config import build_config
from dispatcher.github import list_triggered_issues
from dispatcher.pipeline import first_unstarted_issue, run_pipeline
from dispatcher.state import StateStore


def main(argv: Sequence[str] | None = None) -> int:
    config = build_config(argv)
    store = StateStore(config.paths.state_file)
    issues = list_triggered_issues(config)
    issue = first_unstarted_issue(issues, config.repo, store)
    if issue is None:
        print(f"No new open issues with label {config.label!r} in {config.repo}.")
        return 0

    state = run_pipeline(issue, config, store)
    print(
        f"Issue #{state.number} reached {state.status}: "
        f"branch={state.branch} worktree={state.worktree}"
    )
    return 0
