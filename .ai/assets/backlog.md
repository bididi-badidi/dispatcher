# Project Backlog

## Future Features

### Dashboard
Track per-worker progress and the live work queue in a real-time UI.
- Show each worker's current issue, stage, and status.
- Show the pending queue (issue id, label, priority, enqueued time).
- Consider a simple terminal TUI (e.g. `textual`) or a lightweight web server (FastAPI + HTMX).
- Stretch: WebSocket push so the view auto-refreshes without polling.

### Dynamic Branch Naming
Let the agent decide the branch name at planning time instead of using a hardcoded convention.
- Agent outputs a branch name as part of its plan response.
- Dispatcher validates the name (length, characters, uniqueness) before creating the worktree.
- Branch name is stored in issue state and used for all downstream git operations (PR creation, cleanup).
- Fall back to the current `/Projects/{repo}/{branch}` convention if the agent returns nothing.

### Robust S3 Logging
Ship structured, per-run logs to an S3 bucket for durability and auditability.
- Local handler stays lightweight (WARNING+); S3 handler captures DEBUG+.
- Each run gets a deterministic key: `logs/{repo}/{issue_id}/{run_id}.jsonl`.
- Config: `LOG_S3_BUCKET`, `LOG_S3_PREFIX`, `LOG_LEVEL` env vars.
- Graceful degradation: if S3 upload fails, warn and continue (never block the worker).
- Consider `aioboto3` for non-blocking uploads inside the async dispatcher loop.

### Prompt Versioning
Treat prompts as versioned artifacts so runs are reproducible and rollbacks are easy.
- Store prompts under `prompts/v{N}/` (e.g. `prompts/v1/plan.md`, `prompts/v1/build.md`).
- Active version set via `PROMPT_VERSION` env var or config key (default: latest).
- Running version recorded in issue state JSON and in log lines.
- Changelog at `prompts/CHANGELOG.md` with intent behind each version bump.
- Stretch: A/B testing by routing a percentage of issues to a candidate version.
