from __future__ import annotations

from pathlib import Path

from dispatcher.models import Commands, Config, Paths


def make_config(
    root: Path, *, dry_run: bool = True, repo: str | None = "example/repo"
) -> Config:
    return Config(
        repo=repo,
        label="automate",
        opus_label="automate:opus",
        opus_model="claude-opus-4-7",
        base_branch="main",
        branch_prefix="feat/issue-",
        paths=Paths(
            project_dir=root,
            worktree_root=root.parent,
            state_file=root / ".dispatcher" / "state.json",
            log_dir=root / ".dispatcher" / "logs",
        ),
        commands=Commands(
            worktree="worktree $issue_number $worktree $branch",
            plan="plan $issue_number $worktree",
            build="build $issue_number $branch",
        ),
        dry_run=dry_run,
    )
