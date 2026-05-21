# Dispatcher

Local issue-triggered automation dispatcher for the Phase 1 happy path in
[`.ai/assets/PLAN.md`](.ai/assets/PLAN.md).

The dispatcher polls GitHub for one open issue with the trigger label, records
state locally, runs the three planned agent stages in sequence, and stops after
the build stage opens a draft PR.

## Usage

```bash
uv run python main.py --repo OWNER/REPO
```

Useful options:

- `--label automate` chooses the trigger label.
- `--base-branch main` chooses the branch used for the worktree.
- `--dry-run` writes the stage commands to `.dispatcher/logs/` without running
  Gemini, Claude, or Codex.

The generated state file defaults to `.dispatcher/state.json`; logs default to
`.dispatcher/logs/`.

## Stage Commands

Each stage command is a shell template. Override the defaults when local CLI
flags differ:

```bash
DISPATCHER_WORKTREE_COMMAND='gemini -p "..."' \
DISPATCHER_PLAN_COMMAND='claude -p "..."' \
DISPATCHER_BUILD_COMMAND='codex exec "...' \
uv run python main.py --repo OWNER/REPO
```

Available template variables include `$issue_number`, `$issue_title`,
`$issue_url`, `$repo`, `$project_dir`, `$worktree`, `$branch`, and
`$base_branch`.

## Development

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```
