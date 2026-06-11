from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Protocol, Sequence

from dispatcher.config import load_env_file
from dispatcher.redis_store import RedisStateStore

REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class RepoStore(Protocol):
    def add_repo(self, repo: str) -> int: ...

    def get_repos(self) -> list[str]: ...

    def remove_repo(self, repo: str) -> int: ...

    def close(self) -> None: ...


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    load_env_file()
    redis_url = args.redis_url or os.getenv("DISPATCHER_REDIS_URL")

    if not redis_url:
        print(
            "error: DISPATCHER_REDIS_URL is not set "
            "(set the environment variable or pass --redis-url)",
            file=sys.stderr,
        )
        return 2

    for repo in getattr(args, "repos", []):
        if not _is_valid_repo(repo):
            print(f"error: invalid repo {repo!r}, expected owner/name", file=sys.stderr)
            return 2

    store = RedisStateStore(redis_url)
    try:
        return _dispatch(args, store)
    finally:
        store.close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dispatcher-repos",
        description="Manage repositories tracked by the Redis-backed dispatcher.",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (overrides DISPATCHER_REDIS_URL env var).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add repositories to poll.")
    add_parser.add_argument("repos", nargs="+", metavar="OWNER/REPO")

    subparsers.add_parser("list", help="List repositories currently tracked.")

    remove_parser = subparsers.add_parser(
        "remove", help="Remove repositories from polling."
    )
    remove_parser.add_argument("repos", nargs="+", metavar="OWNER/REPO")

    return parser.parse_args(argv)


def _dispatch(args: argparse.Namespace, store: RepoStore) -> int:
    if args.command == "add":
        for repo in args.repos:
            store.add_repo(repo)
            print(f"tracked: {repo}")
        return 0

    if args.command == "list":
        for repo in store.get_repos():
            print(repo)
        return 0

    if args.command == "remove":
        for repo in args.repos:
            store.remove_repo(repo)
            print(f"removed (or already absent): {repo}")
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _is_valid_repo(repo: str) -> bool:
    return repo == repo.strip() and REPO_PATTERN.fullmatch(repo) is not None
