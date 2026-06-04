"""Operator-facing subprocess command logging."""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence

LOGGER = logging.getLogger("dispatcher.subprocess")


def print_subprocess_command(command: Sequence[str], *, debug: bool = False) -> None:
    if debug:
        LOGGER.info("$ %s", shlex.join(command))


def run_json(command: Sequence[str], cwd: Path, *, debug: bool = False) -> Any:
    print_subprocess_command(command, debug=debug)
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout or "[]")
