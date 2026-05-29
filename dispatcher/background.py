from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from dispatcher.s3_logs import S3LogUploader

LOGGER = logging.getLogger("dispatcher.s3_logs")


class BackgroundUploader:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="dispatcher-s3"
        )

    def submit_stage_upload(
        self,
        uploader: S3LogUploader,
        repo: str,
        issue_number: int,
        stage: str,
        path: Path,
    ) -> Future[None]:
        future = self._executor.submit(
            uploader.upload_stage_log, repo, issue_number, stage, path
        )
        future.add_done_callback(_log_upload_failure)
        return future

    def submit_issue_upload(
        self,
        uploader: S3LogUploader,
        repo: str,
        issue_number: int,
        stage_paths: list[Path],
    ) -> Future[None]:
        future = self._executor.submit(
            uploader.upload_issue_log, repo, issue_number, stage_paths
        )
        future.add_done_callback(_log_upload_failure)
        return future

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


_default_background: BackgroundUploader | None = None


def get_default_background() -> BackgroundUploader:
    global _default_background
    if _default_background is None:
        _default_background = BackgroundUploader()
    return _default_background


def shutdown_default_background(wait: bool = True) -> None:
    global _default_background
    if _default_background is None:
        return
    _default_background.shutdown(wait=wait)
    _default_background = None


def _log_upload_failure(future: Future[None]) -> None:
    try:
        future.result()
    except Exception as exc:
        LOGGER.warning("S3 log upload failed: %s", exc)
