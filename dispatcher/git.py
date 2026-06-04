from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import subprocess
from pathlib import Path

from dispatcher.models import Config, Issue

BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS = 5


class BranchLookup(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class _GitOutcome:
    returncode: int
    stdout: str
    stderr: str
    errored: bool = False


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
    return lookup_branch(branch, cwd=cwd) is BranchLookup.PRESENT


def lookup_branch(branch: str, cwd: Path | None = None) -> BranchLookup:
    """Return a tri-state result for local or origin branch lookup."""
    if cwd is None or not cwd.exists():
        return BranchLookup.UNKNOWN

    saw_error = False
    run_kwargs = {"capture_output": True, "cwd": cwd, "text": True}

    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        result = _run_git(["git", "show-ref", "--verify", "--quiet", ref], run_kwargs)
        if result.returncode == 0:
            return BranchLookup.PRESENT
        if _is_clean_ref_miss(result):
            continue
        saw_error = True

    remote = _run_git(
        ["git", "ls-remote", "--heads", "origin", branch],
        {**run_kwargs, "timeout": BRANCH_REMOTE_LOOKUP_TIMEOUT_SECONDS},
    )
    if remote.errored:
        return BranchLookup.UNKNOWN
    if remote.returncode == 0:
        return BranchLookup.PRESENT if remote.stdout.strip() else BranchLookup.ABSENT
    if remote.stderr.strip():
        return BranchLookup.UNKNOWN
    return BranchLookup.UNKNOWN if saw_error else BranchLookup.ABSENT


def _run_git(
    command: list[str],
    run_kwargs: dict[str, object],
) -> _GitOutcome:
    try:
        result = subprocess.run(command, **run_kwargs)
        return _GitOutcome(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _GitOutcome(returncode=1, stdout="", stderr="", errored=True)


def _is_clean_ref_miss(result: _GitOutcome) -> bool:
    return result.returncode == 1 and not result.stderr.strip() and not result.errored


def repo_name_from_full_name(repo: str) -> str:
    return repo.rsplit("/", maxsplit=1)[-1]


def default_projects_dir() -> Path:
    return Path("/Projects")


def default_worktree_root(
    repo_name: str,
    projects_dir: Path | None = None,
) -> Path:
    return (projects_dir or default_projects_dir()) / repo_name
