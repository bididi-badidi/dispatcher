"""Tests for the S3 -> CloudWatch Lambda handler.

Run from the repo root with:  pytest lambda/s3_to_cloudwatch/test_handler.py
"""

from __future__ import annotations

import gzip
import importlib
import io
import os

# handler.py reads LOG_GROUP_NAME at import time.
os.environ.setdefault("LOG_GROUP_NAME", "/test/group")
os.environ.pop("LOG_STREAM_NAME", None)

handler = importlib.import_module("handler")


class FakeS3:
    def __init__(self, body: bytes):
        self._body = body
        self.requested: tuple[str, str] | None = None

    def get_object(self, Bucket, Key):
        self.requested = (Bucket, Key)
        return {"Body": io.BytesIO(self._body)}


class FakeLogs:
    def __init__(self):
        self.created_groups: list[str] = []
        self.created_streams: list[str] = []
        self.batches: list[list[dict]] = []

    def create_log_group(self, logGroupName):
        self.created_groups.append(logGroupName)

    def create_log_stream(self, logGroupName, logStreamName):
        self.created_streams.append(logStreamName)

    def put_log_events(self, logGroupName, logStreamName, logEvents):
        self.batches.append(logEvents)


def _events(logs: FakeLogs) -> list[dict]:
    return [e for batch in logs.batches for e in batch]


def test_pushes_readable_multiline_log_chunk():
    s3 = FakeS3(b"line one\n\n  \nline two\n")
    logs = FakeLogs()

    count = handler.process_object(s3, logs, "bkt", "p/owner/repo/issue_42-build.log")

    assert count == 1
    messages = [e["message"] for e in _events(logs)]
    assert messages == ["[issue_42-build]\nline one\n\n  \nline two"]


def test_decompresses_gzip_and_strips_suffixes_in_label():
    s3 = FakeS3(gzip.compress(b"hello\n"))
    logs = FakeLogs()

    handler.process_object(s3, logs, "bkt", "owner/repo/issue_7-plan.log.gz")

    assert _events(logs)[0]["message"] == "[issue_7-plan]\nhello"


def test_creates_group_and_per_repo_stream():
    s3 = FakeS3(gzip.compress(b"x\n"))
    logs = FakeLogs()

    handler.process_object(s3, logs, "bkt", "owner/repo/issue_1-plan.log.gz")

    assert logs.created_groups == ["/test/group"]
    assert logs.created_streams == ["owner/repo"]


def test_repo_stream_ignores_optional_key_prefix():
    assert handler._stream_from_key("logs/owner/repo/issue_1-plan.log") == "owner/repo"


def test_empty_object_writes_nothing():
    s3 = FakeS3(b"   \n\n")
    logs = FakeLogs()

    assert handler.process_object(s3, logs, "bkt", "owner/repo/issue_9-build.log") == 0
    assert logs.batches == []
    assert logs.created_streams == []


def test_timestamps_are_monotonic():
    body = (
        f"{'a' * handler.MAX_MESSAGE_BYTES}\n"
        f"{'b' * handler.MAX_MESSAGE_BYTES}\n"
        f"{'c' * handler.MAX_MESSAGE_BYTES}\n"
    )
    s3 = FakeS3(body.encode())
    logs = FakeLogs()

    handler.process_object(s3, logs, "bkt", "owner/repo/issue_2-build.log")

    ts = [e["timestamp"] for e in _events(logs)]
    assert ts == sorted(ts)
    assert len(set(ts)) == 3


def test_oversized_line_is_truncated():
    big = "z" * (handler.MAX_MESSAGE_BYTES + 5_000)
    s3 = FakeS3((big + "\n").encode("utf-8"))
    logs = FakeLogs()

    handler.process_object(s3, logs, "bkt", "owner/repo/issue_3-build.log")

    msg = _events(logs)[0]["message"]
    assert len(msg.encode("utf-8")) <= handler.MAX_MESSAGE_BYTES


def test_multiline_log_splits_on_message_byte_limit():
    line = "z" * 100_000
    s3 = FakeS3(f"{line}\n{line}\n{line}\n".encode())
    logs = FakeLogs()

    count = handler.process_object(s3, logs, "bkt", "owner/repo/issue_4-build.log")

    assert count == 2
    messages = [e["message"] for e in _events(logs)]
    assert messages[0] == f"[issue_4-build]\n{line}\n{line}"
    assert messages[1] == f"[issue_4-build]\n{line}"


def test_batched_splits_on_byte_limit():
    # Each ~600 KB message -> only one fits per 1 MB batch.
    msg = "q" * 600_000
    events = [{"timestamp": i, "message": msg} for i in range(3)]
    batches = list(handler._batched(events))
    assert [len(b) for b in batches] == [1, 1, 1]


def test_batched_splits_on_count_limit():
    events = [
        {"timestamp": i, "message": "x"}
        for i in range(handler.MAX_EVENTS_PER_BATCH + 5)
    ]
    batches = list(handler._batched(events))
    assert [len(b) for b in batches] == [handler.MAX_EVENTS_PER_BATCH, 5]


def test_lambda_handler_processes_all_records(monkeypatch):
    pushed: list[tuple[str, str]] = []

    def fake_process(s3, logs, bucket, key):
        pushed.append((bucket, key))
        return 1

    monkeypatch.setattr(handler, "process_object", fake_process)

    event = {
        "Records": [
            {"s3": {"bucket": {"name": "b1"}, "object": {"key": "owner/repo/a.log"}}},
            {
                "s3": {
                    "bucket": {"name": "b2"},
                    "object": {"key": "owner/repo/b%2Bc.log"},
                }
            },
        ]
    }
    result = handler.lambda_handler(event, None)

    assert result == {"statusCode": 200, "eventsPushed": 2}
    # second key is URL-decoded ('%2B' -> '+').
    assert pushed == [("b1", "owner/repo/a.log"), ("b2", "owner/repo/b+c.log")]
