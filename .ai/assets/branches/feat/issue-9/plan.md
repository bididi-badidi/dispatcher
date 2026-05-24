# Redis Integration Plan — Issue #9

## Context

**Issue:** feat: Redis integration for dynamic repo tracking and shared state

The dispatcher currently locks to a single GitHub repository via the `--repo` CLI flag, and persists all issue state to a local `.dispatcher/state.json` file. Both constraints prevent multi-repo and multi-instance deployments.

This plan replaces `--repo` with a Redis-backed repo registry and makes the state store pluggable so Redis or local JSON can back it transparently.

---

## Architecture

### Before (current)

```
CLI (--repo owner/name)
         │
         ▼
     Config.repo ──────────────────────► list_triggered_issues(config)
                                                      │
         ▼                                            ▼
     StateStore                             Single GitHub repo polled
   (.dispatcher/state.json)
```

### After (target)

```
DISPATCHER_REDIS_URL ──► RedisStateStore ──► dispatcher:repos (Set)
          │                     │                      │
          │           ┌─────────┘            ┌─────────▼──────────┐
          │           │    state backend      │  repo list refresh  │
          │           │    (pluggable)        │  (every N seconds)  │
          │           ▼                       ▼
          │     dispatcher:state              list_triggered_issues(repo)
          │       :{repo}:{number}            (per-repo, concurrent)
          │
DISPATCHER_REPO ──────────────────────► (single-repo fallback; no Redis needed)
          │
          ▼
     LocalStateStore (.dispatcher/state.json)
```

**Fallback chain:**

1. `DISPATCHER_REDIS_URL` set → Redis-backed repo list + Redis state store
2. `DISPATCHER_REPO` set (no Redis) → single-repo, local JSON state store (existing behaviour)
3. Neither set → error on startup with a clear message

---

## New & Modified Files

### New: `dispatcher/redis_store.py`

Central Redis integration module. Wraps `redis-py` (`redis[hiredis]` for performance).

```python
class RedisStateStore:
    """Redis-backed replacement for StateStore."""

    def __init__(self, url: str)
    def get_repos(self) -> list[str]           # SMEMBERS dispatcher:repos
    def get(self, repo: str, issue_number: int) -> IssueState | None
    def upsert(self, repo: str, state: IssueState) -> None
    def close(self) -> None                    # redis.close()

# Key helpers (module-level)
_REPOS_KEY = "dispatcher:repos"
_state_key = lambda repo, n: f"dispatcher:state:{repo}:{n}"
```

**Redis key details:**

| Operation | Command | Notes |
|-----------|---------|-------|
| List repos | `SMEMBERS dispatcher:repos` | Returns `set[bytes]` → decode → `list[str]` |
| Read state | `GET dispatcher:state:{repo}:{n}` | JSON string → `IssueState` via `dacite` or manual |
| Write state | `SET dispatcher:state:{repo}:{n} <json>` | `json.dumps(asdict(state))` |

Connection pooling: use `redis.from_url(url, decode_responses=True)` — simpler than raw client, handles reconnect.

Error surface: wrap `redis.exceptions.RedisError` at `get_repos()` and state ops. Let callers decide whether to fall back or abort — do not silently swallow errors inside this module.

### New: `dispatcher/state_backend.py`

Thin protocol to make the state store pluggable:

```python
from typing import Protocol

class StateBackend(Protocol):
    def get(self, repo: str, issue_number: int) -> IssueState | None: ...
    def upsert(self, repo: str, state: IssueState) -> None: ...
```

`StateStore` (local JSON) already satisfies this. `RedisStateStore` will satisfy it too. No base class needed — just the protocol for type-checking.

### Modified: `dispatcher/models.py`

Add Redis fields to `Config`:

```python
@dataclass(frozen=True)
class Config:
    # existing fields (repo becomes Optional — see below) ...
    repo: str | None = None                     # None when Redis supplies repo list
    redis_url: str | None = None                # DISPATCHER_REDIS_URL
    redis_poll_interval: int = 60               # DISPATCHER_REDIS_POLL_INTERVAL
```

`repo: str | None` — callers that assumed `config.repo` is always set will need updates (see `dispatcher/github.py`, `dispatcher/pipeline.py`, `dispatcher/queue.py`).

### Modified: `dispatcher/config.py`

**Remove** `--repo` argparse argument.

**Add** new env-var bindings:

```python
redis_url = os.getenv("DISPATCHER_REDIS_URL")                  # None if unset
redis_poll_interval = int(os.getenv("DISPATCHER_REDIS_POLL_INTERVAL", "60"))
repo = os.getenv("DISPATCHER_REPO")                            # single-repo fallback
```

**Validation** (new `validate_config(config)` call at end of `build_config`):

