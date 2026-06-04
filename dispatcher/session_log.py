from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterable

THINKING_TAGS = ("thinking", "think", "reasoning")
_THINKING_RE = re.compile(
    "|".join(
        rf"<{tag}\b[^>]*>.*?</{tag}>"
        for tag in sorted(THINKING_TAGS, key=len, reverse=True)
    ),
    re.IGNORECASE | re.DOTALL,
)
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_STDOUT_MARKER = "\n[stdout]\n"
_STDERR_MARKER = "\n\n[stderr]"


def strip_thinking(text: str) -> str:
    cleaned = _THINKING_RE.sub("", text)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def extract_agent_output(stage_log_text: str) -> str:
    _before, marker, stdout_and_after = stage_log_text.partition(_STDOUT_MARKER)
    if not marker:
        return stage_log_text

    stdout, _stderr_marker, _stderr = stdout_and_after.partition(_STDERR_MARKER)
    return stdout


class FlowTrace:
    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []
        self._lock = asyncio.Lock()

    async def enter(self, node: str, *, iteration: int | None = None) -> None:
        async with self._lock:
            self._records.append(
                {
                    "kind": "enter",
                    "node": node,
                    "iteration": iteration,
                    "status": None,
                }
            )

    async def exit(self, node: str, *, status: str | None = None) -> None:
        async with self._lock:
            if node in {"END", "FAILED"}:
                self._records.append(
                    {
                        "kind": "exit",
                        "node": node,
                        "iteration": None,
                        "status": status,
                    }
                )
                return

            for record in reversed(self._records):
                if record["kind"] == "enter" and record["node"] == node:
                    record["status"] = status
                    return

            self._records.append(
                {
                    "kind": "exit",
                    "node": node,
                    "iteration": None,
                    "status": status,
                }
            )

    def render(self) -> str:
        lines = [self._render_record(record) for record in self._records]
        return "\n".join(lines)

    @staticmethod
    def _render_record(record: dict[str, object]) -> str:
        prefix = "\u21e5" if record["kind"] == "exit" else "\u2192"
        line = f"{prefix} {record['node']}"
        if record.get("iteration") is not None:
            line = f"{line} (iteration {record['iteration']})"
        if record.get("status"):
            line = f"{line} [{record['status']}]"
        return line


def compose_rollup(flow: str, stages: Iterable[tuple[str, Path]]) -> bytes:
    ordered_stages = list(stages)
    parts: list[str] = [
        "=== flow ===",
        flow.strip() or "(no flow recorded)",
        "",
        "=== conversation ===",
    ]

    for stage, path in ordered_stages:
        raw_text = path.read_text(encoding="utf-8")
        output = strip_thinking(extract_agent_output(raw_text))
        parts.append(f"--- {stage} ---")
        parts.append(output or "(no agent output)")
        parts.append("")

    parts.append("=== raw ===")
    for stage, path in ordered_stages:
        parts.append(f"=== {stage} ===")
        parts.append(path.read_text(encoding="utf-8"))
        parts.append("")

    return ("\n".join(parts).rstrip() + "\n").encode("utf-8")
