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
from dispatcher.state import StateStore


def run_once(config: Config, store: StateStore) -> bool:
    issues = list_triggered_issues(config)
    issue = first_unstarted_issue(issues, config.repo, store)
    if issue is None:
        print(f"No new open issues with label {config.label!r} in {config.repo}.")
        return False

    state = run_pipeline(issue, config, store)
    print(
        f"Issue #{state.number} reached {state.status}: "
        f"branch={state.branch} worktree={state.worktree}"
    )
    return True


def main(argv: Sequence[str] | None = None) -> int:
    config = build_config(argv)
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


def _run_daemon(config: Config, store: StateStore) -> int:
    from dispatcher.queue import Dispatcher

    try:
        asyncio.run(Dispatcher(config, store).run())
    except KeyboardInterrupt:
        print("Stopping dispatcher daemon.")
        return 130
    return 0


def run_polling_loop(
    config: Config,
    store: StateStore,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    print(
        f"Polling {config.repo} for label {config.label!r} every "
        f"{config.poll_interval_seconds:g} seconds. Press Ctrl-C to stop."
    )
    while True:
        try:
            run_once(config, store)
        except Exception as exc:
            print(f"Polling cycle failed: {exc}", file=sys.stderr)
        sleep(config.poll_interval_seconds)
