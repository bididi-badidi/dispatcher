from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.async_runners import async_run_stage
from dispatcher.models import Config, Issue
from dispatcher.runners import AgentRunner
from tests.helpers import make_config


class FakeRunner(AgentRunner):
    stage_name = "plan"
    executable = "fake"

    def cwd(self, config: Config, worktree: Path) -> Path:
        return worktree

    def command(self, prompt: str, cwd: Path) -> list[str]:
        return ["fake", prompt]

    def stdin(self, prompt: str) -> str:
        return prompt

    def version(self) -> str:
        return "fake 1.0"


class FakeProcess:
    returncode = 0

    def __init__(self, expected_input: bytes, stdout: bytes, stderr: bytes) -> None:
        self.expected_input = expected_input
        self.stdout = stdout
        self.stderr = stderr

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        if input != self.expected_input:
            raise AssertionError(f"unexpected input: {input!r}")
        return self.stdout, self.stderr


class AsyncRunnerTests(unittest.TestCase):
    def test_async_stage_uses_locale_encoding_for_process_io(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = make_config(worktree, dry_run=False)
                runner = FakeRunner("hello")
                stdout = "done".encode("utf-16-le")
                stderr = "warn".encode("utf-16-le")
                proc = FakeProcess("hello".encode("utf-16-le"), stdout, stderr)

                with (
                    patch(
                        "dispatcher.async_runners.locale.getpreferredencoding",
                        return_value="utf-16-le",
                    ),
                    patch(
                        "dispatcher.async_runners.asyncio.create_subprocess_exec",
                        return_value=proc,
                    ),
                ):
                    await async_run_stage(
                        "plan",
                        runner,
                        Issue(1, "Title", "https://example.test/1"),
                        config,
                        worktree,
                        "feat/issue-1",
                    )

                log_path = (
                    config.paths.log_dir / "example" / "repo" / "issue-1-plan.log"
                )
                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("[stdout]\ndone", log_text)
                self.assertIn("[stderr]\nwarn", log_text)

        asyncio.run(scenario())
