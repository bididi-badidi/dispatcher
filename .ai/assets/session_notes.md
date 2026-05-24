# Session Handover Notes

## Current context

- No active handover blockers for `feat/issue-6`.

## Stable project context

- Runner defaults verified against official CLI versions on 2026-05-21:
  codex-cli 0.130.0, Claude Code 2.1.98, gemini 0.38.2.
- Dispatcher intentionally rejects `--yolo`, `--full-auto`, and dangerous
  skip/bypass permission flags.
- State records live under `repositories[owner/name].issues[number]`; logs
  mirror repo path under `.dispatcher/logs/`.
- Worktree contract mismatch (2026-05-22): default prompt names the expected
  branch/path and pipelines validate the path before plan/build stages.
- Default repo path resolution is aware of branch-style dispatcher checkouts
  (sibling repos).
- `main.py` is a compatibility wrapper; patch internal dependencies in tests at
  their owning modules, such as `dispatcher.pipeline.run_stage`.
- CLI long-polls every 120 seconds; `--poll-interval` or
  `DISPATCHER_POLL_INTERVAL_SECONDS` overrides it. `--once` forces a single
  synchronous cycle, and `--daemon` uses the async worker queue.
- Fresh issue polling skips any existing state record (including `failed`);
  retrying a failed issue requires clearing/editing `.dispatcher/state.json`.
  Review requeue scaffolding intentionally allows re-queuing an issue with
  existing completed state as a review task.
- Tests are organized by dispatcher component under `tests/test_*.py`, with
  shared fixtures in `tests/helpers.py` and path setup in `tests/conftest.py`.
- `uv` needs `UV_CACHE_DIR=/private/tmp/uv-cache-issue-3` in this sandbox because `/Users/user/.cache/uv` is not writable here.
