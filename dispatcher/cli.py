from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from typing import Sequence

from dispatcher.config import build_config
from dispatcher.github import list_triggered_issues
from dispatcher.models import Config
from dispatcher.pipeline import first_unstarted_issue, run_pipeline
from dispatcher.repo_context import config_for_repo
from dispatcher.state import StateStore
from dispatcher.state_backend import StateBackend


def run_once(config: Config, store: StateBackend) -> bool:
    for repo in _repos_for_polling(config, store):
        repo_config = config_for_repo(config, repo)
        issues = list_triggered_issues(repo_config, repo)
        issue = first_unstarted_issue(issues, repo, store)
        if issue is None:
            print(f"No new open issues with label {config.label!r} in {repo}.")
            continue

        state = run_pipeline(issue, repo_config, store)
        print(
            f"Issue #{state.number} reached {state.status}: "
            f"branch={state.branch} worktree={state.worktree}"
        )
        return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    config = build_config(argv)
    store: StateBackend
    if config.redis_url:
        from dispatcher.redis_store import RedisStateStore

        store = RedisStateStore(config.redis_url)
    else:
        store = StateStore(config.paths.state_file)

    if config.once:
        run_once(config, store)
        return 0

    if config.daemon:
        return _run_daemon(config, store)

    try:
        run_polling_loop(config, store)
    except KeyboardInterrupt:
        print("Stopping dispatcher polling.")
        return 130

    return 0


def _run_daemon(config: Config, store: StateBackend) -> int:
    from dispatcher.queue import Dispatcher

    try:
        asyncio.run(Dispatcher(config, store).run())
    except KeyboardInterrupt:
        print("Stopping dispatcher daemon.")
        return 130
    return 0


def run_polling_loop(
    config: Config,
    store: StateBackend,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    print(
        f"Polling for label {config.label!r} every "
        f"{config.poll_interval_seconds:g} seconds. Press Ctrl-C to stop."
    )
    while True:
        try:
            run_once(config, store)
        except Exception as exc:
            print(f"Polling cycle failed: {exc}", file=sys.stderr)
        sleep(config.poll_interval_seconds)


def _repos_for_polling(config: Config, store: StateBackend) -> list[str]:
    if hasattr(store, "get_repos"):
        return list(store.get_repos())  # type: ignore[attr-defined]
    if config.repo:
        return [config.repo]
    return []
