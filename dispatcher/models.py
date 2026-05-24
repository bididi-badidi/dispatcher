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
    repo: str | None
    label: str
    base_branch: str
    branch_prefix: str
    paths: Paths
    commands: Commands
    dry_run: bool
    poll_interval_seconds: float = 120.0
    redis_url: str | None = None
    redis_poll_interval: int = 60
    once: bool = False
    daemon: bool = False
    max_workers: int = 3


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
    task_type: str = "fresh"
    worker_id: int | None = None
    build_iteration: int = 0
    build_feedback: str | None = None
    plan_review: str | None = None
    plan_review_feedback: str | None = None
    quality_review: str | None = None
    quality_review_feedback: str | None = None
    pr_url: str | None = None
