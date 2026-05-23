from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
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
BANNED_AGENT_FLAGS = {
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-skip-permissions",
    "--full-auto",
    "--yolo",
    "-y",
}
GEMINI_WORKTREE_ALLOWED_TOOLS = (
    "activate_skill",
    "list_directory",
    "read_file",
    "read_many_files",
    "glob",
    "grep_search",
    "web_fetch",
    "run_shell_command",
    "run_shell_command(bash)",
    "run_shell_command(bun)",
    "run_shell_command(cp)",
    "run_shell_command(dirname)",
    "run_shell_command(find)",
    "run_shell_command(git)",
    "run_shell_command(grep)",
    "run_shell_command(ls)",
    "run_shell_command(mkdir)",
    "run_shell_command(npm)",
    "run_shell_command(pnpm)",
    "run_shell_command(pwd)",
    "run_shell_command(rsync)",
    "run_shell_command(sh)",
    "run_shell_command(test)",
    "run_shell_command(yarn)",
)
CLAUDE_PLAN_ALLOWED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "Write(.ai/assets/branches/**)",
    "Edit(.ai/assets/branches/**)",
    "MultiEdit(.ai/assets/branches/**)",
    "Bash(gh issue list *)",
    "Bash(gh issue view *)",
    "Bash(gh pr checks *)",
    "Bash(gh pr diff *)",
    "Bash(gh pr list *)",
    "Bash(gh pr status *)",
    "Bash(gh pr view *)",
    "Bash(gh repo list *)",
    "Bash(gh repo view *)",
    "Bash(gh search code *)",
    "Bash(gh search commits *)",
    "Bash(gh search issues *)",
    "Bash(gh search prs *)",
    "Bash(gh search repos *)",
    "Bash(git branch *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(git ls-files *)",
    "Bash(git status *)",
    "Bash(find *)",
    "Bash(ls *)",
    "Bash(pwd)",
)
CLAUDE_PLAN_DISALLOWED_TOOLS = (
    "Bash(chmod *)",
    "Bash(chown *)",
    "Bash(dd *)",
    "Bash(dropdb *)",
    "Bash(gh api * --method DELETE *)",
    "Bash(gh api * --method PATCH *)",
    "Bash(gh api * --method POST *)",
    "Bash(gh api * -X DELETE *)",
    "Bash(gh api * -X PATCH *)",
    "Bash(gh api * -X POST *)",
    "Bash(gh issue close *)",
    "Bash(gh issue comment *)",
    "Bash(gh issue create *)",
    "Bash(gh issue delete *)",
    "Bash(gh issue develop *)",
    "Bash(gh issue edit *)",
    "Bash(gh issue lock *)",
    "Bash(gh issue pin *)",
    "Bash(gh issue reopen *)",
    "Bash(gh issue transfer *)",
    "Bash(gh pr close *)",
    "Bash(gh pr comment *)",
    "Bash(gh pr create *)",
    "Bash(gh pr edit *)",
    "Bash(gh pr lock *)",
    "Bash(gh pr merge *)",
    "Bash(gh pr ready *)",
    "Bash(gh pr reopen *)",
    "Bash(gh pr review *)",
    "Bash(git branch -D *)",
    "Bash(git branch --delete --force *)",
    "Bash(git clean *)",
    "Bash(git push --delete *)",
    "Bash(git push --force *)",
    "Bash(git push --force-with-lease *)",
    "Bash(git push -f *)",
    "Bash(git reset --hard *)",
    "Bash(kubectl delete *)",
    "Bash(mv *)",
    "Bash(psql *DROP*)",
    "Bash(rm *)",
    "Bash(rsync --delete *)",
)


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
            return {"repositories": {}}
        with self.path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def get(self, repo: str, issue_number: int) -> dict[str, Any] | None:
        repositories = self.load().get("repositories", {})
        return repositories.get(repo, {}).get("issues", {}).get(str(issue_number))

    def upsert(self, repo: str, state: IssueState) -> None:
        data = self.load()
        repository = data.setdefault("repositories", {}).setdefault(repo, {})
        repository.setdefault("issues", {})[str(state.number)] = asdict(state)
        self.save(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def print_subprocess_command(command: Sequence[str]) -> None:
    print(f"$ {shlex.join(command)}")


def run_json(command: Sequence[str], cwd: Path) -> Any:
    print_subprocess_command(command)
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
        "Create a git worktree for GitHub issue #$issue_number "
        "($issue_title) based on $base_branch at $worktree using branch $branch."
    )


