from __future__ import annotations

import unittest

from dispatcher.prompts import (
    default_build_command,
    default_plan_command,
    default_worktree_command,
)


class PromptTests(unittest.TestCase):
    def test_default_worktree_prompt_describes_codex_worktree_task(self) -> None:
        self.assertEqual(
            default_worktree_command(),
            "Create a git worktree for GitHub issue #$issue_number "
            "($issue_title): from $project_dir, fetch origin $base_branch if needed, "
            "create $worktree using branch $branch based on $base_branch, then copy "
            "seed config files such as .env and .env.local from $project_dir into "
            "$worktree. Do not modify code.",
        )

    def test_default_plan_prompt_uses_branch_assets_and_code_wording(self) -> None:
        prompt = default_plan_command()

        self.assertIn("Read GitHub issue #$issue_number for this repo.", prompt)
        self.assertIn("under branch assets using the project instructions.", prompt)
        self.assertIn("Do not modify code.", prompt)
        self.assertNotIn("$repo", prompt)
        self.assertNotIn("$issue_url", prompt)
        self.assertNotIn("Do not implement code.", prompt)

    def test_default_build_prompt_reads_from_branch_assets(self) -> None:
        prompt = default_build_command()

        self.assertEqual(
            prompt,
            "Read the implementation plan from the branch assets for GitHub "
            "issue #$issue_number. implement it, run relevant checks, push "
            "commit to remote, and open a PR with the configured GitHub MCP "
            "when it is available. Do not require the gh CLI for PR creation. "
            "Stop after PR creation.",
        )
        self.assertNotIn("$branch", prompt)
