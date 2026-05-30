from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_config
from dispatcher.s3_logs import (
    S3LogUploader,
    S3UploadError,
    write_issue_log_fallback,
    write_stage_log_fallback,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, **kwargs) -> None:
        self.calls.append(kwargs)


class S3LogTests(unittest.TestCase):
    def test_local_stage_fallback_copies_log_when_bucket_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            source = root / "source.log"
            source.write_text("stage output", encoding="utf-8")

            destination = write_stage_log_fallback(
                config, "octocat/Hello-World", 42, "plan", source
            )

            self.assertEqual(destination.name, "issue_42-plan.log")
            self.assertIn(".session_logs/octocat/Hello-World", str(destination))
            self.assertEqual(destination.read_text(encoding="utf-8"), "stage output")

    def test_local_issue_fallback_concatenates_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = make_config(root)
            worktree = root / "issue-42-worktree.log"
            plan = root / "issue-42-plan.log"
            worktree.write_text("worktree", encoding="utf-8")
            plan.write_text("plan", encoding="utf-8")

            destination = write_issue_log_fallback(
                config, "octocat/Hello-World", 42, [plan, worktree]
            )

            assert destination is not None
            body = destination.read_text(encoding="utf-8")
            self.assertIn("=== worktree ===\nworktree", body)
            self.assertIn("=== plan ===\nplan", body)
            self.assertLess(body.index("=== worktree ==="), body.index("=== plan ==="))

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
