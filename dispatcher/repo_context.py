from __future__ import annotations

from dataclasses import replace

from dispatcher.config import resolve_projects_dir
from dispatcher.git import default_worktree_root, repo_name_from_full_name
from dispatcher.models import Config, Paths


def config_for_repo(config: Config, repo: str) -> Config:
    if config.repo == repo:
        return config

    repo_name = repo_name_from_full_name(repo)
    projects_dir = resolve_projects_dir()
    worktree_root = default_worktree_root(repo_name, projects_dir).resolve()
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
