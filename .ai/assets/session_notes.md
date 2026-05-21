# Session Handover Notes

- Current runner defaults were checked against official docs on 2026-05-21. Installed local CLI versions observed: `codex-cli 0.130.0`, `Claude Code 2.1.98`, `gemini 0.38.2`.
- The dispatcher intentionally rejects `--yolo`, `--full-auto`, and dangerous skip/bypass permission flags before launching agent subprocesses.
- Claude planning permissions now follow the official permission-rule syntax, pre-approve only read/planning operations, read-only `gh` commands, and writes under `.ai/assets/branches/`. They explicitly deny mutating `gh` commands and destructive shell commands in the runner flags; project `.claude/settings.json` also denies destructive shell commands.
