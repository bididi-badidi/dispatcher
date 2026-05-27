from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from dispatcher.background import BackgroundUploader


class FakeUploader:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def upload_stage_log(
        self, repo: str, issue_number: int, stage: str, path: Path
    ) -> None:
        self.calls.append((threading.get_ident(), stage))

    def upload_issue_log(
        self, repo: str, issue_number: int, stage_paths: list[Path]
    ) -> None:
        self.calls.append((threading.get_ident(), "issue"))


class BackgroundUploaderTests(unittest.TestCase):
    def test_submit_stage_upload_runs_in_thread(self) -> None:
        uploader = FakeUploader()
        background = BackgroundUploader(max_workers=1)
        test_thread_id = threading.get_ident()
        try:
            future = background.submit_stage_upload(
                uploader, "example/repo", 1, "plan", Path("plan.log")
            )
            future.result(timeout=2)
        finally:
            background.shutdown()

        self.assertEqual(uploader.calls[0][1], "plan")
        self.assertNotEqual(uploader.calls[0][0], test_thread_id)

    def test_failed_upload_is_logged_not_raised(self) -> None:
        class FailingUploader(FakeUploader):
            def upload_stage_log(
                self, repo: str, issue_number: int, stage: str, path: Path
            ) -> None:
                raise RuntimeError("boom")

        background = BackgroundUploader(max_workers=1)
        try:
            with self.assertLogs("dispatcher.s3_logs", level="WARNING") as logs:
                future = background.submit_stage_upload(
                    FailingUploader(), "example/repo", 1, "plan", Path("plan.log")
                )
                with self.assertRaises(RuntimeError):
                    future.result(timeout=2)
        finally:
            background.shutdown()

        self.assertIn("S3 log upload failed", logs.output[0])

    def test_shutdown_waits_for_in_flight_uploads(self) -> None:
        completed_at: list[float] = []

        class SlowUploader(FakeUploader):
            def upload_issue_log(
                self, repo: str, issue_number: int, stage_paths: list[Path]
            ) -> None:
                time.sleep(0.05)
                completed_at.append(time.monotonic())

        background = BackgroundUploader(max_workers=1)
        background.submit_issue_upload(SlowUploader(), "example/repo", 1, [])
        background.shutdown(wait=True)
        shutdown_returned_at = time.monotonic()

        self.assertTrue(completed_at)
        self.assertLessEqual(completed_at[0], shutdown_returned_at)
