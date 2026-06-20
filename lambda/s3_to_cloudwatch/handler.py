"""S3-triggered Lambda that ships uploaded log files into CloudWatch Logs.

The dispatcher uploads stage/issue logs to S3 with keys shaped like
``{prefix}/{owner}/{repo}/issue_{N}-{stage}.log`` (optionally gzipped). This
function is invoked on ``s3:ObjectCreated:*`` events, reads each object, and
writes readable multi-line chunks to CloudWatch Logs.
"""

from __future__ import annotations

import gzip
import logging
import os
import time
from typing import Iterator
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

# CloudWatch PutLogEvents hard limits.
# https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutLogEvents.html
MAX_EVENTS_PER_BATCH = 10_000
MAX_BATCH_BYTES = 1_048_576
EVENT_OVERHEAD_BYTES = 26  # added by CloudWatch to each event's payload
MAX_MESSAGE_BYTES = 262_144 - EVENT_OVERHEAD_BYTES  # 256 KB per event

LOG_GROUP = os.environ["LOG_GROUP_NAME"]
# Optional: pin every upload to one stream. When unset, the stream name is
# derived from the S3 key as owner/repo.
LOG_STREAM_OVERRIDE = os.environ.get("LOG_STREAM_NAME") or None

s3_client = boto3.client("s3")
logs_client = boto3.client("logs")


def lambda_handler(event: dict, context) -> dict:
    records = event.get("Records", [])
    total = 0
    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        # S3 event keys are URL-encoded (spaces -> '+', etc.).
        key = unquote_plus(record["s3"]["object"]["key"])
        total += process_object(s3_client, logs_client, bucket, key)
    return {"statusCode": 200, "eventsPushed": total}


def process_object(s3, logs, bucket: str, key: str) -> int:
    """Read one S3 object and push readable chunks to CloudWatch."""
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()

    if key.endswith(".gz"):
        body = gzip.decompress(body)

    text = body.decode("utf-8", "replace")
    if not text.strip():
        LOGGER.info("No non-empty lines in s3://%s/%s; skipping", bucket, key)
        return 0

    label = _label_from_key(key)
    stream = LOG_STREAM_OVERRIDE or _stream_from_key(key)
    _ensure_stream(logs, LOG_GROUP, stream)

    base_ts = int(time.time() * 1000)
    events = [
        {"timestamp": base_ts + i, "message": message}
        for i, message in enumerate(_message_chunks(label, text))
    ]

    pushed = 0
    for batch in _batched(events):
        logs.put_log_events(
            logGroupName=LOG_GROUP,
            logStreamName=stream,
            logEvents=batch,
        )
        pushed += len(batch)

    LOGGER.info("Pushed %d events from s3://%s/%s -> %s", pushed, bucket, key, stream)
    return pushed


def _label_from_key(key: str) -> str:
    """``prefix/owner/repo/issue_42-build.log.gz`` -> ``issue_42-build``."""
    filename = key.split("/")[-1]
    for suffix in (".gz", ".log"):
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]
    return filename


def _stream_from_key(key: str) -> str:
    """Derive ``owner/repo`` from keys with optional prefixes."""
    parts = [part for part in key.split("/") if part]
    if len(parts) >= 3:
        stream = "/".join(parts[-3:-1])
    else:
        stream = key.replace(".gz", "").replace(".log", "")
    return stream.replace(":", "_").replace("*", "_")


def _message_chunks(label: str, text: str) -> Iterator[str]:
    """Group a log file into CloudWatch-sized multi-line messages."""
    header = f"[{label}]\n"
    max_body_bytes = MAX_MESSAGE_BYTES - len(header.encode("utf-8"))
    chunk_lines: list[str] = []
    chunk_bytes = 0

    for line in text.splitlines():
        line_bytes = len(line.encode("utf-8"))
        separator_bytes = 1 if chunk_lines else 0
        if chunk_lines and chunk_bytes + separator_bytes + line_bytes > max_body_bytes:
            yield header + "\n".join(chunk_lines)
            chunk_lines = []
            chunk_bytes = 0
            separator_bytes = 0

        if line_bytes > max_body_bytes:
            if chunk_lines:
                yield header + "\n".join(chunk_lines)
                chunk_lines = []
                chunk_bytes = 0
            yield _truncate(header + line)
            continue

        chunk_lines.append(line)
        chunk_bytes += separator_bytes + line_bytes

    if chunk_lines:
        yield header + "\n".join(chunk_lines)


def _truncate(message: str) -> str:
    encoded = message.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_BYTES:
        return message
    return encoded[:MAX_MESSAGE_BYTES].decode("utf-8", "ignore")


def _batched(events: list[dict]) -> Iterator[list[dict]]:
    """Yield batches within both the per-batch count and byte limits."""
    batch: list[dict] = []
    batch_bytes = 0
    for event in events:
        size = len(event["message"].encode("utf-8")) + EVENT_OVERHEAD_BYTES
        if batch and (
            len(batch) >= MAX_EVENTS_PER_BATCH or batch_bytes + size > MAX_BATCH_BYTES
        ):
            yield batch
            batch, batch_bytes = [], 0
        batch.append(event)
        batch_bytes += size
    if batch:
        yield batch


def _ensure_stream(logs, group: str, stream: str) -> None:
    """Create the log group and stream if they don't already exist."""
    _create_ignoring_exists(lambda: logs.create_log_group(logGroupName=group))
    _create_ignoring_exists(
        lambda: logs.create_log_stream(logGroupName=group, logStreamName=stream)
    )


def _create_ignoring_exists(call) -> None:
    try:
        call()
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
