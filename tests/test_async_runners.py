from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dispatcher.async_runners import async_run_stage
from dispatcher.models import Config, Issue
from dispatcher.runners import AgentRunner, ClaudeRunner
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

    def version(self, *, debug: bool = False) -> str:
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


class FailingProcess:
    returncode = 1
    stdout = b"partial out"
    stderr = b"partial err"

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        raise RuntimeError("communicate exploded")


class StringFailingProcess:
    returncode = 1
    stdout = "partial snowman \u2603"
    stderr = "partial error \u2603"

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        raise RuntimeError("unicode communicate exploded")


class CancelledProcess:
    returncode = 1
    stdout = b"partial out"
    stderr = b"partial err"

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        raise asyncio.CancelledError()


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

    def test_async_stage_encodes_string_capture_safely_on_error(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = make_config(worktree, dry_run=False)
                runner = FakeRunner("hello")

                with patch(
                    "dispatcher.async_runners.asyncio.create_subprocess_exec",
                    return_value=StringFailingProcess(),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "unicode communicate exploded"
                    ):
                        await async_run_stage(
                            "plan",
                            runner,
                            Issue(11, "Crash", "https://example.test/11"),
                            config,
                            worktree,
                            "feat/issue-11",
                        )

                log_path = (
                    config.paths.log_dir / "example" / "repo" / "issue-11-plan.log"
                )
                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("[stdout]\npartial snowman", log_text)
                self.assertIn("[stderr]\npartial error", log_text)

        asyncio.run(scenario())

    def test_async_stage_propagates_cancellation_from_communicate(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = make_config(worktree, dry_run=False)
                runner = FakeRunner("hello")

                with patch(
                    "dispatcher.async_runners.asyncio.create_subprocess_exec",
                    return_value=CancelledProcess(),
                ):
                    with self.assertRaises(asyncio.CancelledError):
                        await async_run_stage(
                            "plan",
                            runner,
                            Issue(12, "Cancel", "https://example.test/12"),
                            config,
                            worktree,
                            "feat/issue-12",
                        )

        asyncio.run(scenario())

    def test_async_dry_run_uses_plan_model_override(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = make_config(worktree)
                runner = ClaudeRunner("plan $issue_number")
                issue = Issue(
                    13,
                    "Plan with Opus",
                    "https://example.test/13",
                    plan_model="claude-opus-4-7",
                )

                with patch.object(ClaudeRunner, "version", return_value="claude 1.0"):
                    await async_run_stage(
                        "plan",
                        runner,
                        issue,
                        config,
                        worktree,
                        "feat/issue-13",
                    )

                log_path = (
                    config.paths.log_dir / "example" / "repo" / "issue-13-plan.log"
                )
                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("--model claude-opus-4-7", log_text)

        asyncio.run(scenario())

    def test_async_stage_log_uploads_when_bucket_configured(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = replace(
                    make_config(worktree),
                    s3_log_bucket="dispatcher-logs",
                )
                runner = ClaudeRunner("plan $issue_number")
                calls = []

                class FakeBackground:
                    def submit_stage_upload(self, uploader, repo, issue, stage, path):
                        calls.append((repo, issue, stage, path))

                with (
                    patch(
                        "dispatcher.async_runners.uploader_from_config",
                        return_value=object(),
                    ),
                    patch(
                        "dispatcher.background.get_default_background",
                        return_value=FakeBackground(),
                    ),
                    patch.object(ClaudeRunner, "version", return_value="claude 1.0"),
                ):
                    await async_run_stage(
                        "plan",
                        runner,
                        Issue(9, "Upload", "https://example.test/9"),
                        config,
                        worktree,
                        "feat/issue-9",
                    )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:3], ("example/repo", 9, "plan"))
            self.assertEqual(calls[0][3].name, "issue-9-plan.log")

        asyncio.run(scenario())

    def test_async_stage_flushes_log_when_communicate_raises(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                worktree = Path(temp_dir)
                config = make_config(worktree, dry_run=False)
                runner = FakeRunner("hello")
                calls = []

                with (
                    patch(
                        "dispatcher.async_runners.asyncio.create_subprocess_exec",
                        return_value=FailingProcess(),
                    ),
                    patch(
                        "dispatcher.async_runners.write_stage_log_fallback",
                        side_effect=lambda *args: calls.append(args),
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "communicate exploded"):
                        await async_run_stage(
                            "plan",
                            runner,
                            Issue(10, "Crash", "https://example.test/10"),
                            config,
                            worktree,
                            "feat/issue-10",
                        )

                log_path = (
                    config.paths.log_dir / "example" / "repo" / "issue-10-plan.log"
                )
                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("[stdout]\npartial out", log_text)
                self.assertIn("[stderr]\npartial err", log_text)
                self.assertIn(
                    "[exception]\nRuntimeError: communicate exploded", log_text
                )
                self.assertEqual(len(calls), 1)

        asyncio.run(scenario())
