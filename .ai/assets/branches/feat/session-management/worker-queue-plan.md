# Worker Queue System Plan

## Context

The dispatcher currently processes one issue at a time synchronously — `run_once()` picks one unstarted issue, runs the full 3-stage pipeline (worktree, plan, build) via blocking `subprocess.run()`, then sleeps. This means long agent runs (minutes to hours) block all other issues.

This plan adds an async worker queue so that up to 3 issues can be processed concurrently, with clean lifecycle management and observable state for a future dashboard.

**Scope:** Single repo per daemon instance. Run multiple daemon processes for multiple repos.

---

## Architecture

```
                         ┌──────────────────────┐
                         │   Dispatcher.run()    │
                         │   (asyncio event loop)│
                         └──────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
     ┌────────▼───────┐ ┌──────▼──────┐   ┌──────▼──────┐
     │    Poller       │ │  Worker 0   │   │  Worker 1   │  ... Worker N
     │ (polls gh CLI)  │ │  (pipeline) │   │  (pipeline) │
     │ enqueues tasks  │ │  async sub  │   │  async sub  │
     └────────┬───────┘ └──────▲──────┘   └──────▲──────┘
              │                │                  │
              └────► asyncio.Queue ◄──────────────┘
```

**Core primitives (all stdlib):**
- `asyncio.Queue` — task queue (maxsize=20, matching gh issue list limit)
- Fixed pool of N worker coroutines (default 3) — each loops on `queue.get()`
- `asyncio.Event` — shutdown signal
- `asyncio.create_subprocess_exec` — non-blocking subprocess execution

---

## New & Modified Files

### New: `dispatcher/queue.py`

The central orchestrator module.

```python
# Key types
class TaskType(enum.Enum):
    FRESH = "fresh"       # Full pipeline: worktree → plan → build
    REVIEW = "review"     # Skip worktree: plan → build (future use)

@dataclass
class Task:
    repo: str
    issue: Issue
    task_type: TaskType = TaskType.FRESH

@dataclass(frozen=True)
class QueueSnapshot:
    pending: tuple[Task, ...]
    active: dict[int, Task | None]   # worker_id → current task or None
    completed_count: int
    failed_count: int

class Dispatcher:
    def __init__(self, config: Config, store: StateStore, max_workers: int = 3)
    async def run(self)                    # Entry point — starts poller + workers
    async def _poller(self, shutdown)      # Polls gh, enqueues new Tasks
    async def _worker(self, id, shutdown)  # Loops on queue.get(), runs pipeline
    def enqueue_review(self, issue)        # Public: re-queue for PR review (future)
    def snapshot(self) -> QueueSnapshot    # Observable state for dashboard (future)
```

**Poller logic:**
1. Call `list_triggered_issues(config)` via `asyncio.to_thread()` (gh CLI is sync)
2. Filter out issues already in `_in_flight` set or in state store with terminal status
3. Enqueue remaining as `Task(FRESH)`
4. Sleep `config.poll_interval_seconds`, repeat

**Worker logic:**
1. `task = await queue.get()`
2. If `None` sentinel → break (shutdown)
3. Call `async_run_pipeline(task, config, store, worker_id, shutdown_event)`
4. On completion/failure: remove from `_in_flight`, call `queue.task_done()`

**Deduplication:**
- `_in_flight: set[int]` tracks issue numbers currently queued or being processed
- Updated on enqueue (add) and worker completion (discard)
- Poller also checks `store.get()` for issues with existing state

**Shutdown:**
- Signal handler (`SIGINT`, `SIGTERM`) sets `asyncio.Event`
- Poller stops polling
- Sentinel `None` values pushed to queue to unblock workers
- Workers check shutdown event between pipeline stages — if set, mark state as `failed` with "shutdown requested" and exit cleanly

### New: `dispatcher/async_runners.py`

Async subprocess execution that reuses existing `AgentRunner` methods for prompt/command/env building but replaces `subprocess.run` with `asyncio.create_subprocess_exec`.

```python
async def async_run_stage(
    name: str,
    runner: AgentRunner,
    issue: Issue,
    config: Config,
    worktree: Path,
    branch: str,
) -> None:
    # Reuse runner.prompt(), runner.cwd(), runner.command(), runner.env(), runner.stdin()
    # These are all synchronous — only the execution changes.
    prompt = runner.prompt(issue, config, worktree, branch)
    cwd = runner.cwd(config, worktree)
    command = runner.command(prompt, cwd)
    runner._validate_command(command)

    # ... log setup identical to AgentRunner.run() ...

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=runner.env(),
        stdin=asyncio.subprocess.PIPE if runner.stdin(prompt) else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdin_bytes = runner.stdin(prompt).encode() if runner.stdin(prompt) else None
    stdout, stderr = await proc.communicate(input=stdin_bytes)

    # Write log, check returncode — same logic as AgentRunner.run()
```

**Why not modify `AgentRunner.run()`:** Keep the sync path intact for `--once` mode and backward compatibility. The async module is a parallel execution path, not a replacement.

### New: `dispatcher/async_pipeline.py`

Async version of `run_pipeline()`:

