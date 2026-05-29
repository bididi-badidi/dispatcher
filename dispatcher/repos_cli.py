from __future__ import annotations

import argparse
import logging
import re
from typing import Protocol, Sequence

from dispatcher.config import build_config
from dispatcher.logging_setup import configure_logging
from dispatcher.redis_store import RedisStateStore

REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
LOGGER = logging.getLogger("dispatcher.repos_cli")


class RepoStore(Protocol):
    def add_repo(self, repo: str) -> int: ...

    def get_repos(self) -> list[str]: ...

    def remove_repo(self, repo: str) -> int: ...

    def close(self) -> None: ...


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)

    try:
        config = build_config([])
    except SystemExit:
        LOGGER.error("error: DISPATCHER_REDIS_URL is not set")
        return 2

    if not config.redis_url:
        LOGGER.error("error: DISPATCHER_REDIS_URL is not set")
        return 2

    for repo in getattr(args, "repos", []):
        if not _is_valid_repo(repo):
            LOGGER.error("error: invalid repo %r, expected owner/name", repo)
            return 2

    store = RedisStateStore(config.redis_url)
    try:
        return _dispatch(args, store)
    finally:
        store.close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dispatcher-repos",
        description="Manage repositories tracked by the Redis-backed dispatcher.",
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
            LOGGER.info("tracked: %s", repo)
        return 0

    if args.command == "list":
        for repo in store.get_repos():
            print(repo)
        return 0

    if args.command == "remove":
        for repo in args.repos:
            store.remove_repo(repo)
            LOGGER.info("removed (or already absent): %s", repo)
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _is_valid_repo(repo: str) -> bool:
    return repo == repo.strip() and REPO_PATTERN.fullmatch(repo) is not None
