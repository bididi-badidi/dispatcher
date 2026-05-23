# Dispatcher

Local issue-triggered automation dispatcher for the Phase 1 happy path in
[`.ai/assets/PLAN.md`](.ai/assets/PLAN.md).

The dispatcher polls GitHub for one open issue with the trigger label, records
state locally, runs the three planned agent stages in sequence, and stops after
the build stage opens a PR.

## Usage

```bash
uv run python main.py --repo OWNER/REPO
```

Useful options:

- `--label automate` chooses the trigger label.
- `--base-branch main` chooses the branch used for the worktree.
- The base checkout defaults to `/Projects/{repo_name}/main` when the
  dispatcher is run from `/Projects/dispatcher` or `/Projects/dispatcher/main`.
- New worktrees default to `/Projects/{repo_name}/{branch_name}`.
- Dispatcher state and logs stay under the dispatcher directory by default.
- `--dry-run` writes the stage commands to `.dispatcher/logs/` without running
  Gemini, Claude, or Codex.
- The worktree stage must create the path selected by the dispatcher before
  planning can start.

The generated state file defaults to `.dispatcher/state.json`; issue records
are grouped by repository so `OWNER/REPO#7` does not collide with another
repository's issue `#7`. Logs default to `.dispatcher/logs/` and use matching
repository subdirectories.

## Stage Prompts

Each stage has a provider-specific subprocess runner. The runner owns the safe
non-interactive CLI flags; the configurable value is only the prompt template:

```bash
DISPATCHER_WORKTREE_COMMAND='Create a git worktree for issue #$issue_number ...' \
DISPATCHER_PLAN_COMMAND='Plan issue #$issue_number ...' \
DISPATCHER_BUILD_COMMAND='Implement issue #$issue_number ...' \
uv run python main.py --repo OWNER/REPO
```

Available template variables include `$issue_number`, `$issue_title`,
`$issue_url`, `$repo`, `$project_dir`, `$worktree`, `$branch`, and
`$base_branch`.

The default build prompt tells Codex to use its configured GitHub MCP for PR
creation when available and not to require `gh` for that step. Git still
publishes the local branch before the PR is opened.

The default runners use:

- Gemini: `gemini --approval-mode auto_edit --allowed-tools ... --prompt`.
  The allowlist includes Gemini's real filesystem/search/fetch tool names
  (`list_directory`, `read_file`, `read_many_files`, `glob`, `grep_search`,
  `web_fetch`), `activate_skill`, and `run_shell_command` for the
  skill-driven worktree bootstrap flow. Scoped `run_shell_command(...)`
  prefixes remain listed as documentation for the common git, worktree setup,
  dependency install, and shell inspection commands.
  The dispatcher does not pass `--sandbox` to Gemini and removes inherited
  Gemini sandbox environment variables so macOS Seatbelt does not restrict
  worktree creation outside `/Projects/{repo_name}/main`.
- Claude: `printf '%s\n' '<prompt>' | claude --print --permission-mode acceptEdits --allowedTools ... --disallowedTools ...`.
  The planning runner only pre-approves reads, issue/codebase inspection
  commands, read-only `gh` commands, and writes under `.ai/assets/branches/`;
  mutating `gh` commands and destructive shell commands such as `rm`, hard
  resets, forced pushes, and delete-style commands are explicitly denied.
- Codex: `codex exec --sandbox workspace-write --config sandbox_workspace_write.network_access=true --config sandbox_workspace_write.writable_roots=[...] --add-dir <git-dir> --cd <worktree>`.
  For linked worktrees, the runner reads the worktree `.git` metadata and grants
  both its per-worktree Git admin directory and shared Git directory when they
  sit outside Codex's writable workspace root. It passes those roots through
  both the Codex workspace-write config and `--add-dir` so linked-worktree Git
  index and ref updates can write their admin metadata. Network access stays
  enabled for the build stage because Codex is expected to push its branch and
  open a PR.

The dispatcher rejects yolo or dangerous skip/bypass flags before launching any
agent subprocess.

## Development

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```

## Code Layout

- `main.py` is a thin compatibility entry point for `python main.py` and tests
  that import the historical module.
- `dispatcher/config.py` owns CLI argument parsing and environment defaults.
- `dispatcher/github.py`, `dispatcher/state.py`, and `dispatcher/pipeline.py`
  own issue polling, persisted state, and orchestration flow.
- `dispatcher/runners.py` owns provider-specific Gemini, Claude, and Codex
  subprocess commands.
- `dispatcher/git.py` and `dispatcher/prompts.py` hold worktree/Git helpers and
  prompt templating.
