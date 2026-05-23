# Task Archive

- [x] Phase 1 follow-up: encapsulated Codex, Gemini, and Claude subprocess execution under an abstract `AgentRunner`, with provider-specific non-interactive flags, CLI version logging, and rejection of yolo/dangerous bypass flags.
- [x] Phase 1 follow-up: scoped dispatcher issue state and stage logs by repository so matching GitHub issue numbers from multiple repos do not collide.
- [x] Phase 1 follow-up: made the default worktree prompt include the dispatcher-selected branch/path and fail fast when a provider does not create that expected worktree.
- [x] Phase 1 follow-up: fixed default target-repository path resolution when the dispatcher itself is running from a `dispatcher/main` worktree, so sibling repos resolve under `/Projects/{repo_name}` instead of `/Projects/dispatcher/{repo_name}`.
- [x] Phase 1 follow-up: refactored the dispatcher monolith into a modular `dispatcher/` package while preserving `main.py` as the CLI and compatibility import surface.
- [x] Phase 1 follow-up: changed the dispatcher CLI into a long-polling process with a configurable 120-second default interval and `--once` single-cycle mode.
- [x] Session-management branch: implemented async worker queue daemon mode with `--daemon`, `--max-workers`, non-blocking stage execution, in-flight dedupe, review requeue scaffolding, and queue snapshots.
- [x] Session-management branch review fixes: made queue enqueue shutdown-aware, validated review-task worktrees before plan/build stages, documented terminal failed-state behavior, and covered the fixes with regression tests.
- [x] Test refactor: split the monolithic dispatcher test file into component-focused test modules with shared helpers.
- [x] PR review follow-up: addressed Copilot comments for daemon mode flag exclusivity, Ctrl-C handling, snapshot private queue access documentation, and async runner locale encoding.
