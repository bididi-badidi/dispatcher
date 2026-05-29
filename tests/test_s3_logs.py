from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.s3_logs import S3LogUploader, S3UploadError


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
