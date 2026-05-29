# Project Progress

## Current Task

No active tasks

## Upcoming

### Future Features

- [ ] **Dashboard** — real-time UI to track per-worker progress and the live work queue (issue assignments, stage, status, ETA).
- [ ] **Dynamic branch naming** — agent determines the branch name at planning time; all subsequent git operations (worktree, PR, cleanup) use the agent-chosen name rather than a hardcoded convention.
- [ ] **Robust S3 logging** — structured, per-run log files shipped to an S3 bucket; local logs remain lightweight; log level and bucket configured via env/config.
- [ ] **Prompt versioning** — prompts are versioned artifacts (e.g. `prompts/v1/plan.md`); the running version is recorded in state and logs so behaviour is reproducible and rollbacks are possible.

## Project Documents

- [Architecture & Plan](.ai/assets/PLAN.md)
- [Session Notes](.ai/assets/session_notes.md)
- [Backlog](.ai/assets/backlog.md)
- [Task Archive](.ai/assets/task_archive.md)

## Phases

- [x] Phase 1 skeleton: local dispatcher CLI detects labelled issues, records repo-scoped JSON state, uses and validates the `/Projects/{repo_name}/{branch_name}` worktree convention, runs worktree/plan/build stage commands, and stops after PR creation. Tests cover issue selection, dry-run orchestration, and GitHub CLI polling.
- [x] Worker queue daemon mode: async dispatcher queue processes multiple issues concurrently with daemon CLI flags, async stage execution, in-flight dedupe, review requeue scaffolding, and queue snapshot state. See [worker queue plan](.ai/assets/branches/feat/session-management/worker-queue-plan.md).
- [x] Config startup hardening: dispatcher startup loads local `.env` defaults before CLI config construction, with shell environment precedence preserved. See [Task Archive](.ai/assets/task_archive.md).
- [x] PR lifecycle automation: detects requested-changes PR reviews, requeues Codex review tasks, detects merged PRs, and performs post-merge branch/worktree cleanup. See [Task Archive](.ai/assets/task_archive.md).
