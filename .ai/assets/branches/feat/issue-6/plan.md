# feat/issue-6 — GEMINI.md sync with CLAUDE.md

## Issue

**bididi-badidi/dispatcher#6** — "GEMINI.md missing"
> "push back gemini.md with same instructions as claude.md"
> Labels: `documentation`, `automate`

---

## Current State Analysis

| File        | Version | Last Updated | Notes                          |
| ----------- | ------- | ------------ | ------------------------------ |
| `CLAUDE.md` | 1.0.1   | 2026-04-22   | Canonical instruction source   |
| `GEMINI.md` | 1.0.1   | 2026-04-22   | Byte-for-byte identical to CLAUDE.md |
| `AGENTS.md` | 1.1.0   | 2026-05-11   | Codex-specific; newer version, slightly condensed format |

`diff CLAUDE.md GEMINI.md` → **no diff** on `main` and `feat/issue-6`.

`GEMINI.md` was introduced in the initial commit (`a8efc5e feat: add local issue dispatcher`) and has never drifted from `CLAUDE.md`. The issue was likely filed when the file was observed as absent in an intermediate working state, and has since been restored.

---

## Goal

Ensure `GEMINI.md` permanently stays in sync with `CLAUDE.md` so future updates to one are reflected in the other. The `automate` label signals that a sync mechanism (not just a one-time copy) is expected.

---

## Implementation Plan

### Step 1 — Verify parity (already done)

Confirm `GEMINI.md` matches `CLAUDE.md` at HEAD. ✅ No diff.

### Step 2 — Add a sync check script

Create `scripts/sync_agent_docs.sh`:

- Diffs `CLAUDE.md` → `GEMINI.md`.
- Exits non-zero (with a clear message) if they diverge.
- `--fix` flag copies `CLAUDE.md` over `GEMINI.md` in-place.
- `--dry-run` flag prints what would change without writing.

```
scripts/sync_agent_docs.sh [--fix] [--dry-run]
```

### Step 3 — Wire into CI (GitHub Actions)

Add `.github/workflows/sync-agent-docs.yml`:

- Trigger: `push` to any branch when `CLAUDE.md` or `GEMINI.md` changes.
- Job: run `scripts/sync_agent_docs.sh` (no `--fix`); fail the PR if they differ.
- This prevents future drift without requiring manual upkeep.

### Step 4 — Update version metadata in GEMINI.md

Bump `GEMINI.md` frontmatter to reflect the new `automate` policy:

```yaml
version: 1.1.0
last_updated: 2026-05-24
changelog:
  - 1.1.0: Add sync-check CI enforcement (issue #6)
  - 1.0.1: Compress section 0.1-0.3 to one file hygiene section
  - 1.0.0: Initial release
```

Apply the same bump to `CLAUDE.md` to keep version parity.

---

## Files Changed

| Action | Path |
| ------ | ---- |
| New    | `scripts/sync_agent_docs.sh` |
| New    | `.github/workflows/sync-agent-docs.yml` |
| Edit   | `GEMINI.md` (version bump only) |
| Edit   | `CLAUDE.md` (version bump only) |

---

## Out of Scope

- Merging `AGENTS.md` (v1.1.0) with `CLAUDE.md`/`GEMINI.md` — `AGENTS.md` targets Codex and intentionally uses a condensed format.
- Automated rewriting of `GEMINI.md` content — the file should remain a direct copy of `CLAUDE.md`, not a generated derivative.

---

## Acceptance Criteria

- [x] `diff CLAUDE.md GEMINI.md` produces no output.
- [x] `scripts/sync_agent_docs.sh` exits 0 when files match, non-zero when they differ.
- [x] CI workflow fails a PR that introduces a diff between `CLAUDE.md` and `GEMINI.md`.
- [x] `GEMINI.md` frontmatter version ≥ `1.1.0`.