```python
async def async_run_pipeline(
    task: Task,
    config: Config,
    store: StateStore,
    worker_id: int,
    shutdown_event: asyncio.Event,
) -> IssueState:
```

- Mirrors `pipeline.py:run_pipeline()` logic
- Calls `async_run_stage()` instead of `run_stage()`
- Checks `shutdown_event.is_set()` between stages
- Skips worktree stage when `task.task_type == TaskType.REVIEW`
- Sets `worker_id` on `IssueState` during execution, clears on completion

### Modified: `dispatcher/models.py`

Add fields to existing dataclasses:

```python
@dataclass(frozen=True)
class Config:
    # ... existing fields ...
    daemon: bool = False
    max_workers: int = 3

@dataclass
class IssueState:
    # ... existing fields ...
    task_type: str = "fresh"        # "fresh" or "review"
    worker_id: int | None = None    # Which worker slot is processing
```

Defaults ensure backward compatibility with existing serialized state.

### Modified: `dispatcher/config.py`

Add CLI arguments:

```python
parser.add_argument("--daemon", action="store_true",
    help="Run as async daemon with concurrent worker queue.")
parser.add_argument("--max-workers", type=int, default=3,
    help="Maximum concurrent pipelines in daemon mode (default: 3).")
```

### Modified: `dispatcher/cli.py`

Add daemon mode branch:

```python
def main(argv=None) -> int:
    config = build_config(argv)
    store = StateStore(config.paths.state_file)

    if config.once:
        run_once(config, store)
        return 0

    if config.daemon:                          # NEW
        return _run_daemon(config, store)      # NEW

    try:
        run_polling_loop(config, store)
    except KeyboardInterrupt:
        return 130
    return 0

def _run_daemon(config: Config, store: StateStore) -> int:
    import asyncio
    from dispatcher.queue import Dispatcher
    try:
        asyncio.run(Dispatcher(config, store).run())
    except KeyboardInterrupt:
        print("Stopping dispatcher daemon.")
        return 130
    return 0
```

### Modified: `dispatcher/__init__.py` and `main.py`

Export new public symbols: `Dispatcher`, `TaskType`, `Task`, `QueueSnapshot`.

---

## State Transitions

```
              FRESH task                    REVIEW task
              ─────────                     ───────────
  (enqueue) → queued                  (enqueue) → queued
           → started                           → started
           → worktree_created                  │ (skip worktree)
           → planned                           → planned
           → built ──── (dequeue)              → built ──── (dequeue)

  Any stage failure → failed ──── (dequeue)
  Shutdown between stages → failed (error="shutdown requested") ──── (dequeue)
```

**Dequeue** = remove from `_in_flight` set. The state record persists in `state.json` with terminal status.

---

## Thread Safety

`StateStore` operations are synchronous and fast (small JSON file). Since `asyncio` runs on a single thread, concurrent `store.upsert()` calls from different workers cannot interleave mid-call — no lock needed. The existing implementation is safe as-is.

---

## Future Considerations

### PR Review Re-queue (Phase 3)
- `Dispatcher.enqueue_review(issue)` creates `Task(REVIEW)` and puts it on the queue
- Review tasks skip worktree creation — the worktree already exists from the initial run
- The review poller (future) watches for new PR review comments via `gh pr view`
- `IssueState.status` resets from `built` → `queued` when re-queued for review

### Dashboard (future)
- `Dispatcher.snapshot()` returns a frozen `QueueSnapshot` with pending/active/completed state
- A future `aiohttp` or similar handler can expose this as JSON over HTTP
- The state file (`state.json`) is also readable for simpler dashboards

---

## Verification

1. **Unit tests** (`tests/test_queue.py`):
   - Task enqueueing and deduplication (same issue not queued twice)
   - Worker picks up tasks and runs async pipeline
   - Review tasks skip worktree stage
   - Shutdown sentinel causes clean worker exit
   - Snapshot returns correct counts

2. **Dry-run integration test**:
   ```bash
   uv run python main.py --repo owner/repo --daemon --dry-run --max-workers 2
   ```
   Verify: poller discovers issues, workers log dry-run commands, state transitions appear in `state.json`

3. **Manual test** with a real tracking repo:
   ```bash
   uv run python main.py --repo bididi-badidi/testing-coding-assistant --daemon --max-workers 3
   ```
   Create 3+ issues with `automate` label, verify concurrent processing

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `dispatcher/queue.py` | **New** | `Dispatcher`, `Task`, `TaskType`, `QueueSnapshot` |
| `dispatcher/async_runners.py` | **New** | `async_run_stage()` — async subprocess execution |
| `dispatcher/async_pipeline.py` | **New** | `async_run_pipeline()` — async pipeline orchestration |
| `dispatcher/models.py` | Modify | Add `daemon`, `max_workers` to Config; `task_type`, `worker_id` to IssueState |
| `dispatcher/config.py` | Modify | Add `--daemon`, `--max-workers` CLI args |
| `dispatcher/cli.py` | Modify | Add daemon mode branch |
| `dispatcher/__init__.py` | Modify | Export new symbols |
| `main.py` | Modify | Re-export new symbols |
| `tests/test_queue.py` | **New** | Unit tests for queue system |
