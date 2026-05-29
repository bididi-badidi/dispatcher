from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from dispatcher.constants import (
    BANNED_AGENT_FLAGS,
    CLAUDE_PLAN_ALLOWED_TOOLS,
    CLAUDE_PLAN_DISALLOWED_TOOLS,
    CLAUDE_REVIEW_ALLOWED_TOOLS,
    GEMINI_WORKTREE_ALLOWED_TOOLS,
)
from dispatcher.git import codex_git_write_dirs
from dispatcher.models import Config, Issue
from dispatcher.prompts import render_template
from dispatcher.s3_logs import uploader_from_config
from dispatcher.subprocess_utils import print_subprocess_command


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

    def command_for(self, issue: Issue, prompt: str, cwd: Path) -> list[str]:
        return self.command(prompt, cwd)

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
        command = self.command_for(issue, prompt, cwd)
        self._validate_command(command)

        if config.repo is None:
            raise RuntimeError("runner requires a concrete repository")
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
            _submit_stage_upload(config, issue.number, self.stage_name, log_path)
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
        _submit_stage_upload(config, issue.number, self.stage_name, log_path)
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

    def command_for(self, issue: Issue, prompt: str, cwd: Path) -> list[str]:
        command = self.command(prompt, cwd)
        if issue.plan_model:
            logging.getLogger(__name__).info(
                "[planning] model escalated to %s (label: automate:opus)",
                issue.plan_model,
            )
            command = [*command, "--model", issue.plan_model]
        return command

    def stdin(self, prompt: str) -> str:
        return prompt


class ClaudeReviewRunner(ClaudeRunner):
    stage_name = "review"

    def command_for(self, issue: Issue, prompt: str, cwd: Path) -> list[str]:
        return AgentRunner.command_for(self, issue, prompt, cwd)

    def command(self, prompt: str, cwd: Path) -> list[str]:
        return [
            self.executable,
            "--print",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ",".join(CLAUDE_REVIEW_ALLOWED_TOOLS),
            "--disallowedTools",
            ",".join(CLAUDE_PLAN_DISALLOWED_TOOLS),
        ]


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


class GeminiPrRunner(GeminiRunner):
    stage_name = "open_pr"

    def cwd(self, config: Config, worktree: Path) -> Path:
        return worktree


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


def _submit_stage_upload(
    config: Config, issue_number: int, stage_name: str, log_path: Path
) -> None:
    if config.repo is None:
        return
    uploader = uploader_from_config(config)
    if uploader is None:
        return

    from dispatcher.background import get_default_background

    get_default_background().submit_stage_upload(
        uploader, config.repo, issue_number, stage_name, log_path
    )
