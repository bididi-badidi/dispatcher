from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from dispatcher.config import resolve_root_dir
from dispatcher.git import default_worktree_root, repo_name_from_full_name
from dispatcher.models import Config, Paths


def config_for_repo(config: Config, repo: str) -> Config:
    if config.repo == repo:
        return config

    dispatcher_dir = _dispatcher_dir(config.paths.state_file)
    repo_name = repo_name_from_full_name(repo)
    worktree_root = default_worktree_root(
        dispatcher_dir, repo_name, config.base_branch
    ).resolve()
    project_dir = (worktree_root / config.base_branch).resolve()
    return replace(
        config,
        repo=repo,
        paths=Paths(
            project_dir=project_dir,
            worktree_root=worktree_root,
            state_file=config.paths.state_file,
            log_dir=config.paths.log_dir,
        ),
    )


def _dispatcher_dir(state_file: Path) -> Path:
    if state_file.parent.name == ".dispatcher":
        return state_file.parent.parent
    return resolve_root_dir()
