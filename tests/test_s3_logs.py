from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.s3_logs import S3LogUploader, S3UploadError, issue_stage_log_paths


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, **kwargs) -> None:
        self.calls.append(kwargs)


class S3LogTests(unittest.TestCase):
    def test_from_env_disabled_when_bucket_unset_or_blank(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(S3LogUploader.from_env())

        with patch.dict("os.environ", {"AWS_S3_LOG_BUCKET": ""}, clear=True):
            self.assertIsNone(S3LogUploader.from_env())

    def test_from_env_enabled(self) -> None:
        with patch.dict("os.environ", {"AWS_S3_LOG_BUCKET": "logs"}, clear=True):
            uploader = S3LogUploader.from_env()

        self.assertIsNotNone(uploader)
        assert uploader is not None
        self.assertTrue(uploader.is_enabled())

    def test_upload_stage_log_key_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "stage.log"
            log_path.write_text("stage output", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", client=client)

            uploader.upload_stage_log("octocat/Hello-World", 42, "plan", log_path)

        self.assertEqual(
            client.calls[0]["Key"], "octocat/Hello-World/issue_42-plan.log"
        )
        self.assertEqual(client.calls[0]["Body"], b"stage output")

    def test_upload_issue_log_key_format_matches_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "issue-42-plan.log"
            log_path.write_text("plan", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", client=client)

            uploader.upload_issue_log("octocat/Hello-World", 42, [log_path])

        self.assertEqual(client.calls[0]["Key"], "octocat/Hello-World/issue_42.log")

    def test_upload_issue_log_concatenates_in_canonical_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            build = root / "issue-42-build.log"
            worktree = root / "issue-42-worktree.log"
            plan = root / "issue-42-plan.log"
            build.write_text("build", encoding="utf-8")
            worktree.write_text("worktree", encoding="utf-8")
            plan.write_text("plan", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", client=client)

            uploader.upload_issue_log(
                "octocat/Hello-World", 42, [build, plan, worktree]
            )

        body = client.calls[0]["Body"].decode("utf-8")
        self.assertLess(body.index("=== worktree ==="), body.index("=== plan ==="))
        self.assertLess(body.index("=== plan ==="), body.index("=== build ==="))
        self.assertIn("=== flow ===", body)
        self.assertIn("=== conversation ===", body)
        self.assertIn("=== raw ===", body)

    def test_upload_issue_log_uses_flow_and_sanitized_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = root / "issue-42-plan.log"
            flow = root / "issue-42-flow.log"
            plan.write_text(
                "$ plan\n\n[version]\n1\n\n[stdout]\n"
                "<thinking>private</thinking>\nAgent answer\n\n[stderr]\nerr",
                encoding="utf-8",
            )
            flow.write_text("\u2192 START\n\u21e5 END", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", client=client)

            uploader.upload_issue_log("octocat/Hello-World", 42, [plan])

        body = client.calls[0]["Body"].decode("utf-8")
        self.assertIn("=== flow ===\n\u2192 START\n\u21e5 END", body)
        conversation = body.split("=== conversation ===", 1)[1].split("=== raw ===", 1)[
            0
        ]
        raw = body.split("=== raw ===", 1)[1]
        self.assertIn("--- plan ---\nAgent answer", conversation)
        self.assertNotIn("private", conversation)
        self.assertIn("<thinking>private</thinking>", raw)

    def test_issue_stage_log_paths_excludes_flow_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_dir = root / "octocat" / "Hello-World"
            repo_dir.mkdir(parents=True)
            plan = repo_dir / "issue-42-plan.log"
            flow = repo_dir / "issue-42-flow.log"
            plan.write_text("plan", encoding="utf-8")
            flow.write_text("flow", encoding="utf-8")

            paths = issue_stage_log_paths(root, "octocat/Hello-World", 42)

        self.assertEqual(paths, [plan])

    def test_upload_issue_log_can_render_flow_only_rollup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            flow = Path(temp_dir) / "issue-42-flow.log"
            flow.write_text("\u2192 START\n\u21e5 FAILED [boom]", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", client=client)

            uploader.upload_issue_log("octocat/Hello-World", 42, [flow])

        body = client.calls[0]["Body"].decode("utf-8")
        self.assertIn("\u21e5 FAILED [boom]", body)
        self.assertIn("=== conversation ===\n=== raw ===", body)
        self.assertNotIn("=== flow ===\n=== flow ===", body)

    def test_key_prefix_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "issue-42-plan.log"
            log_path.write_text("plan", encoding="utf-8")
            client = FakeS3Client()
            uploader = S3LogUploader("bucket", "//dispatcher-prod//", client=client)

            uploader.upload_issue_log("octocat/Hello-World", 42, [log_path])

        self.assertEqual(
            client.calls[0]["Key"],
            "dispatcher-prod/octocat/Hello-World/issue_42.log",
        )

    def test_upload_failure_raises_s3uploaderror(self) -> None:
        class FailingClient:
            def put_object(self, **kwargs) -> None:
                raise RuntimeError("network down")

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "stage.log"
            log_path.write_text("stage output", encoding="utf-8")
            uploader = S3LogUploader("bucket", client=FailingClient())

            with self.assertRaisesRegex(S3UploadError, "failed to upload S3 log"):
                uploader.upload_stage_log("octocat/Hello-World", 42, "plan", log_path)
