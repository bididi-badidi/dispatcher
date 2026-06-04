from __future__ import annotations

import logging
from dataclasses import replace

from dispatcher.config import (
    BaseBranchResolution,
    resolve_base_branch,
    resolve_projects_dir,
    resolve_root_dir,
)
from dispatcher.constants import DEFAULT_BASE_BRANCH
from dispatcher.git import default_worktree_root, repo_name_from_full_name
from dispatcher.models import Config, Paths

LOGGER = logging.getLogger(__name__)
_LOGGED_BASE_BRANCH_RESOLUTIONS: set[tuple[str, str, str, str | None]] = set()


def config_for_repo(config: Config, repo: str) -> Config:
    if config.repo == repo:
        _log_base_branch_resolution(
            repo=repo,
            requested=config.base_branch,
            resolution=BaseBranchResolution(
                branch=config.base_branch,
                project_dir=config.paths.project_dir,
                fell_back=False,
            ),
        )
        return config

    repo_name = repo_name_from_full_name(repo)
    projects_dir = resolve_projects_dir()
    worktree_root = default_worktree_root(repo_name, projects_dir).resolve()
    requested_project_dir = (worktree_root / config.base_branch).resolve()
    fallback_project_dir = (worktree_root / DEFAULT_BASE_BRANCH).resolve()
    requested_branch = config.base_branch
    resolution = resolve_base_branch(
        config.base_branch,
        repo=repo,
        project_dir=requested_project_dir,
        fallback_project_dir=fallback_project_dir,
        worktree_root=worktree_root,
        dispatcher_dir=resolve_root_dir(),
    )
    _log_base_branch_resolution(
        repo=repo,
        requested=requested_branch,
        resolution=resolution,
    )
    return replace(
        config,
        repo=repo,
        base_branch=resolution.branch,
        paths=Paths(
            project_dir=resolution.project_dir,
            worktree_root=worktree_root,
            state_file=config.paths.state_file,
            log_dir=config.paths.log_dir,
        ),
    )


def _log_base_branch_resolution(
    *,
    repo: str,
    requested: str,
    resolution: BaseBranchResolution,
) -> None:
    key = (repo, requested, resolution.branch, resolution.cause)
    if key in _LOGGED_BASE_BRANCH_RESOLUTIONS:
        return

    _LOGGED_BASE_BRANCH_RESOLUTIONS.add(key)
    LOGGER.info(
        "base_branch_resolution repo=%s requested=%s resolved=%s "
        "project_dir=%s fell_back=%s cause=%s",
        repo,
        requested,
        resolution.branch,
        resolution.project_dir,
        resolution.fell_back,
        resolution.cause or "",
    )
