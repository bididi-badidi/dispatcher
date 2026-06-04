from __future__ import annotations

from dataclasses import replace

from dispatcher.config import (
    resolve_base_branch,
    resolve_projects_dir,
    resolve_root_dir,
)
from dispatcher.constants import DEFAULT_BASE_BRANCH
from dispatcher.git import default_worktree_root, repo_name_from_full_name
from dispatcher.models import Config, Paths


def config_for_repo(config: Config, repo: str) -> Config:
    if config.repo == repo:
        return config

    repo_name = repo_name_from_full_name(repo)
    projects_dir = resolve_projects_dir()
    worktree_root = default_worktree_root(repo_name, projects_dir).resolve()
    requested_project_dir = (worktree_root / config.base_branch).resolve()
    fallback_project_dir = (worktree_root / DEFAULT_BASE_BRANCH).resolve()
    base_branch = resolve_base_branch(
        config.base_branch,
        repo=repo,
        project_dir=requested_project_dir,
        fallback_project_dir=fallback_project_dir,
        worktree_root=worktree_root,
        dispatcher_dir=resolve_root_dir(),
    )
    project_dir = (worktree_root / base_branch).resolve()
    return replace(
        config,
        repo=repo,
        base_branch=base_branch,
        paths=Paths(
            project_dir=project_dir,
            worktree_root=worktree_root,
            state_file=config.paths.state_file,
            log_dir=config.paths.log_dir,
        ),
    )
