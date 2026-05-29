# Operational Scripts

Common commands for managing the dispatcher and its tracked repositories.

## Redis: manage tracked repositories

The `dispatcher-repos` tool is the supported way to add and remove repositories
from the dispatcher's Redis tracking set.

```bash
# Add a repository to poll
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run dispatcher-repos add OWNER/REPO

# List all tracked repositories
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run dispatcher-repos list

# Stop polling a repository
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run dispatcher-repos remove OWNER/REPO
```

## Redis: inspect and clear issue state

Issue state is terminal once a record exists, including `failed` records. The
poller will not automatically retry a failed issue. Delete the Redis key to
allow the issue to be reprocessed:

```bash
# Delete a single issue record
redis-cli DEL 'dispatcher:state:OWNER/REPO:123'

# Inspect the current state of an issue
redis-cli GET 'dispatcher:state:OWNER/REPO:123'

# List all tracked issue keys for a repository
redis-cli KEYS 'dispatcher:state:OWNER/REPO:*'
```

## Starting the daemon

Single-repo daemon (no Redis):

```bash
DISPATCHER_REPO=OWNER/REPO uv run python main.py --daemon --max-workers 3
```

Redis-backed daemon (polls all registered repositories):

```bash
DISPATCHER_REDIS_URL=redis://localhost:6379/0 uv run python main.py --daemon
```

## Local JSON state (single-repo fallback)

When Redis is not configured, state is stored in `.dispatcher/state.json`. To
reprocess a failed or completed issue, remove its entry from that file before
the next polling cycle.
