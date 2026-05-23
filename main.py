from __future__ import annotations

import subprocess
import sys

from dispatcher.async_pipeline import async_run_pipeline
from dispatcher.async_runners import async_run_stage
from dispatcher.cli import _run_daemon, main, run_once, run_polling_loop
from dispatcher.config import build_config
from dispatcher.constants import (
    BANNED_AGENT_FLAGS,
    CLAUDE_PLAN_ALLOWED_TOOLS,
    CLAUDE_PLAN_DISALLOWED_TOOLS,
    DEFAULT_BASE_BRANCH,
    DEFAULT_BRANCH_PREFIX,
    DEFAULT_LABEL,
    DEFAULT_LOG_DIR,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STATE_FILE,
    GEMINI_WORKTREE_ALLOWED_TOOLS,
)
from dispatcher.git import (
    branch_for_issue,
    codex_git_write_dirs,
    common_git_dir,
    default_worktree_root,
    repo_name_from_full_name,
    require_worktree_path,
    worktree_git_dir,
    worktree_path_for_issue,
)
from dispatcher.github import list_triggered_issues
from dispatcher.models import Commands, Config, Issue, IssueState, Paths
from dispatcher.pipeline import first_unstarted_issue, run_pipeline
from dispatcher.queue import Dispatcher, QueueSnapshot, Task, TaskType
from dispatcher.prompts import (
    default_build_command,
    default_plan_command,
    default_worktree_command,
    render_template,
)
from dispatcher.runners import (
    AgentRunner,
    ClaudeRunner,
    CodexRunner,
    GeminiRunner,
    build_stage_runners,
    run_stage,
)
from dispatcher.state import StateStore
from dispatcher.subprocess_utils import print_subprocess_command, run_json
from dispatcher.time_utils import utc_now

__all__ = [
    "AgentRunner",
    "BANNED_AGENT_FLAGS",
    "CLAUDE_PLAN_ALLOWED_TOOLS",
    "CLAUDE_PLAN_DISALLOWED_TOOLS",
    "ClaudeRunner",
    "CodexRunner",
    "Commands",
    "Config",
    "DEFAULT_BASE_BRANCH",
    "DEFAULT_BRANCH_PREFIX",
    "DEFAULT_LABEL",
    "DEFAULT_LOG_DIR",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_STATE_FILE",
    "Dispatcher",
    "GEMINI_WORKTREE_ALLOWED_TOOLS",
    "GeminiRunner",
    "Issue",
    "IssueState",
    "Paths",
    "QueueSnapshot",
    "StateStore",
    "Task",
    "TaskType",
    "_run_daemon",
    "async_run_pipeline",
    "async_run_stage",
    "branch_for_issue",
    "build_config",
    "build_stage_runners",
    "codex_git_write_dirs",
    "common_git_dir",
    "default_build_command",
    "default_plan_command",
    "default_worktree_command",
    "default_worktree_root",
    "first_unstarted_issue",
    "list_triggered_issues",
    "main",
    "print_subprocess_command",
    "render_template",
    "repo_name_from_full_name",
    "require_worktree_path",
    "run_json",
    "run_once",
    "run_pipeline",
    "run_polling_loop",
    "run_stage",
    "subprocess",
    "utc_now",
    "worktree_git_dir",
    "worktree_path_for_issue",
]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
