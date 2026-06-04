from __future__ import annotations

import subprocess
import logging
from pathlib import Path

from dispatcher.subprocess_utils import print_subprocess_command

LOGGER = logging.getLogger(__name__)


def delete_remote_branch(branch: str, project_dir: Path) -> None:
    _run_best_effort(["git", "push", "origin", "--delete", branch], project_dir)


def remove_local_worktree(worktree: Path, branch: str, project_dir: Path) -> None:
    _run_best_effort(
        ["git", "worktree", "remove", "--force", str(worktree)], project_dir
    )
    try:
        _run(["git", "branch", "-d", branch], project_dir)
    except subprocess.CalledProcessError:
        _run_best_effort(["git", "branch", "-D", branch], project_dir)


def cleanup_merged_branch(branch: str, worktree: Path, project_dir: Path) -> None:
    delete_remote_branch(branch, project_dir)
    remove_local_worktree(worktree, branch, project_dir)


def _run_best_effort(command: list[str], cwd: Path) -> None:
    try:
        _run(command, cwd)
    except subprocess.CalledProcessError as exc:
        LOGGER.warning("cleanup command failed: %s", exc)


def _run(command: list[str], cwd: Path) -> None:
    print_subprocess_command(command)
    subprocess.run(command, cwd=cwd, check=True)
