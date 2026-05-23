# Session Handover Notes

## Current context

- The async worker queue review items from 2026-05-23 have been addressed.
- Fresh issue polling still treats any existing state record as terminal,
  including `failed`; this matches current behavior and is now documented in
  `README.md`. Retrying a failed issue currently requires clearing or editing
  its `.dispatcher/state.json` entry.
- Review requeue scaffolding intentionally allows an issue with existing
  completed state to be queued as a review task, while fresh issue polling skips
  any existing state record.
- Tests are organized by dispatcher component under `tests/test_*.py`, with
  shared fixtures in `tests/helpers.py` and path setup in `tests/conftest.py`.

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
