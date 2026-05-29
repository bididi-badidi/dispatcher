from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.github import (
    TerminalPr,
    initial_review_cursor,
    list_merged_issues,
    list_prs_needing_review_response,
    list_terminal_prs,
    list_triggered_issues,
)
from dispatcher.models import Issue, IssueState
from dispatcher.state import StateStore
from dispatcher.time_utils import utc_now
from tests.helpers import make_config


class GitHubTests(unittest.TestCase):
    def test_list_triggered_issues_uses_gh_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 3,
                        "title": "Ship it",
                        "url": "https://example.test/3",
                        "labels": [{"name": "automate"}],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(issues, [Issue(3, "Ship it", "https://example.test/3")])
            command = run_json.call_args.args[0]
            self.assertIn("--label", command)
            self.assertIn("automate", command)
            self.assertIn("owner/repo", command)
            self.assertIn("number,title,url,labels", command)

    def test_list_triggered_issues_sets_plan_model_for_opus_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 4,
                        "title": "Plan with Opus",
                        "url": "https://example.test/4",
                        "labels": [
                            {"name": "automate"},
                            {"name": "automate:opus"},
                        ],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(
                issues,
                [
                    Issue(
                        4,
                        "Plan with Opus",
                        "https://example.test/4",
                        plan_model="claude-opus-4-7",
                    )
                ],
            )

    def test_list_triggered_issues_requires_trigger_label_for_plan_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 5,
                        "title": "Missing trigger",
                        "url": "https://example.test/5",
                        "labels": [{"name": "automate:opus"}],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertIsNone(issues[0].plan_model)

    def test_list_triggered_issues_supports_custom_opus_label_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(
                make_config(root),
                opus_label="needs-opus",
                opus_model="claude-opus-4-5",
            )
            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = [
                    {
                        "number": 6,
                        "title": "Custom escalation",
                        "url": "https://example.test/6",
                        "labels": [
                            {"name": "automate"},
                            {"name": "needs-opus"},
                        ],
                    }
                ]

                issues = list_triggered_issues(config, "owner/repo")

            self.assertEqual(issues[0].plan_model, "claude-opus-4-5")

    def test_list_prs_needing_review_response_uses_review_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=7,
                    title="Fix comments",
                    url="https://example.test/7",
                    status="pr_opened",
                    branch="feat/issue-7",
                    worktree="/tmp/seven",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/42",
                    pr_review_cursor=10,
                    pr_issue_comment_cursor=0,
                    pr_review_comment_cursor=0,
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [
                    [
                        {
                            "id": 10,
                            "state": "CHANGES_REQUESTED",
                            "body": "Old feedback",
                            "user": {"login": "sam"},
                        },
                        {
                            "id": 11,
                            "state": "COMMENTED",
                            "body": "FYI",
                            "user": {"login": "sam"},
                        },
                        {
                            "id": 12,
                            "state": "CHANGES_REQUESTED",
                            "body": "Please add tests.",
                            "user": {"login": "lee"},
                        },
                    ],
                    [],
                    [],
                ]

                pending = list_prs_needing_review_response(config, "owner/repo", store)

            self.assertEqual(len(pending), 1)
            issue, feedback, cursors = pending[0]
            self.assertEqual(issue, Issue(7, "Fix comments", "https://example.test/7"))
            self.assertIn("Please add tests.", feedback)
            self.assertNotIn("Old feedback", feedback)
            self.assertEqual(cursors, (12, 0, 0))
            self.assertEqual(
                [call.args[0] for call in run_json.call_args_list],
                [
                    ["gh", "api", "repos/owner/repo/pulls/42/reviews"],
                    ["gh", "api", "repos/owner/repo/issues/42/comments"],
                    ["gh", "api", "repos/owner/repo/pulls/42/comments"],
                ],
            )

    def test_list_prs_needing_review_response_includes_pr_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=9,
                    title="Address PR comments",
                    url="https://example.test/9",
                    status="pr_opened",
                    branch="feat/issue-9",
                    worktree="/tmp/nine",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/44",
                    pr_review_cursor=20,
                    pr_issue_comment_cursor=20,
                    pr_review_comment_cursor=20,
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [
                    [],
                    [
                        {
                            "id": 21,
                            "body": "Please rename this for clarity.",
                            "user": {"login": "lee"},
                        }
                    ],
                    [
                        {
                            "id": 22,
                            "body": "This branch needs a regression test.",
                            "user": {"login": "sam"},
                            "path": "dispatcher/github.py",
                            "line": 72,
                        }
                    ],
                ]

                pending = list_prs_needing_review_response(config, "owner/repo", store)

            self.assertEqual(len(pending), 1)
            issue, feedback, cursors = pending[0]
            self.assertEqual(
                issue, Issue(9, "Address PR comments", "https://example.test/9")
            )
            self.assertIn("PR comment #21 by lee", feedback)
            self.assertIn("Please rename this for clarity.", feedback)
            self.assertIn(
                "Inline comment #22 by sam on dispatcher/github.py:72", feedback
            )
            self.assertIn("This branch needs a regression test.", feedback)
            self.assertEqual(cursors, (20, 21, 22))

    def test_list_prs_needing_review_response_detects_low_id_review_after_high_id_comment(
        self,
    ) -> None:
        """Regression: per-endpoint cursors prevent cross-namespace ID pollution.

        A review comment in /pulls/{pr}/comments (id=5000) must not shadow a
        subsequent formal review in /pulls/{pr}/reviews (id=101) even though
        101 < 5000.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=11,
                    title="Cross-namespace test",
                    url="https://example.test/11",
                    status="pr_opened",
                    branch="feat/issue-11",
                    worktree="/tmp/eleven",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/50",
                    pr_review_cursor=100,
                    pr_issue_comment_cursor=0,
                    pr_review_comment_cursor=5000,
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [
                    [
                        {
                            "id": 101,
                            "state": "CHANGES_REQUESTED",
                            "body": "Second review.",
                            "user": {"login": "alice"},
                        }
                    ],
                    [],
                    [],
                ]

                pending = list_prs_needing_review_response(config, "owner/repo", store)

            self.assertEqual(len(pending), 1)
            _, feedback, cursors = pending[0]
            self.assertIn("Second review.", feedback)
            self.assertEqual(cursors, (101, 0, 5000))

    def test_list_prs_needing_review_response_skips_missing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=10,
                    title="Legacy PR",
                    url="https://example.test/10",
                    status="pr_opened",
                    branch="feat/issue-10",
                    worktree="/tmp/ten",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/45",
                    pr_review_cursor=None,
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                pending = list_prs_needing_review_response(config, "owner/repo", store)

            self.assertEqual(pending, [])
            run_json.assert_not_called()

    def test_initial_review_cursor_returns_per_endpoint_max(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [
                    [{"id": 14}, {"id": "18"}],
                    [{"id": 16}, {"id": None}],
                    [{"id": "not-an-int"}, {"id": 20}],
                ]

                cursors = initial_review_cursor(config, "owner/repo", "45")

            self.assertEqual(cursors, (18, 16, 20))
            self.assertEqual(
                [call.args[0] for call in run_json.call_args_list],
                [
                    ["gh", "api", "repos/owner/repo/pulls/45/reviews"],
                    ["gh", "api", "repos/owner/repo/issues/45/comments"],
                    ["gh", "api", "repos/owner/repo/pulls/45/comments"],
                ],
            )

    def test_initial_review_cursor_returns_zero_per_endpoint_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [[], [], []]

                cursors = initial_review_cursor(config, "owner/repo", "45")

            self.assertEqual(cursors, (0, 0, 0))

    def test_list_prs_needing_review_response_picks_up_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=12,
                    title="Exhausted retries",
                    url="https://example.test/12",
                    status="failed",
                    branch="feat/issue-12",
                    worktree="/tmp/twelve",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/50",
                    pr_review_cursor=0,
                    pr_issue_comment_cursor=100,
                    pr_review_comment_cursor=0,
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.side_effect = [
                    [],
                    [{"id": 101, "body": "Please fix.", "user": {"login": "reviewer"}}],
                    [],
                ]

                pending = list_prs_needing_review_response(config, "owner/repo", store)

        self.assertEqual(len(pending), 1)
        _, feedback, cursors = pending[0]
        self.assertIn("Please fix.", feedback)
        self.assertEqual(cursors, (0, 101, 0))

    def test_list_merged_issues_checks_pr_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=8,
                    title="Merged work",
                    url="https://example.test/8",
                    status="pr_opened",
                    branch="feat/issue-8",
                    worktree="/tmp/eight",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/43",
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = {"state": "MERGED"}

                merged = list_merged_issues(config, "owner/repo", store)

            self.assertEqual(
                merged, [Issue(8, "Merged work", "https://example.test/8")]
            )
            self.assertEqual(
                run_json.call_args.args[0],
                [
                    "gh",
                    "pr",
                    "view",
                    "43",
                    "--repo",
                    "owner/repo",
                    "--json",
                    "state",
                ],
            )

    def test_list_terminal_prs_includes_closed_prs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            store = StateStore(config.paths.state_file)
            store.upsert(
                "owner/repo",
                IssueState(
                    number=15,
                    title="Closed work",
                    url="https://example.test/15",
                    status="pr_opened",
                    branch="feat/issue-15",
                    worktree="/tmp/fifteen",
                    updated_at=utc_now(),
                    pr_url="https://github.com/owner/repo/pull/51",
                ),
            )

            with patch("dispatcher.github.run_json") as run_json:
                run_json.return_value = {"state": "CLOSED"}

                terminal_prs = list_terminal_prs(config, "owner/repo", store)

            self.assertEqual(
                terminal_prs,
                [
                    TerminalPr(
                        Issue(15, "Closed work", "https://example.test/15"),
                        "closed",
                    )
                ],
            )
