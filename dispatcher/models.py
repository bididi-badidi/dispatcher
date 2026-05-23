from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    url: str


@dataclass(frozen=True)
class Paths:
    project_dir: Path
    worktree_root: Path
    state_file: Path
    log_dir: Path


@dataclass(frozen=True)
class Commands:
    worktree: str
    plan: str
    build: str


@dataclass(frozen=True)
class Config:
    repo: str
    label: str
    base_branch: str
    branch_prefix: str
    paths: Paths
    commands: Commands
    dry_run: bool


@dataclass
class IssueState:
    number: int
    title: str
    url: str
    status: str
    branch: str
    worktree: str
    updated_at: str
    error: str | None = None
