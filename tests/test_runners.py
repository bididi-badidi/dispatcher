from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from dispatcher.constants import BANNED_AGENT_FLAGS
from dispatcher.git import codex_git_write_dirs
from dispatcher.models import Issue
from dispatcher.runners import (
    ClaudeReviewRunner,
    ClaudeRunner,
    CodexRunner,
    GeminiRunner,
    build_stage_runners,
)
from tests.helpers import make_config


class RunnerTests(unittest.TestCase):
    def test_agent_runner_prints_version_and_launch_commands_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            (worktree / ".git").mkdir()
            config = make_config(worktree, dry_run=False)
            runner = CodexRunner("build $issue_number")
            version = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="codex-cli 1.0", stderr=""
            )
            run = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

            with (
                patch("builtins.print") as print_,
                patch("dispatcher.runners.subprocess.run", side_effect=[version, run]),
            ):
                runner.run(
                    Issue(2, "Build", "https://example.test/2"),
                    config,
                    worktree,
                    "feat/issue-2",
                )

            self.assertEqual(
                [call.args[0] for call in print_.call_args_list],
                [
                    "$ codex --version",
                    "$ codex exec --sandbox workspace-write --config "
                    "sandbox_workspace_write.network_access=true "
                    f"--cd {worktree} 'build 2'",
                ],
            )

    def test_stage_runners_use_provider_specific_safe_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            worktree = root / "feat" / "issue-9"
            git_dir = root / "main" / ".git" / "worktrees" / "issue-9"
            git_dir.mkdir(parents=True)
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
            (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
            runners = build_stage_runners(config)

            gemini = runners["worktree"].command("make worktree", root)
            claude = runners["plan"].command("plan feature", worktree)
            codex = runners["build"].command("build feature", worktree)

            self.assertEqual(gemini[:3], ["gemini", "--approval-mode", "auto_edit"])
            self.assertIn("--allowed-tools", gemini)
            gemini_allowed_tools = gemini[gemini.index("--allowed-tools") + 1].split(
                ","
            )
            self.assertIn("activate_skill", gemini_allowed_tools)
            self.assertIn("list_directory", gemini_allowed_tools)
            self.assertIn("read_file", gemini_allowed_tools)
            self.assertIn("read_many_files", gemini_allowed_tools)
            self.assertIn("glob", gemini_allowed_tools)
            self.assertIn("grep_search", gemini_allowed_tools)
            self.assertIn("web_fetch", gemini_allowed_tools)
            self.assertIn("run_shell_command", gemini_allowed_tools)
            self.assertIn("run_shell_command(git)", gemini_allowed_tools)
            self.assertIn("run_shell_command(bash)", gemini_allowed_tools)
            self.assertIn("run_shell_command(ls)", gemini_allowed_tools)
            self.assertIn("run_shell_command(grep)", gemini_allowed_tools)
            self.assertNotIn("non_existent_tool", gemini_allowed_tools)
            self.assertNotIn("--sandbox", gemini)
            self.assertIn("--print", claude)
            self.assertIn("acceptEdits", claude)
            self.assertIn("--allowedTools", claude)
            self.assertIn("--disallowedTools", claude)
            claude_allowed_tools = claude[claude.index("--allowedTools") + 1].split(",")
            claude_disallowed_tools = claude[
                claude.index("--disallowedTools") + 1
            ].split(",")
            self.assertIn("Read", claude_allowed_tools)
            self.assertIn("Glob", claude_allowed_tools)
            self.assertIn("Grep", claude_allowed_tools)
            self.assertIn("Write(.ai/assets/branches/**)", claude_allowed_tools)
            self.assertIn("Edit(.ai/assets/branches/**)", claude_allowed_tools)
            self.assertIn("Bash(gh issue list *)", claude_allowed_tools)
            self.assertIn("Bash(gh issue view *)", claude_allowed_tools)
            self.assertIn("Bash(gh pr view *)", claude_allowed_tools)
            self.assertIn("Bash(gh pr diff *)", claude_allowed_tools)
            self.assertIn("Bash(gh repo view *)", claude_allowed_tools)
            self.assertIn("Bash(gh search issues *)", claude_allowed_tools)
            self.assertIn("Bash(git status *)", claude_allowed_tools)
            self.assertNotIn("Bash(gh api *)", claude_allowed_tools)
            self.assertNotIn("Bash(gh issue edit *)", claude_allowed_tools)
            self.assertNotIn("Write", claude_allowed_tools)
            self.assertNotIn("Edit", claude_allowed_tools)
            self.assertIn("Bash(gh issue edit *)", claude_disallowed_tools)
            self.assertIn("Bash(gh pr merge *)", claude_disallowed_tools)
            self.assertIn("Bash(gh api * -X POST *)", claude_disallowed_tools)
            self.assertIn("Bash(rm *)", claude_disallowed_tools)
            self.assertIn("Bash(git reset --hard *)", claude_disallowed_tools)
            self.assertIn("Bash(git push --force *)", claude_disallowed_tools)
            self.assertNotIn("plan feature", claude)
            self.assertEqual(runners["plan"].stdin("plan feature"), "plan feature")
            self.assertEqual(
                codex[:4], ["codex", "exec", "--sandbox", "workspace-write"]
            )
            codex_configs = [
                codex[index + 1]
                for index, value in enumerate(codex[:-1])
                if value == "--config"
            ]
            self.assertIn("sandbox_workspace_write.network_access=true", codex_configs)
            self.assertEqual(
                codex_configs[1],
                "sandbox_workspace_write.writable_roots="
                f'["{git_dir.resolve()}", "{(root / "main" / ".git").resolve()}"]',
            )
            codex_add_dirs = [
                codex[index + 1]
                for index, value in enumerate(codex[:-1])
                if value == "--add-dir"
            ]
            self.assertEqual(
                codex_add_dirs,
                [str(git_dir.resolve()), str((root / "main" / ".git").resolve())],
            )
            self.assertIn("--cd", codex)

            for command in [gemini, claude, codex]:
                self.assertFalse(BANNED_AGENT_FLAGS.intersection(command))

    def test_stage_runner_rejects_banned_automation_flags(self) -> None:
        runner = CodexRunner("prompt")

        with self.assertRaisesRegex(ValueError, "prohibited flag"):
            runner._validate_command(["codex", "exec", "--yolo", "prompt"])

    def test_gemini_runner_does_not_inherit_sandbox_environment(self) -> None:
        runner = GeminiRunner("prompt")

        with patch.dict(
            "os.environ",
            {
                "GEMINI_SANDBOX": "sandbox-exec",
                "SEATBELT_PROFILE": "permissive-open",
                "SANDBOX_FLAGS": "--anything",
                "PATH": "/bin",
            },
            clear=True,
        ):
            env = runner.env()

        self.assertEqual(env["PATH"], "/bin")
        self.assertNotIn("GEMINI_SANDBOX", env)
        self.assertNotIn("SEATBELT_PROFILE", env)
        self.assertNotIn("SANDBOX_FLAGS", env)

    def test_claude_runner_appends_plan_model_override(self) -> None:
        runner = ClaudeRunner("plan")
        issue = Issue(
            13,
            "Plan with Opus",
            "https://example.test/13",
            plan_model="claude-opus-4-7",
        )

        with self.assertLogs("dispatcher.runners", level="INFO") as logs:
            command = runner.command_for(issue, "plan feature", Path("/tmp/worktree"))

        self.assertEqual(command[-2:], ["--model", "claude-opus-4-7"])
        self.assertIn(
            "[planning] model escalated to claude-opus-4-7 (label: automate:opus)",
            logs.output[0],
        )

    def test_claude_runner_uses_default_model_when_issue_has_no_override(self) -> None:
        runner = ClaudeRunner("plan")
        issue = Issue(13, "Plan normally", "https://example.test/13")

        command = runner.command_for(issue, "plan feature", Path("/tmp/worktree"))

        self.assertNotIn("--model", command)

    def test_claude_review_runner_does_not_use_plan_model_override(self) -> None:
        runner = ClaudeReviewRunner("review")
        issue = Issue(
            13,
            "Review without Opus",
            "https://example.test/13",
            plan_model="claude-opus-4-7",
        )

        command = runner.command_for(issue, "review feature", Path("/tmp/worktree"))

        self.assertNotIn("--model", command)

    def test_codex_git_write_dirs_stay_empty_for_a_normal_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            (worktree / ".git").mkdir()

            self.assertEqual(codex_git_write_dirs(worktree), [])

    def test_stage_log_uploads_when_bucket_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            config = replace(
                make_config(worktree),
                s3_log_bucket="dispatcher-logs",
            )
            runner = GeminiRunner("worktree $issue_number")
            calls = []

            class FakeBackground:
                def submit_stage_upload(self, uploader, repo, issue, stage, path):
                    calls.append((uploader, repo, issue, stage, path))

            with (
                patch("dispatcher.runners.uploader_from_config", return_value=object()),
                patch(
                    "dispatcher.background.get_default_background",
                    return_value=FakeBackground(),
                ),
                patch.object(GeminiRunner, "version", return_value="gemini 1.0"),
            ):
                runner.run(
                    Issue(8, "Upload", "https://example.test/8"),
                    config,
                    worktree,
                    "feat/issue-8",
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:4], ("example/repo", 8, "worktree"))
        self.assertEqual(calls[0][4].name, "issue-8-worktree.log")

    def test_no_upload_when_bucket_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            config = make_config(worktree)
            runner = GeminiRunner("worktree $issue_number")

            with (
                patch("dispatcher.runners.uploader_from_config", return_value=None),
                patch("dispatcher.background.get_default_background") as background,
                patch.object(GeminiRunner, "version", return_value="gemini 1.0"),
            ):
                runner.run(
                    Issue(8, "Upload", "https://example.test/8"),
                    config,
                    worktree,
                    "feat/issue-8",
                )

        background.assert_not_called()