def default_plan_command() -> str:
    return (
        "Read GitHub issue #$issue_number for this repo. Save the feature "
        "implementation plan under branch assets using the project "
        "instructions. Do not modify code."
    )


def default_build_command() -> str:
    return (
        "Read the implementation plan from the branch assets for GitHub issue "
        "#$issue_number. implement it, run relevant checks, push commit to "
        "remote, and open a PR with the configured GitHub MCP when it is "
        "available. Do not require the gh CLI for PR creation. Stop after PR "
        "creation."
    )


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


class AgentRunner(ABC):
    stage_name: str
    executable: str
    version_args: Sequence[str] = ("--version",)

    def __init__(self, prompt_template: str) -> None:
        self.prompt_template = prompt_template

    def prompt(self, issue: Issue, config: Config, worktree: Path, branch: str) -> str:
        return render_template(self.prompt_template, issue, config, worktree, branch)

    @abstractmethod
    def cwd(self, config: Config, worktree: Path) -> Path:
        """Return the process working directory for this provider stage."""

    @abstractmethod
    def command(self, prompt: str, cwd: Path) -> list[str]:
        """Build the provider CLI argv for this provider stage."""

    def env(self) -> dict[str, str] | None:
        return None

    def stdin(self, prompt: str) -> str | None:
        return None

    def version(self) -> str:
        try:
            command = [self.executable, *self.version_args]
            print_subprocess_command(command)
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"unavailable ({exc})"

        output = (completed.stdout or completed.stderr).strip()
        return output or f"unknown (exit {completed.returncode})"

    def run(self, issue: Issue, config: Config, worktree: Path, branch: str) -> None:
        prompt = self.prompt(issue, config, worktree, branch)
        cwd = self.cwd(config, worktree)
        command = self.command(prompt, cwd)
        self._validate_command(command)

        repo_log_dir = config.paths.log_dir / config.repo
        repo_log_dir.mkdir(parents=True, exist_ok=True)
        log_path = repo_log_dir / f"issue-{issue.number}-{self.stage_name}.log"
        version = self.version()
        command_text = shlex.join(command)
        stdin_text = self.stdin(prompt)
        stdin_log = f"\n\n[stdin]\n{stdin_text}" if stdin_text is not None else ""

        if config.dry_run:
            log_path.write_text(
                f"DRY RUN: {command_text}{stdin_log}\n\n[version]\n{version}\n",
                encoding="utf-8",
            )
            return

        print_subprocess_command(command)
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=self.env(),
            input=stdin_text,
            text=True,
            capture_output=True,
        )
        log_path.write_text(
            f"$ {command_text}{stdin_log}\n\n[version]\n{version}\n\n[stdout]\n"
            f"{completed.stdout}\n\n[stderr]\n{completed.stderr}",
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{self.stage_name} stage failed with exit code "
                f"{completed.returncode}; see {log_path}"
            )

    def _validate_command(self, command: Sequence[str]) -> None:
        used_banned_flags = sorted(BANNED_AGENT_FLAGS.intersection(command))
        if used_banned_flags:
            raise ValueError(
                f"{self.stage_name} runner uses prohibited flag(s): "
                f"{', '.join(used_banned_flags)}"
            )


class GeminiRunner(AgentRunner):
    stage_name = "worktree"
    executable = "gemini"

    def cwd(self, config: Config, worktree: Path) -> Path:
        return config.paths.project_dir

    def command(self, prompt: str, cwd: Path) -> list[str]:
        return [
            self.executable,
            "--approval-mode",
            "auto_edit",
            "--allowed-tools",
            ",".join(GEMINI_WORKTREE_ALLOWED_TOOLS),
            "--prompt",
            prompt,
        ]

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("GEMINI_SANDBOX", None)
        env.pop("SEATBELT_PROFILE", None)
        env.pop("SANDBOX_FLAGS", None)
        return env


