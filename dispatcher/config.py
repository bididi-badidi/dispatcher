from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from dispatcher.constants import (
    DEFAULT_BASE_BRANCH,
    DEFAULT_BRANCH_PREFIX,
    DEFAULT_LABEL,
    DEFAULT_LOG_DIR,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STATE_FILE,
)
from dispatcher.git import default_worktree_root, repo_name_from_full_name
from dispatcher.models import Commands, Config, Paths
from dispatcher.prompts import (
    default_build_command,
    default_plan_command,
    default_worktree_command,
)


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_config(argv: Sequence[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description="Run the local issue-triggered dispatcher happy path."
    )
    parser.add_argument(
        "--repo", required=True, help="GitHub repository in owner/name form."
    )
    parser.add_argument("--label", default=os.getenv("DISPATCHER_LABEL", DEFAULT_LABEL))
    parser.add_argument(
        "--base-branch",
        default=os.getenv("DISPATCHER_BASE_BRANCH", DEFAULT_BASE_BRANCH),
    )
    parser.add_argument(
        "--branch-prefix",
        default=os.getenv("DISPATCHER_BRANCH_PREFIX", DEFAULT_BRANCH_PREFIX),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help=(
            "Base checkout where the worktree agent runs. Defaults to "
            "<worktree-root>/<base-branch>."
        ),
    )
    parser.add_argument("--worktree-root", type=Path)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(os.getenv("DISPATCHER_STATE_FILE", DEFAULT_STATE_FILE)),
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(os.getenv("DISPATCHER_LOG_DIR", DEFAULT_LOG_DIR)),
    )
    parser.add_argument(
        "--worktree-command",
        default=os.getenv("DISPATCHER_WORKTREE_COMMAND", default_worktree_command()),
    )
    parser.add_argument(
        "--plan-command",
        default=os.getenv("DISPATCHER_PLAN_COMMAND", default_plan_command()),
    )
    parser.add_argument(
        "--build-command",
        default=os.getenv("DISPATCHER_BUILD_COMMAND", default_build_command()),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write stage commands to logs without running agents.",
    )
    parser.add_argument(
        "--poll-interval",
        type=positive_float,
        default=os.getenv(
            "DISPATCHER_POLL_INTERVAL_SECONDS",
            str(DEFAULT_POLL_INTERVAL_SECONDS),
        ),
        help="Seconds to wait between polling cycles. Defaults to 120.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Run one polling cycle and exit instead of long polling.",
    )
    mode_group.add_argument(
        "--daemon",
        action="store_true",
        help="Run as an async daemon with a concurrent worker queue.",
    )
    parser.add_argument(
        "--max-workers",
        type=positive_int,
        default=3,
        help="Maximum concurrent pipelines in daemon mode. Defaults to 3.",
    )
    args = parser.parse_args(argv)

    dispatcher_dir = Path.cwd().resolve()
    repo_name = repo_name_from_full_name(args.repo)
    worktree_root = (
        args.worktree_root
        or default_worktree_root(dispatcher_dir, repo_name, args.base_branch)
    ).resolve()
    project_dir = (args.project_dir or worktree_root / args.base_branch).resolve()
    state_file = (
        args.state_file
        if args.state_file.is_absolute()
        else dispatcher_dir / args.state_file
    )
    log_dir = (
        args.log_dir if args.log_dir.is_absolute() else dispatcher_dir / args.log_dir
    )

    return Config(
        repo=args.repo,
        label=args.label,
        base_branch=args.base_branch,
        branch_prefix=args.branch_prefix,
        paths=Paths(
            project_dir=project_dir,
            worktree_root=worktree_root,
            state_file=state_file.resolve(),
            log_dir=log_dir.resolve(),
        ),
        commands=Commands(
            worktree=args.worktree_command,
            plan=args.plan_command,
            build=args.build_command,
        ),
        dry_run=args.dry_run,
        poll_interval_seconds=args.poll_interval,
        once=args.once,
        daemon=args.daemon,
        max_workers=args.max_workers,
    )
