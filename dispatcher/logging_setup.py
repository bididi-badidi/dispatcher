from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("dispatcher")

_DISPATCHER_HANDLER = "_dispatcher_stream_handler"
_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)
_EXTRA_DENYLIST = {
    "message",
    "asctime",
    "exc_text",
    "stack_info",
}


class DispatcherFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        extras = {
            key: _json_safe(value)
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_KEYS
            and key not in _EXTRA_DENYLIST
            and not key.startswith("_")
        }
        if not extras:
            return message
        return f"{message} {json.dumps(extras, sort_keys=True)}"


class DispatcherStreamHandler(logging.Handler):
    """Route operator logs to stdout, but keep ERROR+ diagnostics on stderr."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = sys.stderr if record.levelno >= logging.ERROR else sys.stdout
            stream.write(message + self.terminator)
            stream.flush()
        except Exception:
            self.handleError(record)

    terminator = "\n"


def configure_logging(level: str | None = None) -> None:
    logger = logging.getLogger("dispatcher")
    logger.setLevel(_parse_level(level or os.getenv("DISPATCHER_LOG_LEVEL") or "INFO"))
    logger.propagate = False

    for handler in logger.handlers:
        if getattr(handler, _DISPATCHER_HANDLER, False):
            handler.setLevel(logging.NOTSET)
            handler.setFormatter(
                DispatcherFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            return

    handler = DispatcherStreamHandler()
    setattr(handler, _DISPATCHER_HANDLER, True)
    handler.setFormatter(
        DispatcherFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)


def log_workflow_start(
    *,
    repo: str,
    issue_number: int,
    task_type: str,
    worker_id: int | None,
    branch: str,
    worktree: Path,
) -> None:
    label = _task_type_label(task_type)
    LOGGER.info(
        "[DISPATCHER] Processing %s #%d in %s",
        label,
        issue_number,
        repo,
        extra={
            "repo": repo,
            "issue_number": issue_number,
            "task_type": task_type,
            "worker_id": worker_id,
            "branch": branch,
            "worktree": str(worktree),
        },
    )


def log_workflow_complete(
    *,
    repo: str,
    issue_number: int,
    status: str,
    build_iteration: int,
    pr_url: str | None,
    state: Mapping[str, Any],
) -> None:
    LOGGER.info(
        "[DISPATCHER] Completed #%d in %s status=%s build_iter=%d pr=%s",
        issue_number,
        repo,
        status,
        build_iteration,
        pr_url or "none",
        extra={
            "repo": repo,
            "issue_number": issue_number,
            "status": status,
            "build_iteration": build_iteration,
            "pr_url": pr_url,
            "state": redact_state(state),
        },
    )


def log_workflow_failed(
    *,
    repo: str,
    issue_number: int,
    state: Mapping[str, Any],
) -> None:
    LOGGER.exception(
        "[DISPATCHER] Failed #%d in %s",
        issue_number,
        repo,
        extra={
            "repo": repo,
            "issue_number": issue_number,
            "state": redact_state(state),
        },
    )


def redact_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, value) for key, value in state.items()}


def _parse_level(level: str) -> int:
    parsed = getattr(logging, level.upper(), None)
    if isinstance(parsed, int):
        return parsed
    return logging.INFO


def _task_type_label(task_type: str) -> str:
    return "PR" if task_type == "review" else "issue"


def _redact_value(key: str, value: Any) -> Any:
    if key == "plan_content" and isinstance(value, str):
        return value[:500]
    if key.endswith("_feedback") and isinstance(value, str):
        return value[:500]
    return _json_safe(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
