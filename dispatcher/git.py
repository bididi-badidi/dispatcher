from __future__ import annotations

import subprocess
from pathlib import Path

from dispatcher.models import Config, Issue


def worktree_git_dir(worktree: Path) -> Path | None:
    git_marker = worktree / ".git"
    if git_marker.is_dir():
        return git_marker.resolve()
    if not git_marker.is_file():
        return None

    prefix = "gitdir:"
    marker = git_marker.read_text(encoding="utf-8").strip()
    if not marker.startswith(prefix):
        return None

    git_dir = Path(marker.removeprefix(prefix).strip())
    if not git_dir.is_absolute():
        git_dir = worktree / git_dir
    return git_dir.resolve()


def common_git_dir(git_dir: Path) -> Path:
    common_dir_marker = git_dir / "commondir"
    if not common_dir_marker.is_file():
        return git_dir

    common_dir = Path(common_dir_marker.read_text(encoding="utf-8").strip())
    if not common_dir.is_absolute():
        common_dir = git_dir / common_dir
    return common_dir.resolve()


def codex_git_write_dirs(worktree: Path) -> list[Path]:
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return []

    workspace = worktree.resolve()
    write_dirs: list[Path] = []
    for git_write_dir in (git_dir, common_git_dir(git_dir)):
        if git_write_dir == workspace or workspace in git_write_dir.parents:
            continue
        if git_write_dir not in write_dirs:
            write_dirs.append(git_write_dir)
    return write_dirs


def worktree_path_for_issue(config: Config, issue: Issue) -> Path:
    return config.paths.worktree_root / branch_for_issue(config, issue)


def branch_for_issue(config: Config, issue: Issue) -> str:
    return f"{config.branch_prefix}{issue.number}"


def require_worktree_path(worktree: Path) -> None:
    if not worktree.is_dir():
        raise RuntimeError(
            "worktree stage completed without creating the expected worktree "
            f"directory: {worktree}"
        )


def branch_exists(branch: str, cwd: Path | None = None) -> bool:
    """Return True when a branch exists locally or on origin."""
    run_kwargs = {"capture_output": True, "cwd": cwd, "text": True}

    local = subprocess.run(["git", "branch", "--list", branch], **run_kwargs)
    if local.stdout.strip():
        return True

    remote = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch], **run_kwargs
    )
    return bool(remote.stdout.strip())


def repo_name_from_full_name(repo: str) -> str:
    return repo.rsplit("/", maxsplit=1)[-1]


def default_projects_dir() -> Path:
    return Path("/Projects")


def default_worktree_root(
    repo_name: str,
    projects_dir: Path | None = None,
) -> Path:
    return (projects_dir or default_projects_dir()) / repo_name
