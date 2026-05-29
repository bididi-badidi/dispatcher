"""Operator-facing subprocess command echoes.

The dispatcher workflow uses structured logging. This helper intentionally
keeps a direct stdout echo so humans can see the exact external command being
launched in CLI sessions.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence


def print_subprocess_command(command: Sequence[str]) -> None:
    print(f"$ {shlex.join(command)}")


def run_json(command: Sequence[str], cwd: Path) -> Any:
    print_subprocess_command(command)
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout or "[]")
