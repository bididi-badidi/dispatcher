from __future__ import annotations

import asyncio
import locale
import shlex
from pathlib import Path

from dispatcher.models import Config, Issue
from dispatcher.runners import AgentRunner
from dispatcher.subprocess_utils import print_subprocess_command


async def async_run_stage(
    name: str,
    runner: AgentRunner,
    issue: Issue,
    config: Config,
    worktree: Path,
    branch: str,
) -> str:
    if runner.stage_name != name:
        raise ValueError(f"runner {runner.stage_name!r} cannot run {name!r}")

    prompt = runner.prompt(issue, config, worktree, branch)
    cwd = runner.cwd(config, worktree)
    command = runner.command_for(issue, prompt, cwd)
    runner._validate_command(command)

    if config.repo is None:
        raise RuntimeError("runner requires a concrete repository")
    repo_log_dir = config.paths.log_dir / config.repo
    repo_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = repo_log_dir / f"issue-{issue.number}-{runner.stage_name}.log"
    version = await asyncio.to_thread(runner.version)
    command_text = shlex.join(command)
    stdin_text = runner.stdin(prompt)
    stdin_log = f"\n\n[stdin]\n{stdin_text}" if stdin_text is not None else ""

    if config.dry_run:
        log_path.write_text(
            f"DRY RUN: {command_text}{stdin_log}\n\n[version]\n{version}\n",
            encoding="utf-8",
        )
        return ""

    print_subprocess_command(command)
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=runner.env(),
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    encoding = locale.getpreferredencoding(False)
    stdout, stderr = await proc.communicate(
        input=stdin_text.encode(encoding) if stdin_text is not None else None
    )
    stdout_text = stdout.decode(encoding, errors="replace")
    stderr_text = stderr.decode(encoding, errors="replace")
    log_path.write_text(
        f"$ {command_text}{stdin_log}\n\n[version]\n{version}\n\n[stdout]\n"
        f"{stdout_text}\n\n[stderr]\n{stderr_text}",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{runner.stage_name} stage failed with exit code "
            f"{proc.returncode}; see {log_path}"
        )
    return stdout_text
