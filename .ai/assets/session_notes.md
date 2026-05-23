# Session Handover Notes

- Current runner defaults were checked against official docs on 2026-05-21. Installed local CLI versions observed: `codex-cli 0.130.0`, `Claude Code 2.1.98`, `gemini 0.38.2`.
- The dispatcher intentionally rejects `--yolo`, `--full-auto`, and dangerous skip/bypass permission flags before launching agent subprocesses.
- Claude planning permissions now follow the official permission-rule syntax, pre-approve only read/planning operations, read-only `gh` commands, and writes under `.ai/assets/branches/`. They explicitly deny mutating `gh` commands and destructive shell commands in the runner flags; project `.claude/settings.json` also denies destructive shell commands.
- State records now live under `repositories[owner/name].issues[number]`, and logs mirror the repo path under `.dispatcher/logs/`. Legacy top-level `issues` state is not used for dispatching because it cannot reliably identify the source repository.
- A 2026-05-22 run for `bididi-badidi/testing-coding-assistant#1` exposed a worktree contract mismatch: dispatcher default branch `feat/issue-1` implied `/Users/user/Projects/testing-coding-assistant/feat/issue-1`, while Gemini prepared existing `fix/issue-1`. The default prompt now names the expected branch/path, and the pipeline validates the path before starting plan/build stages.
