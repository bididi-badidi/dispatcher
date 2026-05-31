from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3

from dispatcher.config import load_env_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manually verify boto3 can upload an object to the S3 log bucket."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path.cwd() / ".env",
        help="Path to the env file to load. Defaults to ./.env.",
    )
    parser.add_argument(
        "--key",
        help=(
            "Object key to write. Defaults to "
            "<AWS_S3_LOG_KEY_PREFIX>/manual-test/boto-s3-upload-<timestamp>.txt."
        ),
    )
    parser.add_argument(
        "--body",
        default="dispatcher manual boto3 S3 upload test\n",
        help="Text body to upload.",
    )
    args = parser.parse_args()

    load_env_file(args.env_file)

    bucket = required_env("AWS_S3_LOG_BUCKET")
    key = args.key or default_key()
    body = build_body(args.body)

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )

    print(f"Uploaded s3://{bucket}/{key}")
    return 0


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"error: {name} is required")
    return value


def default_key() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = os.getenv("AWS_S3_LOG_KEY_PREFIX", "").strip().strip("/")
    filename = f"manual-test/boto-s3-upload-{timestamp}.txt"
    return f"{prefix}/{filename}" if prefix else filename


def build_body(body: str) -> str:
    timestamp = datetime.now(UTC).isoformat()
    return f"{body.rstrip()}\ncreated_at={timestamp}\n"


if __name__ == "__main__":
    raise SystemExit(main())
