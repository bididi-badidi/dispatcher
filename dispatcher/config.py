from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Sequence

from dispatcher.constants import (
    DEFAULT_BASE_BRANCH,
    DEFAULT_BRANCH_PREFIX,
    DEFAULT_LABEL,
    DEFAULT_LOG_DIR,
    DEFAULT_OPUS_LABEL,
    DEFAULT_PLAN_OPUS_MODEL,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STATE_FILE,
)
from dispatcher.git import (
    default_projects_dir,
    default_worktree_root,
    repo_name_from_full_name,
)
from dispatcher.models import Commands, Config, Paths
from dispatcher.prompts import (
    default_build_command,
    default_plan_command,
    default_worktree_command,
)

ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def load_env_file(path: Path | None = None) -> None:
    env_path = path or resolve_root_dir() / ".env"
    if not env_path.is_file():
        return

    for line in env_path.read_text().splitlines():
        key_value = _parse_env_line(line)
        if key_value is None:
            continue

        key, value = key_value
        os.environ.setdefault(key, value)


def resolve_root_dir() -> Path:
    root_dir = os.getenv("DISPATCHER_ROOT_DIR")
    if root_dir:
        return Path(root_dir).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_projects_dir() -> Path:
    projects_dir = os.getenv("DISPATCHER_PROJECTS_DIR")
    if projects_dir:
        return Path(projects_dir).expanduser().resolve()
    return default_projects_dir().resolve()


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()

    key, separator, raw_value = stripped.partition("=")
    key = key.strip()
    if separator == "" or not ENV_KEY_PATTERN.match(key):
        return None

    return key, _parse_env_value(raw_value.strip())


def _parse_env_value(raw_value: str) -> str:
    if raw_value.startswith(("'", '"')):
        quote = raw_value[0]
        closing_index = raw_value.find(quote, 1)
        if closing_index != -1:
            return raw_value[1:closing_index]

    return _strip_inline_comment(raw_value).strip()


def _strip_inline_comment(value: str) -> str:
    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def build_config(argv: Sequence[str] | None = None) -> Config:
    load_env_file()

    parser = argparse.ArgumentParser(
        description="Run the local issue-triggered dispatcher happy path."
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

    dispatcher_dir = resolve_root_dir()
    repo = os.getenv("DISPATCHER_REPO")
    redis_url = os.getenv("DISPATCHER_REDIS_URL")
    opus_label = os.getenv("DISPATCHER_OPUS_LABEL", DEFAULT_OPUS_LABEL)
    opus_model = os.getenv("DISPATCHER_OPUS_MODEL", DEFAULT_PLAN_OPUS_MODEL)
    s3_log_bucket = os.getenv("AWS_S3_LOG_BUCKET", "").strip() or None
    s3_log_key_prefix = os.getenv("AWS_S3_LOG_KEY_PREFIX", "").strip()
    redis_poll_interval = positive_int(
        os.getenv("DISPATCHER_REDIS_POLL_INTERVAL", "60")
    )
    repo_name = repo_name_from_full_name(repo) if repo else dispatcher_dir.name
    projects_dir = resolve_projects_dir()
    worktree_root = (
        args.worktree_root or default_worktree_root(repo_name, projects_dir)
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

    config = Config(
        repo=repo,
        label=args.label,
        opus_label=opus_label,
        opus_model=opus_model,
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
        redis_url=redis_url,
        redis_poll_interval=redis_poll_interval,
        once=args.once,
        daemon=args.daemon,
        max_workers=args.max_workers,
        s3_log_bucket=s3_log_bucket,
        s3_log_key_prefix=s3_log_key_prefix,
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    if config.redis_url is None and config.repo is None:
        raise SystemExit(
            "error: set DISPATCHER_REDIS_URL (Redis mode) "
            "or DISPATCHER_REPO (single-repo fallback)"
        )
