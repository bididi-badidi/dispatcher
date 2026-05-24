# Plan: feat/issue-3 — LangGraph Agentic Workflow Integration

**Source:** [GitHub Issue #3](https://github.com/bididi-badidi/dispatcher/issues/3)
**Branch:** `feat/issue-3`
**Labels:** `enhancement`, `architecture`

---

## Summary

Replace the current linear `worktree → plan → build` pipeline (`dispatcher/pipeline.py`, `dispatcher/async_pipeline.py`) with a [LangGraph](https://github.com/langchain-ai/langgraph) state graph that adds:

- A **dual review loop** (plan quality + code quality checked in parallel after each build)
- **Conditional edges** to re-run the build node if either reviewer requests changes
- A **terminal `open_pr` node** (Gemini pushes branch and opens PR)
- An iteration cap to prevent infinite loops

---

## Proposed Workflow

```
[Task Queued]
      │
      ▼
┌─────────────┐
│   Gemini    │  git worktree add for feat/issue-{n}
│  (worktree) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Claude    │  Read issue, write plan.md
│   (plan)    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    Codex    │  Implement changes per plan ◄──────────────────┐
│   (build)   │                                                 │
└──────┬──────┘                                                 │ loop if any
       │                                                        │ reviewer rejects
       ▼                                                        │
┌──────────────────────────────────┐                           │
│         Parallel Review          │                           │
│  ┌──────────────┐ ┌───────────┐  │                           │
│  │ Claude       │ │  Claude   │  │                           │
│  │ (plan-review)│ │  (quality)│  │───────────────────────────┘
│  └──────────────┘ └───────────┘  │
└──────────────┬───────────────────┘
               │ both approved
               ▼
┌─────────────┐
│   Gemini    │  git push + gh pr create --body "Closes #<n>"
│    (pr)     │
└─────────────┘
```

---

## Node Descriptions

| Node | Agent | Responsibility |
|------|-------|----------------|
| `create_worktree` | Gemini | `git worktree add` for `feat/issue-{n}` branch |
| `plan` | Claude | Read issue, write plan to `.ai/assets/branches/<branch>/plan.md` |
| `build` | Codex | Implement changes according to the saved plan |
| `review_plan` | Claude | Verify implementation matches plan; emit `approved` or `changes_requested` |
| `review_quality` | Claude | Check code style, edge cases, test coverage; emit `approved` or `changes_requested` |
| `open_pr` | Gemini | `git push` + `gh pr create --body "Closes #<n>"` |

---

## State Schema

```python
class PipelineState(TypedDict):
    # Issue context (read-only after graph entry)
    issue_number: int
    issue_title: str
    issue_body: str
    issue_url: str
    repo: str                     # "owner/repo"
    base_branch: str

    # Dispatcher config
    project_dir: Path
    max_iterations: int           # default 3; env: DISPATCHER_MAX_ITERATIONS

    # Worktree / branch (written by create_worktree)
    worktree: Path | None
    branch: str | None

    # Plan (written by plan node)
    plan_path: Path | None        # .ai/assets/branches/<branch>/plan.md
    plan_content: str | None

    # Build loop
    build_iteration: int
    build_feedback: str | None    # merged reviewer feedback forwarded to Codex on retry

    # Review verdicts
    plan_review: Literal["approved", "changes_requested"] | None
    plan_review_feedback: str | None
    quality_review: Literal["approved", "changes_requested"] | None
    quality_review_feedback: str | None

    # PR
    pr_url: str | None

    # Terminal
    error: str | None
```

### State flow per node

| Node | Reads | Writes |
|------|-------|--------|
| `create_worktree` | `issue_number`, `repo`, `project_dir`, `base_branch` | `worktree`, `branch` |
| `plan` | `issue_number`, `issue_title`, `issue_body`, `issue_url`, `worktree`, `branch` | `plan_path`, `plan_content` |
| `build` | `plan_content`, `plan_path`, `worktree`, `branch`, `build_feedback`, `build_iteration` | `build_iteration` |
| `review_plan` | `plan_content`, `worktree`, `branch`, `issue_body` | `plan_review`, `plan_review_feedback` |
| `review_quality` | `worktree`, `branch` | `quality_review`, `quality_review_feedback` |
| `router` | `plan_review`, `quality_review`, `build_iteration`, `max_iterations` | `build_feedback` |
| `open_pr` | `issue_number`, `issue_title`, `repo`, `branch`, `base_branch` | `pr_url` |

---

## Graph Edges

```
create_worktree  → plan
plan             → build
build            → [review_plan, review_quality]   (parallel fan-out)
[review_plan, review_quality] → router
router:
  both approved                                         → open_pr
  any changes_requested AND build_iteration < MAX       → build
  build_iteration >= MAX_ITERATIONS                     → fail (set error, stop)
open_pr          → END
```

---

## Files to Change

| File | Change |
|------|--------|
| `dispatcher/langgraph_pipeline.py` | **New** — `StateGraph` with all six nodes |
| `dispatcher/queue.py` | Replace `async_run_pipeline()` call with `langgraph_pipeline()` |
| `dispatcher/prompts.py` | Add `review_plan_prompt` and `review_quality_prompt` templates |
| `dispatcher/models.py` | Add review verdict fields to `IssueState` if needed |
| `dispatcher/constants.py` | Add allowed tools for reviewer Claude instances |
| `dispatcher/pipeline.py` | Kept for backwards compat; no changes required |
| `dispatcher/async_pipeline.py` | Kept for backwards compat; no changes required |
| `pyproject.toml` / `requirements.txt` | Add `langgraph` dependency |

---

## Implementation Notes

1. **Entry point** — `dispatcher/queue.py` calls `langgraph_pipeline(task, config, store)` instead of `async_run_pipeline()`.
2. **Agent runners** — Reuse existing `AgentRunner` subclasses (`GeminiRunner`, `ClaudeRunner`, `CodexRunner`) inside LangGraph node functions. Nodes are thin wrappers.
3. **Parallel review** — Use LangGraph's `Send` API or a `fan_out` pattern to run `review_plan` and `review_quality` concurrently.
4. **Iteration cap** — `MAX_ITERATIONS = 3`, configurable via `DISPATCHER_MAX_ITERATIONS` env var.
5. **State persistence** — Map `PipelineState` fields back to the existing `IssueState` JSON store after each node to preserve the current state file format.
6. **Shutdown** — Thread the existing `asyncio.Event` shutdown signal into the graph's config so nodes can bail early.
7. **Observability** — LangSmith tracing is available for free once `langgraph` is installed; no extra wiring needed.

---

## Acceptance Criteria

- [ ] `dispatcher/langgraph_pipeline.py` defines the `StateGraph` with all six nodes
- [ ] `review_plan` and `review_quality` run concurrently (validated by timing logs)
- [ ] Build loop retries up to `MAX_ITERATIONS` times, then marks issue `failed` with a clear error message
- [ ] PR body contains `Closes #<issue_number>`
- [ ] Existing `IssueState` JSON format preserved (no breaking change)
- [ ] Unit tests cover: happy path, single-retry loop, max-iteration exhaustion, shutdown mid-graph
- [ ] `langgraph` added to `pyproject.toml` / `requirements.txt`

---

## Out of Scope

- Switching to LangGraph's persistence layer (keep existing JSON store)
- Human-in-the-loop review steps
- Supporting agents other than Gemini / Claude / Codex
