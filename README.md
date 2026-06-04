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

On startup, the dispatcher loads environment defaults from a `.env` file in the
current dispatcher directory. Shell exports take precedence. Start from
`.env.example` when creating a local `.env` file.

Useful options:

- `--label automate` chooses the trigger label.
- `DISPATCHER_OPUS_LABEL=automate:opus` chooses the secondary label that
  escalates only the planning stage to Opus.
- `DISPATCHER_OPUS_MODEL=claude-opus-4-7` chooses the Claude model used when
  the Opus escalation label is present.
- `DISPATCHER_REDIS_URL=redis://...` enables Redis-backed repository tracking
  and shared issue state. Repositories are read from the `dispatcher:repos`
  Redis set.
- `DISPATCHER_REPO=OWNER/REPO` keeps the single-repository local JSON fallback
  when Redis is not configured.
- `--base-branch main` chooses the branch used for the worktree.
- The base checkout defaults to `/Projects/{repo_name}/main` regardless of
  where the dispatcher is run.
- New worktrees default to `/Projects/{repo_name}/{branch_name}`.
- `DISPATCHER_PROJECTS_DIR` changes the repo/worktree root parent; it is
  independent of `DISPATCHER_ROOT_DIR`.
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

### Session log uploads (optional)

Set `DISPATCHER_SESSION_LOG_BUCKET` to upload dispatcher session logs after
each stage and after each issue run. When unset, the dispatcher skips S3 and
writes local fallback copies under `.dispatcher/logs/.session_logs/`. The
canonical object key is `<prefix>/<owner>/<repo>/issue_<number>.log`;
individual stage logs use
`<prefix>/<owner>/<repo>/issue_<number>-<stage>.log`.

`boto3` reads standard AWS credential and region variables such as
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION`.
`DISPATCHER_SESSION_LOG_PREFIX` defaults to `logs` and can prepend a bucket
prefix such as `dispatcher-prod/`. `AWS_S3_LOG_BUCKET` and
`AWS_S3_LOG_KEY_PREFIX` still work as deprecated fallbacks for one release.
Uploads run in the background; upload failures are logged as warnings and do
not fail the issue pipeline.

The generated state file defaults to `.dispatcher/state.json`; issue records
are grouped by repository so `OWNER/REPO#7` does not collide with another
repository's issue `#7`. Logs default to `.dispatcher/logs/` and use matching
repository subdirectories.

By default the process keeps running and polls every 120 seconds. A failed
polling cycle is logged with its traceback, then the dispatcher waits for the
next interval and tries again. Press Ctrl-C to stop the process.

Daemon mode keeps the same polling source and stage runners, but enqueues
unseen issues into an `asyncio` worker pool so multiple issue pipelines can run
at the same time. Worker pipelines run through a LangGraph state graph:
worktree creation, planning, build, parallel plan/code-quality reviews,
conditional build retry, and PR opening.

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py --daemon
```

Redis-backed daemon — polls all registered repositories:

```bash
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run python main.py --daemon
```

Use `--debug` or `DISPATCHER_DEBUG=1` to log subprocess commands.

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