```python
def validate_config(config: Config) -> None:
    if config.redis_url is None and config.repo is None:
        raise SystemExit(
            "error: set DISPATCHER_REDIS_URL (Redis mode) "
            "or DISPATCHER_REPO (single-repo fallback)"
        )
```

No `--repo` positional/optional arg in the argparse definition.

### Modified: `dispatcher/github.py`

Change signature of `list_triggered_issues`:

```python
# Before
def list_triggered_issues(config: Config) -> list[Issue]:
    # uses config.repo

# After
def list_triggered_issues(config: Config, repo: str) -> list[Issue]:
    # repo is always explicit
```

Callers (single-repo polling loop and daemon poller) pass the repo explicitly. This also enables per-repo concurrent calls in daemon mode.

### Modified: `dispatcher/cli.py`

**Polling loop** (single-repo, non-daemon):

```python
def run_once(config: Config, store: StateBackend) -> bool:
    repo = config.repo          # guaranteed non-None in single-repo mode (validation ensures this)
    issues = list_triggered_issues(config, repo)
    ...

def run_polling_loop(config: Config, store: StateBackend, sleep=time.sleep) -> None:
    while True:
        run_once(config, store)
        sleep(config.poll_interval_seconds)
```

**Startup backend selection** (in `main`):

```python
def main(argv=None) -> int:
    config = build_config(argv)

    if config.redis_url:
        from dispatcher.redis_store import RedisStateStore
        store = RedisStateStore(config.redis_url)
    else:
        store = StateStore(config.paths.state_file)

    if config.once:
        run_once(config, store)
        return 0
    if config.daemon:
        return _run_daemon(config, store)
    try:
        run_polling_loop(config, store)
    except KeyboardInterrupt:
        return 130
    return 0
```

### Modified: `dispatcher/queue.py` — `Dispatcher` class

The daemon poller must iterate over a dynamic repo list instead of a fixed `config.repo`.

```python
class Dispatcher:
    def __init__(self, config: Config, store: StateBackend, max_workers: int = 3)

    async def _poller(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            repos = self._get_repos()       # Redis set or [config.repo]
            for repo in repos:
                await self._enqueue_triggered_issues(repo)
            await asyncio.sleep(config.poll_interval_seconds)

    def _get_repos(self) -> list[str]:
        if isinstance(self._store, RedisStateStore):
            try:
                return self._store.get_repos()
            except RedisError:
                print("warn: redis unavailable, skipping repo refresh", file=sys.stderr)
                return []
        # single-repo fallback
        return [self._config.repo] if self._config.repo else []
```

The Redis poll interval (`config.redis_poll_interval`) is separate from the GitHub poll interval (`config.poll_interval_seconds`). The simplest safe implementation: refresh repos every GitHub poll cycle. A dedicated Redis refresh timer can be added later.

**Deduplication** across repos: `_in_flight` becomes `set[tuple[str, int]]` (repo, issue_number) pairs instead of `set[int]`.

### Modified: `dispatcher/pipeline.py` and `dispatcher/async_pipeline.py`

`first_unstarted_issue(issues, repo, store)` — already takes `repo` explicitly. No change needed here unless `StateStore.get()` signature differs. Verify the `StateBackend` protocol is satisfied by both backends.

### Modified: `dispatcher/__init__.py`

Export `RedisStateStore` and `StateBackend`:

```python
from dispatcher.redis_store import RedisStateStore
from dispatcher.state_backend import StateBackend
```

### New: `tests/test_redis_store.py`

Unit tests using `unittest.mock.MagicMock` to mock the `redis` client (no real Redis needed):

| Test | Verifies |
|------|---------|
| `test_get_repos_returns_decoded_set` | `SMEMBERS` result decoded to `list[str]` |
| `test_get_repos_empty_set` | Empty set → empty list (guard against `list_triggered_issues` with no repos) |
| `test_get_returns_none_when_missing` | `GET` returns `None` → `store.get()` returns `None` |
| `test_get_deserialises_issue_state` | Valid JSON → `IssueState` with all fields |
| `test_upsert_serialises_and_writes` | `IssueState` → JSON → `SET` called with correct key |
| `test_get_repos_redis_error_propagates` | `RedisError` is not swallowed — caller decides |
| `test_fallback_local_store_used_when_no_redis_url` | `main()` with no `DISPATCHER_REDIS_URL` creates `StateStore` not `RedisStateStore` |
| `test_list_triggered_issues_skips_empty_repo_list` | Empty repo list → no `gh` subprocess calls |

### Modified: `tests/test_config.py`

- Remove tests asserting `--repo` is a valid/required argument
- Add test: `DISPATCHER_REDIS_URL` → `config.redis_url` set
- Add test: `DISPATCHER_REPO` → `config.repo` set (single-repo fallback)
- Add test: neither set → `SystemExit` with clear message

