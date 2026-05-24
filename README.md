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

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py
```

On startup, the dispatcher loads environment defaults from a `.env` file in the
current dispatcher directory. Variables that are already exported in the shell
take precedence over `.env` values.

Useful options:

- `--label automate` chooses the trigger label.
- `DISPATCHER_REDIS_URL=redis://...` enables Redis-backed repository tracking
  and shared issue state. Repositories are read from the `dispatcher:repos`
  Redis set.
- `DISPATCHER_REPO=OWNER/REPO` keeps the single-repository local JSON fallback
  when Redis is not configured.
- `--base-branch main` chooses the branch used for the worktree.
- The base checkout defaults to `/Projects/{repo_name}/main` when the
  dispatcher is run from `/Projects/dispatcher` or `/Projects/dispatcher/main`.
- New worktrees default to `/Projects/{repo_name}/{branch_name}`.
- Dispatcher state and logs stay under the dispatcher directory by default.
- `--poll-interval 120` chooses the delay between polling cycles, in seconds.
  It can also be set with `DISPATCHER_POLL_INTERVAL_SECONDS`.
- `--once` runs a single polling cycle and exits.
- `--daemon` runs the async worker queue instead of the simple long-polling
  loop.
- `--max-workers 3` sets the daemon worker count.
- `--dry-run` writes the stage commands to `.dispatcher/logs/` without running
  Gemini, Claude, or Codex.
- The worktree stage must create the path selected by the dispatcher before
  planning can start.

The generated state file defaults to `.dispatcher/state.json`; issue records
are grouped by repository so `OWNER/REPO#7` does not collide with another
repository's issue `#7`. Logs default to `.dispatcher/logs/` and use matching
repository subdirectories.

By default the process keeps running and polls every 120 seconds. A failed
polling cycle is printed to stderr, then the dispatcher waits for the next
interval and tries again. Press Ctrl-C to stop the process.

Daemon mode keeps the same polling source and stage runners, but enqueues
unseen issues into an `asyncio` worker pool so multiple issue pipelines can run
at the same time. Worker pipelines run through a LangGraph state graph:
worktree creation, planning, build, parallel plan/code-quality reviews,
conditional build retry, and PR opening.

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py --daemon --max-workers 3
```

Redis-backed daemon mode polls every repository currently registered in Redis:

```bash
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run python main.py --daemon
```

Issue state is terminal once a record exists, including `failed` records. The
poller will not automatically retry failed issues; clear or edit the relevant
entry in `.dispatcher/state.json` before reprocessing an issue.

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
