from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Sequence


DEFAULT_STATE_FILE = ".dispatcher/state.json"
DEFAULT_LOG_DIR = ".dispatcher/logs"
DEFAULT_LABEL = "automate"
DEFAULT_BASE_BRANCH = "main"
DEFAULT_BRANCH_PREFIX = "feat/issue-"


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


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"issues": {}}
        with self.path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def get(self, issue_number: int) -> dict[str, Any] | None:
        return self.load()["issues"].get(str(issue_number))

    def upsert(self, state: IssueState) -> None:
        data = self.load()
        data.setdefault("issues", {})[str(state.number)] = asdict(state)
        self.save(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    return slug.strip("-") or "issue"


def run_json(command: Sequence[str], cwd: Path) -> Any:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout or "[]")


def list_triggered_issues(config: Config) -> list[Issue]:
    raw_issues = run_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            config.repo,
            "--label",
            config.label,
            "--state",
            "open",
            "--json",
            "number,title,url",
            "--limit",
            "20",
        ],
        cwd=config.paths.project_dir,
    )
    return [
        Issue(
            number=int(item["number"]),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
        )
        for item in raw_issues
    ]


def render_template(
    template: str, issue: Issue, config: Config, worktree: Path, branch: str
) -> str:
    values = {
        "base_branch": config.base_branch,
        "branch": branch,
        "issue_number": str(issue.number),
        "issue_title": issue.title,
        "issue_url": issue.url,
        "label": config.label,
        "project_dir": str(config.paths.project_dir),
        "repo": config.repo,
        "worktree": str(worktree),
    }
    return Template(template).safe_substitute(values)


def default_worktree_command() -> str:
    return (
        'gemini -p "Create a git worktree for GitHub issue #$issue_number '
        "($issue_title) from $project_dir at $worktree on branch $branch based on "
        "$base_branch. Use the repository git-worktree skill and copy gitignored "
        '.env files as required."'
    )


def default_plan_command() -> str:
    return (
        'claude -p "Read GitHub issue #$issue_number for $repo: $issue_url. '
        "Write the feature implementation plan into .assets/ in this worktree, "
        'using the project instructions. Do not implement code."'
    )


def default_build_command() -> str:
    return (
        'codex exec "Read the implementation plan in .assets/ for GitHub issue '
        "#$issue_number, implement it, run relevant checks, commit to $branch, "
        'push, and open a draft PR. Stop after PR creation."'
    )


def run_stage(
    name: str,
    template: str,
    issue: Issue,
    config: Config,
    worktree: Path,
    branch: str,
) -> None:
    command = render_template(template, issue, config, worktree, branch)
    config.paths.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.paths.log_dir / f"issue-{issue.number}-{name}.log"

    if config.dry_run:
        log_path.write_text(f"DRY RUN: {command}\n", encoding="utf-8")
        return

    cwd = config.paths.project_dir if name == "worktree" else worktree
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
    )
    log_path.write_text(
        f"$ {command}\n\n[stdout]\n{completed.stdout}\n\n[stderr]\n{completed.stderr}",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} stage failed with exit code {completed.returncode}; see {log_path}"
        )


def worktree_path_for_issue(config: Config, issue: Issue) -> Path:
    project_name = config.paths.project_dir.name
    return (
        config.paths.worktree_root
        / f"{project_name}-{issue.number}-{slugify(issue.title)[:40]}"
    )


def branch_for_issue(config: Config, issue: Issue) -> str:
    return f"{config.branch_prefix}{issue.number}"


def run_pipeline(issue: Issue, config: Config, store: StateStore) -> IssueState:
    existing = store.get(issue.number)
    if existing and existing.get("status") in {"started", "planned", "built", "failed"}:
        return IssueState(**existing)

    worktree = worktree_path_for_issue(config, issue)
    branch = branch_for_issue(config, issue)
    state = IssueState(
        number=issue.number,
        title=issue.title,
        url=issue.url,
        status="started",
        branch=branch,
        worktree=str(worktree),
        updated_at=utc_now(),
    )
    store.upsert(state)

    try:
        run_stage("worktree", config.commands.worktree, issue, config, worktree, branch)
        state.status = "worktree_created"
        state.updated_at = utc_now()
        store.upsert(state)

        run_stage("plan", config.commands.plan, issue, config, worktree, branch)
        state.status = "planned"
        state.updated_at = utc_now()
        store.upsert(state)

        run_stage("build", config.commands.build, issue, config, worktree, branch)
        state.status = "built"
        state.updated_at = utc_now()
        store.upsert(state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.updated_at = utc_now()
        store.upsert(state)
        raise

    return state


def first_unstarted_issue(issues: Sequence[Issue], store: StateStore) -> Issue | None:
    for issue in issues:
        existing = store.get(issue.number)
        if not existing:
            return issue
    return None


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
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
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
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    worktree_root = (args.worktree_root or project_dir.parent).resolve()
    state_file = (
        args.state_file
        if args.state_file.is_absolute()
        else project_dir / args.state_file
    )
    log_dir = args.log_dir if args.log_dir.is_absolute() else project_dir / args.log_dir

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
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = build_config(argv)
    store = StateStore(config.paths.state_file)
    issues = list_triggered_issues(config)
    issue = first_unstarted_issue(issues, store)
    if issue is None:
        print(f"No new open issues with label {config.label!r} in {config.repo}.")
        return 0

    state = run_pipeline(issue, config, store)
    print(
        f"Issue #{state.number} reached {state.status}: "
        f"branch={state.branch} worktree={state.worktree}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
