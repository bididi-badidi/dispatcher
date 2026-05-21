# Plan: Issue-Triggered Local Automation Pipeline

## Objective

Build a local dispatcher (a long-running orchestrator on the MacBook) that turns a single labelled GitHub issue into the full feature-development pipeline, with one human gate at PR review. Everything runs on one machine so the existing git worktrees and gitignored `.env` files stay reachable.

This is the "Option 1, pure local dispatcher" approach. No GitHub-hosted runner is used.

## Agent roster

Three CLIs (command-line AI agents), each owning one stage. Each agent is expected to figure out its own headless flags and permission settings; this plan does not prescribe them.

| Stage             | Agent                | Responsibility                                                                             |
| ----------------- | -------------------- | ------------------------------------------------------------------------------------------ |
| Worktree creation | Gemini CLI           | Create the new worktree, run the worktree skill, copy gitignored `.env` files              |
| Planning          | Claude (Claude Code) | Read the issue, write the feature plan into `.assets/`                                     |
| Coding            | Codex CLI            | Implement the plan, commit to a feature branch, open the PR, later address review comments |

## Repository conventions assumed

These already exist and must be respected, not redesigned:

- All repos live under `/Projects/`.
- Each project has branches: `main`, `dev`, `feat/*`, `ci/*`, etc.
- Worktree creation is governed by an existing skill that includes copying `.env` files (which are gitignored, so they exist only locally).
- The planning agent writes to a `.assets/` directory, as instructed in `gemini.md` / `claude.md`.
- Code lands on a feature branch via PR, gets reviewed by the human, then merges to `dev`.

## High-level pipeline

1. Human creates an issue and applies the trigger label (proposed: `automate`).
2. Dispatcher detects the new labelled issue.
3. Dispatcher invokes Gemini CLI in the project's `main` (or chosen base) directory to create the worktree and copy `.env`.
4. Dispatcher invokes Claude in the new worktree to plan the feature into `.assets/`.
5. Dispatcher invokes Codex CLI in the worktree (fresh context) to implement, commit, and open a PR.
6. Human reviews the PR and comments. This is the only manual gate.
7. Dispatcher detects new PR review comments and invokes Codex CLI again to address them.
8. Once the PR is approved, the PR merges to `dev` (auto or manual, see Open decisions).

## Components to build

### 1. Watcher

- Polls GitHub for issues carrying the trigger label using the GitHub CLI (`gh`, GitHub's official command-line tool).
- Runs as a launchd service (the macOS background-service manager, preferred over cron for reliability) or as a guarded loop.
- Optional later upgrade: replace polling with a GitHub webhook delivered through a tunnel (a service such as cloudflared or ngrok that exposes the local machine to a public URL).

### 2. State store

- Tracks which issues have been started, which stage each is in, and which have completed.
- Prevents the same issue from being processed twice.
- Simple is fine: a JSON file or a SQLite database (a lightweight on-disk database) keyed by issue number.

### 3. Orchestrator

- For each new issue, runs the stages in order.
- Sets the working directory correctly before each agent call (base project directory for worktree creation, the new worktree directory for planning and coding). Each stage is a separate non-interactive agent invocation, not a persistent session.
- Captures each stage's exit status and logs output per issue.

### 4. Stage runners (one thin wrapper per agent)

- `run_worktree(issue)` invokes Gemini CLI to create the worktree and copy `.env`.
- `run_plan(issue, worktree)` invokes Claude to write the plan to `.assets/`.
- `run_build(issue, worktree)` invokes Codex CLI to implement, commit, and open the PR. Use fresh context here (the clean-context requirement for coding).
- Each wrapper passes the issue number and any needed paths; the agent figures out its own flags.

### 5. PR feedback loop

- Watches for new review comments on open PRs created by the pipeline (via `gh`).
- On a new comment, invokes Codex CLI in that worktree to address it, then push.

### 6. Merge step

- On approval, merge the PR to `dev`.

## Build phases

Ship in order; do not build the later phases until the earlier ones are solid.

- **Phase 1 (core happy path):** Watcher detects one labelled issue, orchestrator runs the three stages, stops at PR creation. No feedback loop, no auto-merge.
- **Phase 2 (robustness):** State store, per-issue logging, idempotency (not re-processing an issue), error handling and retries on stage failure.
- **Phase 3 (feedback loop):** Detect PR review comments and trigger the coding agent to address them.
- **Phase 4 (merge automation):** Auto-merge to `dev` on approval, if desired.
- **Phase 5 (optional):** Swap polling for webhook + tunnel.

## Failure handling and edge cases

- A stage fails (non-zero exit): record the failure, comment on the issue or PR, stop that issue's pipeline; do not advance to the next stage.
- Worktree already exists for the issue: skip creation, continue.
- Two issues labelled at once: process them independently; decide whether to run concurrently or queue (see Open decisions).
- Dispatcher restarts mid-pipeline: state store should let it resume rather than restart an issue.
- Agent waits for input: all agent calls must be non-interactive (headless), so the orchestrator never blocks on a prompt.

## Open decisions (resolve before Phase 1)

1. Trigger label name (proposed: `automate`).
2. Base branch for worktree creation (always `main`, or read from the issue).
3. Concurrency: run multiple issues in parallel, or one at a time?
4. Auto-merge to `dev` on approval, or keep merge manual?
5. Where logs and the state store live on disk.

## Cost note

Headless agent runs can consume quota quickly. For Claude specifically, from June 15, 2026, `claude -p` and Agent SDK usage on subscription plans draws from a separate monthly Agent SDK credit, independent of interactive limits ([Claude Code docs, "Run Claude Code programmatically"](https://code.claude.com/docs/en/headless)). Budget for this and add a per-issue spend log if cost visibility matters.
