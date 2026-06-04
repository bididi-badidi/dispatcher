from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from dispatcher.models import Config
from dispatcher.session_log import compose_rollup

CONTENT_TYPE = "text/plain; charset=utf-8"
CANONICAL_STAGE_ORDER = (
    "worktree",
    "plan",
    "build",
    "review_plan",
    "review_quality",
    "open_pr",
)


class S3UploadError(RuntimeError):
    """Raised when an S3 log upload fails."""


class S3LogUploader:
    def __init__(self, bucket: str, key_prefix: str = "", *, client=None) -> None:
        self.bucket = bucket
        self.key_prefix = _normalize_key_prefix(key_prefix)
        self._client = client

    @classmethod
    def from_env(cls) -> S3LogUploader | None:
        bucket = os.getenv("AWS_S3_LOG_BUCKET", "").strip()
        if not bucket:
            return None
        return cls(bucket, os.getenv("AWS_S3_LOG_KEY_PREFIX", ""))

    def is_enabled(self) -> bool:
        return bool(self.bucket)

    def upload_stage_log(
        self, repo: str, issue_number: int, stage: str, path: Path
    ) -> None:
        key = self._key(repo, f"issue_{issue_number}-{stage}.log")
        self._put_object(key, path.read_bytes())

    def upload_issue_log(
        self, repo: str, issue_number: int, stage_paths: Iterable[Path]
    ) -> None:
        key = self._key(repo, f"issue_{issue_number}.log")
        all_paths = list(stage_paths)
        stage_path_list = [
            path for path in all_paths if not _is_flow_log_path(path, issue_number)
        ]
        flow = issue_flow_log_path_from_stage_paths(all_paths, repo, issue_number)
        body = compose_rollup(
            flow.read_text(encoding="utf-8") if flow.is_file() else "",
            [
                (_stage_name_from_path(path, issue_number), path)
                for path in _sort_stage_paths(stage_path_list, issue_number)
            ],
        )
        self._put_object(key, body)

    def _key(self, repo: str, filename: str) -> str:
        return f"{self.key_prefix}{repo}/{filename}"

    def _put_object(self, key: str, body: bytes) -> None:
        try:
            self._s3_client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=CONTENT_TYPE,
            )
        except Exception as exc:
            raise S3UploadError(f"failed to upload S3 log {key!r}: {exc}") from exc

    def _s3_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client


def uploader_from_config(config: Config) -> S3LogUploader | None:
    bucket = (config.s3_log_bucket or "").strip()
    if not bucket:
        return None
    return _cached_uploader(bucket, config.s3_log_key_prefix)


def issue_stage_log_paths(log_dir: Path, repo: str, issue_number: int) -> list[Path]:
    repo_log_dir = log_dir / repo
    if not repo_log_dir.is_dir():
        return []
    return _sort_stage_paths(
        (
            path
            for path in repo_log_dir.glob(f"issue-{issue_number}-*.log")
            if not _is_flow_log_path(path, issue_number)
        ),
        issue_number,
    )


def issue_flow_log_path(log_dir: Path, repo: str, issue_number: int) -> Path:
    return log_dir / repo / f"issue-{issue_number}-flow.log"


def issue_flow_log_path_from_stage_paths(
    stage_paths: Iterable[Path], repo: str, issue_number: int
) -> Path:
    for path in stage_paths:
        return path.parent / f"issue-{issue_number}-flow.log"
    return Path(repo) / f"issue-{issue_number}-flow.log"


@lru_cache(maxsize=8)
def _cached_uploader(bucket: str, key_prefix: str) -> S3LogUploader:
    return S3LogUploader(bucket, key_prefix)


def _normalize_key_prefix(key_prefix: str) -> str:
    stripped = key_prefix.strip().strip("/")
    return f"{stripped}/" if stripped else ""


def _sort_stage_paths(paths: Iterable[Path], issue_number: int) -> list[Path]:
    return sorted(
        paths, key=lambda path: (_stage_sort_key(path, issue_number), path.name)
    )


def _stage_sort_key(path: Path, issue_number: int) -> int:
    stage = _stage_name_from_path(path, issue_number)
    try:
        return CANONICAL_STAGE_ORDER.index(stage)
    except ValueError:
        return len(CANONICAL_STAGE_ORDER)


def _stage_name_from_path(path: Path, issue_number: int) -> str:
    prefix = f"issue-{issue_number}-"
    name = path.name
    if name.startswith(prefix) and name.endswith(".log"):
        return name[len(prefix) : -len(".log")]
    return path.stem


def _is_flow_log_path(path: Path, issue_number: int) -> bool:
    return path.name == f"issue-{issue_number}-flow.log"