### Modified: `tests/test_cli.py`

- Update `make_config()` helper / fixtures — `repo` is now `None` when `redis_url` is set
- Update polling loop tests to pass `repo` explicitly to `list_triggered_issues`

### Modified: `tests/helpers.py`

Update `make_config()` to default `repo=None, redis_url=None` so existing tests still work (single-repo tests should pass `repo="owner/repo"`).

---

## Dependency

Add `redis[hiredis]` to `pyproject.toml`:

```toml
[project]
dependencies = [
    "langgraph>=1.0.4",
    "redis[hiredis]>=5.0",
]
```

`hiredis` is a C parser that speeds up bulk operations — worth including since `SMEMBERS` on a large repo set is the hot path.

---

## Migration / Fallback Behaviour

| Configuration | Repo source | State backend |
|---------------|-------------|---------------|
| `DISPATCHER_REDIS_URL` set | Redis `dispatcher:repos` Set | Redis `dispatcher:state:*` keys |
| `DISPATCHER_REPO` set (no Redis URL) | Env var value | Local `.dispatcher/state.json` |
| Neither set | — | Error on startup |

The fallback preserves 100% backward compatibility: existing single-repo setups only need to rename `--repo owner/name` to `DISPATCHER_REPO=owner/name`.

---

## State Transitions (unchanged)

The `IssueState` status lifecycle is identical. Redis just stores the same JSON payload at a different address.

---

## Deduplication & Concurrent Safety

- Single instance: `_in_flight: set[tuple[str, int]]` prevents double-processing within one daemon.
- Multiple instances: Redis `SET NX` (set-if-not-exists) provides a distributed lock:
  ```python
  # In RedisStateStore.upsert — only write terminal state if no other instance claimed it
  # Use redis.set(key, value, nx=True) for "started" status to avoid races
  ```
  This is a Phase 2 concern — the issue's acceptance criteria do not require it, but the architecture must not preclude it.

---

## Acceptance Criteria → Implementation Mapping

| Acceptance criterion | Implementation |
|----------------------|----------------|
| Reads `dispatcher:repos` on startup, refreshes every N seconds | `Dispatcher._poller()` calls `_get_repos()` → `RedisStateStore.get_repos()` each cycle |
| Adding/removing from `dispatcher:repos` takes effect within one cycle | Repo list fetched fresh each poll cycle (no caching) |
| `IssueState` written to/read from Redis | `RedisStateStore.get()` / `upsert()` |
| Multiple instances share state via Redis | Both instances use same Redis keys; `SET NX` guards "started" write |
| `DISPATCHER_REPO` works as single-repo fallback | `config.repo` set from env; `LocalStateStore` used |
| Local JSON fallback when Redis not configured | `main()` selects `StateStore` when `config.redis_url is None` |
| `--repo` CLI argument removed | Removed from argparse; env var only |
| Default poll interval 60 s | `DISPATCHER_REDIS_POLL_INTERVAL` defaults to `"60"` |
| Unit tests for Redis fetch, state read/write, fallbacks | `tests/test_redis_store.py` (8 tests above) |

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `dispatcher/redis_store.py` | **New** | `RedisStateStore` — Redis-backed repo list + state store |
| `dispatcher/state_backend.py` | **New** | `StateBackend` protocol for type-safe pluggability |
| `dispatcher/models.py` | Modify | `Config.repo → str \| None`, add `redis_url`, `redis_poll_interval` |
| `dispatcher/config.py` | Modify | Remove `--repo` arg; add `DISPATCHER_REDIS_URL`, `DISPATCHER_REDIS_POLL_INTERVAL`, `DISPATCHER_REPO` env vars; add `validate_config()` |
| `dispatcher/github.py` | Modify | `list_triggered_issues(config, repo)` — explicit repo param |
| `dispatcher/cli.py` | Modify | Backend selection in `main()`; pass `repo` explicitly |
| `dispatcher/queue.py` | Modify | `_get_repos()` helper; `_in_flight` keyed by `(repo, issue_number)` |
| `dispatcher/__init__.py` | Modify | Export `RedisStateStore`, `StateBackend` |
| `pyproject.toml` | Modify | Add `redis[hiredis]>=5.0` dependency |
| `tests/test_redis_store.py` | **New** | 8 unit tests (mocked Redis client) |
| `tests/test_config.py` | Modify | Remove `--repo` tests; add Redis/fallback/validation tests |
| `tests/test_cli.py` | Modify | Update fixtures for optional `repo`; backend-selection tests |
| `tests/helpers.py` | Modify | `make_config()` defaults `repo=None, redis_url=None` |