class ClaudeRunner(AgentRunner):
    stage_name = "plan"
    executable = "claude"

    def cwd(self, config: Config, worktree: Path) -> Path:
        return worktree

    def command(self, prompt: str, cwd: Path) -> list[str]:
        return [
            self.executable,
            "--print",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ",".join(CLAUDE_PLAN_ALLOWED_TOOLS),
            "--disallowedTools",
            ",".join(CLAUDE_PLAN_DISALLOWED_TOOLS),
        ]

    def stdin(self, prompt: str) -> str:
        return prompt


class CodexRunner(AgentRunner):
    stage_name = "build"
    executable = "codex"

    def cwd(self, config: Config, worktree: Path) -> Path:
        return worktree

    def command(self, prompt: str, cwd: Path) -> list[str]:
        command = [
            self.executable,
            "exec",
            "--sandbox",
            "workspace-write",
            "--config",
            "sandbox_workspace_write.network_access=true",
        ]
        git_write_dirs = codex_git_write_dirs(cwd)
        if git_write_dirs:
            command.extend(
                [
                    "--config",
                    "sandbox_workspace_write.writable_roots="
                    f"{json.dumps([str(path) for path in git_write_dirs])}",
                ]
            )
        for git_write_dir in git_write_dirs:
            command.extend(["--add-dir", str(git_write_dir)])
        command.extend(
            [
                "--cd",
                str(cwd),
                prompt,
            ]
        )
        return command


def build_stage_runners(config: Config) -> dict[str, AgentRunner]:
    return {
        "worktree": GeminiRunner(config.commands.worktree),
        "plan": ClaudeRunner(config.commands.plan),
        "build": CodexRunner(config.commands.build),
    }


def run_stage(
    name: str,
    runner: AgentRunner,
    issue: Issue,
    config: Config,
    worktree: Path,
    branch: str,
) -> None:
    if runner.stage_name != name:
        raise ValueError(f"runner {runner.stage_name!r} cannot run {name!r}")
    runner.run(issue, config, worktree, branch)


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


def run_pipeline(issue: Issue, config: Config, store: StateStore) -> IssueState:
    existing = store.get(config.repo, issue.number)
    if existing and existing.get("status") in {"started", "planned", "built", "failed"}:
        return IssueState(**existing)

    worktree = worktree_path_for_issue(config, issue)
    branch = branch_for_issue(config, issue)
    runners = build_stage_runners(config)
    state = IssueState(
        number=issue.number,
        title=issue.title,
        url=issue.url,
        status="started",
        branch=branch,
        worktree=str(worktree),
        updated_at=utc_now(),
    )
    store.upsert(config.repo, state)

    try:
        run_stage("worktree", runners["worktree"], issue, config, worktree, branch)
        if not config.dry_run:
            require_worktree_path(worktree)
        state.status = "worktree_created"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)

        run_stage("plan", runners["plan"], issue, config, worktree, branch)
        state.status = "planned"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)

        run_stage("build", runners["build"], issue, config, worktree, branch)
        state.status = "built"
        state.updated_at = utc_now()
        store.upsert(config.repo, state)
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.updated_at = utc_now()
        store.upsert(config.repo, state)
        raise

    return state


def first_unstarted_issue(
    issues: Sequence[Issue], repo: str, store: StateStore
) -> Issue | None:
    for issue in issues:
        existing = store.get(repo, issue.number)
        if not existing:
            return issue
    return None


def repo_name_from_full_name(repo: str) -> str:
    return repo.rsplit("/", maxsplit=1)[-1]


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
    args = parser.parse_args(argv)

    dispatcher_dir = Path.cwd().resolve()
    repo_name = repo_name_from_full_name(args.repo)
    worktree_root = (args.worktree_root or dispatcher_dir.parent / repo_name).resolve()
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
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = build_config(argv)
    store = StateStore(config.paths.state_file)
    issues = list_triggered_issues(config)
    issue = first_unstarted_issue(issues, config.repo, store)
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
