# Dispatcher

Local issue-triggered automation dispatcher described in
[`.ai/assets/PLAN.md`](.ai/assets/PLAN.md).

The dispatcher long-polls GitHub for open issues with the trigger label,
records state locally, and runs labelled issues through either the simple loop
or daemon worker pipeline until PR creation.

## Architecture

```
Issue (labelled automate)
        |
        v
   GitHub Poller
        |
   +----+----+
Simple      Daemon (--daemon)
  loop       |
        AsyncIO worker pool
             |
        LangGraph pipeline
        +------------------+
        | worktree -> plan |
        | -> build -> review |
        | -> (retry) -> PR |
        +------------------+
```

The simple loop processes each newly labelled issue through the worktree,
planning, and build stages in order, then stops after PR creation.

Daemon mode keeps the same polling source and stage runners, but uses an
`asyncio` worker pool and LangGraph pipeline to run issue work concurrently with
review and retry steps.

## Agent setup

Agent configuration (`.ai/` directory layout, `CLAUDE.md`, `GEMINI.md`, and
skills) follows the
[bididi-badidi/agent-project-blueprint](https://github.com/bididi-badidi/agent-project-blueprint).
Clone or reference that repo to replicate the same agent behavior in a new
project.

## Usage

Simple polling loop — processes newly labelled issues one at a time:

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py
```

Daemon mode — concurrent worker pool, PR review response triggers:

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py --daemon
```

Redis-backed daemon — polls all registered repositories:

```bash
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run python main.py --daemon
```

On startup the dispatcher loads environment defaults from a `.env` file in the
current dispatcher directory. Shell exports take precedence. Start from
`.env.example` when creating a local `.env` file.

Use `--debug` or `DISPATCHER_DEBUG=1` to print subprocess commands to stdout.

See [docs/cli-reference.md](docs/cli-reference.md) for all flags and
environment variables.

See [docs/scripts.md](docs/scripts.md) for common operational scripts
(repository registration, state inspection, clearing failed records).

## Stage Prompts

Each stage has a provider-specific subprocess runner. The runner owns the safe
non-interactive CLI flags; the configurable value is only the prompt template:

```bash
DISPATCHER_WORKTREE_COMMAND='Create a git worktree for issue #$issue_number ...' \
DISPATCHER_PLAN_COMMAND='Plan issue #$issue_number ...' \
DISPATCHER_BUILD_COMMAND='Implement issue #$issue_number ...' \
DISPATCHER_REPO=OWNER/REPO uv run python main.py
```

Available template variables include `$issue_number`, `$issue_title`,
`$issue_url`, `$repo`, `$project_dir`, `$worktree`, `$branch`, and
`$base_branch`.

The default build prompt tells Codex to use its configured GitHub MCP for PR
creation when available and not to require `gh` for that step. Git still
publishes the local branch before the PR is opened.

The default runners use:

- Gemini creates the worktree and copies `.env` files via the git-worktree
  skill; it runs with `--approval-mode auto_edit`.
- Claude reads the issue and writes the feature plan into
  `.ai/assets/branches/`; it is restricted to read and plan-asset-write work.
- Codex implements the plan, commits on the feature branch, and opens the PR;
  it runs with network access enabled for push and PR creation.

The dispatcher rejects yolo or dangerous skip/bypass flags before launching any
agent subprocess.

## Development

Branching policy: feature branches merge into `dev`; only `dev` merges into
`main`. This is enforced by the `branch-policy` workflow. See
[CONTRIBUTING.md](CONTRIBUTING.md#branching-strategy).

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```

## Code Layout

- `main.py` is a thin compatibility entry point for `python main.py` and tests
  that import the historical module.
- `dispatcher/config.py` owns CLI argument parsing and environment defaults.
- `dispatcher/redis_store.py` owns Redis-backed repo discovery and shared state.
- `dispatcher/github.py`, `dispatcher/state.py`, and `dispatcher/pipeline.py`
  own issue polling, persisted state, and orchestration flow.
- `dispatcher/queue.py`, `dispatcher/langgraph_pipeline.py`, and
  `dispatcher/async_runners.py` own daemon-mode queueing, graph orchestration,
  and non-blocking subprocess execution.
- `dispatcher/runners.py` owns provider-specific Gemini, Claude, and Codex
  subprocess commands.
- `dispatcher/git.py` and `dispatcher/prompts.py` hold worktree/Git helpers and
  prompt templating.
