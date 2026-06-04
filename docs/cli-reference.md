# CLI Reference

All flags for `uv run python main.py`. Environment variables can also be set in
a `.env` file in the dispatcher directory; shell exports take precedence over
`.env` values.

## Run modes

These three flags are mutually exclusive.

| Flag | Description |
|------|-------------|
| _(none)_ | Long-poll loop. Checks for new labelled issues every `--poll-interval` seconds and runs them one at a time. Does **not** handle PR review responses. |
| `--once` | Run one polling cycle and exit. Useful for testing or cron-scheduled runs. |
| `--daemon` | Async worker pool backed by a LangGraph pipeline. Supports concurrent issue pipelines, build-review retry loops, and PR comment triggers. Required to act on comments left on open PRs. |

## Daemon options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-workers N` | `3` | Number of concurrent issue pipelines in daemon mode. |

## Repository targeting

| Flag / Env var | Default | Description |
|----------------|---------|-------------|
| `DISPATCHER_REPO=OWNER/REPO` | — | Single-repo mode. Required when Redis is not configured. |
| `DISPATCHER_REDIS_URL=redis://...` | — | Enables Redis-backed state. Repos to poll are read from the `dispatcher:repos` set (managed with `dispatcher-repos`). |

## Polling

| Flag / Env var | Default | Description |
|----------------|---------|-------------|
| `--poll-interval N` / `DISPATCHER_POLL_INTERVAL_SECONDS` | `120` | Seconds between polling cycles. |

## Branch and path configuration

| Flag / Env var | Default | Description |
|----------------|---------|-------------|
| `--base-branch BRANCH` / `DISPATCHER_BASE_BRANCH` | `main` | Branch used as the base for new worktrees. |
| `--branch-prefix PREFIX` / `DISPATCHER_BRANCH_PREFIX` | `feat/` | Prefix applied to generated feature branch names. |
| `--project-dir PATH` | `<worktree-root>/<base-branch>` | Base checkout where the worktree agent runs. |
| `--worktree-root PATH` | `/Projects/<repo_name>` | Parent directory for new worktrees. |
| `DISPATCHER_PROJECTS_DIR` | `~/Projects` | Root under which repo and worktree directories are created. Independent of `DISPATCHER_ROOT_DIR`. |

## State and logging

| Flag / Env var | Default | Description |
|----------------|---------|-------------|
| `--state-file PATH` / `DISPATCHER_STATE_FILE` | `.dispatcher/state.json` | Local JSON state file (single-repo mode only). |
| `--log-dir PATH` / `DISPATCHER_LOG_DIR` | `.dispatcher/logs/` | Directory for per-stage subprocess logs. |

## Stage labels and model escalation

| Env var | Default | Description |
|---------|---------|-------------|
| `--label LABEL` / `DISPATCHER_LABEL` | `automate` | GitHub label that triggers the dispatcher. |
| `DISPATCHER_OPUS_LABEL` | `automate:opus` | Secondary label that escalates the planning stage to Opus. |
| `DISPATCHER_OPUS_MODEL` | `claude-opus-4-7` | Claude model used when the Opus escalation label is present. |

## Stage prompt overrides

Each stage runner accepts a prompt template. Available variables: `$issue_number`,
`$issue_title`, `$issue_url`, `$repo`, `$project_dir`, `$worktree`, `$branch`,
`$base_branch`.

| Env var | Description |
|---------|-------------|
| `DISPATCHER_WORKTREE_COMMAND` | Prompt passed to Gemini for worktree creation. |
| `DISPATCHER_PLAN_COMMAND` | Prompt passed to Claude for planning. |
| `DISPATCHER_BUILD_COMMAND` | Prompt passed to Codex for implementation and PR opening. |

Equivalent CLI flags: `--worktree-command`, `--plan-command`, `--build-command`.

## Miscellaneous

| Flag | Description |
|------|-------------|
| `--dry-run` | Write stage commands to logs without running Gemini, Claude, or Codex. |
