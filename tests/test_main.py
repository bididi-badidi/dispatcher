from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class DispatcherTests(unittest.TestCase):
    def make_config(self, root: Path, *, dry_run: bool = True) -> main.Config:
        return main.Config(
            repo="example/repo",
            label="automate",
            base_branch="main",
            branch_prefix="feat/issue-",
            paths=main.Paths(
                project_dir=root,
                worktree_root=root.parent,
                state_file=root / ".dispatcher" / "state.json",
                log_dir=root / ".dispatcher" / "logs",
            ),
            commands=main.Commands(
                worktree="worktree $issue_number $worktree $branch",
                plan="plan $issue_number $worktree",
                build="build $issue_number $branch",
            ),
            dry_run=dry_run,
        )

    def test_first_unstarted_issue_skips_known_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = main.StateStore(root / "state.json")
            store.upsert(
                main.IssueState(
                    number=1,
                    title="Started",
                    url="https://example.test/1",
                    status="started",
                    branch="feat/issue-1",
                    worktree="/tmp/one",
                    updated_at=main.utc_now(),
                )
            )
            issue = main.first_unstarted_issue(
                [
                    main.Issue(1, "Started", "https://example.test/1"),
                    main.Issue(2, "New", "https://example.test/2"),
                ],
                store,
            )
            self.assertIsNotNone(issue)
            self.assertEqual(issue.number, 2)

    def test_default_worktree_prompt_is_minimal(self) -> None:
        self.assertEqual(
            main.default_worktree_command(),
            "Create a git worktree for GitHub issue #$issue_number "
            "($issue_title) based on main.",
        )

    def test_dry_run_pipeline_records_state_and_stage_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            main_checkout = repo_root / "main"
            main_checkout.mkdir(parents=True)
            config = self.make_config(main_checkout)
            config = main.Config(
                repo=config.repo,
                label=config.label,
                base_branch=config.base_branch,
                branch_prefix=config.branch_prefix,
                paths=main.Paths(
                    project_dir=main_checkout,
                    worktree_root=repo_root,
                    state_file=config.paths.state_file,
                    log_dir=config.paths.log_dir,
                ),
                commands=config.commands,
                dry_run=config.dry_run,
            )
            store = main.StateStore(config.paths.state_file)
            issue = main.Issue(7, "Build the thing", "https://example.test/7")

            state = main.run_pipeline(issue, config, store)

            self.assertEqual(state.status, "built")
            saved = json.loads(config.paths.state_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["issues"]["7"]["branch"], "feat/issue-7")
            self.assertEqual(
                saved["issues"]["7"]["worktree"],
                str(repo_root / "feat" / "issue-7"),
            )
            self.assertTrue((config.paths.log_dir / "issue-7-worktree.log").exists())
            self.assertTrue((config.paths.log_dir / "issue-7-plan.log").exists())
            self.assertTrue((config.paths.log_dir / "issue-7-build.log").exists())

    def test_build_config_defaults_to_repo_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher_dir = Path(temp_dir) / "dispatcher"
            dispatcher_dir.mkdir()
            with patch("pathlib.Path.cwd", return_value=dispatcher_dir):
                config = main.build_config(["--repo", "owner/target-repo"])

            repo_root = (dispatcher_dir.parent / "target-repo").resolve()
            self.assertEqual(config.paths.project_dir, repo_root / "main")
            self.assertEqual(config.paths.worktree_root, repo_root)
            self.assertEqual(
                main.worktree_path_for_issue(config, main.Issue(8, "Task", "url")),
                repo_root / "feat" / "issue-8",
            )
            self.assertEqual(
                config.paths.state_file,
                (dispatcher_dir / ".dispatcher" / "state.json").resolve(),
            )
            self.assertEqual(
                config.paths.log_dir,
                (dispatcher_dir / ".dispatcher" / "logs").resolve(),
            )

    def test_list_triggered_issues_uses_gh_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            with patch("main.run_json") as run_json:
                run_json.return_value = [
                    {"number": 3, "title": "Ship it", "url": "https://example.test/3"}
                ]

                issues = main.list_triggered_issues(config)

            self.assertEqual(
                issues, [main.Issue(3, "Ship it", "https://example.test/3")]
            )
            command = run_json.call_args.args[0]
            self.assertIn("--label", command)
            self.assertIn("automate", command)

    def test_stage_runners_use_provider_specific_safe_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self.make_config(root)
            worktree = root / "feat" / "issue-9"
            git_dir = root / "main" / ".git" / "worktrees" / "issue-9"
            git_dir.mkdir(parents=True)
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
            (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
            runners = main.build_stage_runners(config)

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
                self.assertFalse(main.BANNED_AGENT_FLAGS.intersection(command))

    def test_stage_runner_rejects_banned_automation_flags(self) -> None:
        runner = main.CodexRunner("prompt")

        with self.assertRaisesRegex(ValueError, "prohibited flag"):
            runner._validate_command(["codex", "exec", "--yolo", "prompt"])

    def test_codex_git_write_dirs_stay_empty_for_a_normal_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worktree = Path(temp_dir)
            (worktree / ".git").mkdir()

            self.assertEqual(main.codex_git_write_dirs(worktree), [])

    def test_gemini_runner_does_not_inherit_sandbox_environment(self) -> None:
        runner = main.GeminiRunner("prompt")

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

    def test_default_plan_prompt_uses_branch_assets_and_code_wording(self) -> None:
        prompt = main.default_plan_command()

        self.assertIn("Read GitHub issue #$issue_number for this repo.", prompt)
        self.assertIn("under branch assets using the project instructions.", prompt)
        self.assertIn("Do not modify code.", prompt)
        self.assertNotIn("$repo", prompt)
        self.assertNotIn("$issue_url", prompt)
        self.assertNotIn("Do not implement code.", prompt)

    def test_default_build_prompt_reads_from_branch_assets(self) -> None:
        prompt = main.default_build_command()

        self.assertEqual(
            prompt,
            "Read the implementation plan from the branch assets for GitHub "
            "issue #$issue_number. implement it, run relevant checks, push "
            "commit to remote, and open a draft PR. Stop after PR creation.",
        )
        self.assertNotIn("$branch", prompt)


if __name__ == "__main__":
    unittest.main()
