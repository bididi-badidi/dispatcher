#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/sync_agent_docs.sh [--fix] [--dry-run]

Checks that GEMINI.md is byte-for-byte identical to CLAUDE.md.

Options:
  --fix      Copy CLAUDE.md over GEMINI.md when they differ.
  --dry-run  Show what would change without writing files.
USAGE
}

fix=false
dry_run=false

while (($#)); do
  case "$1" in
    --fix)
      fix=true
      ;;
    --dry-run)
      dry_run=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
source_file="$repo_root/CLAUDE.md"
target_file="$repo_root/GEMINI.md"

if [[ ! -f "$source_file" ]]; then
  echo "Missing source file: CLAUDE.md" >&2
  exit 1
fi

if [[ ! -f "$target_file" ]]; then
  echo "Missing target file: GEMINI.md" >&2
  exit 1
fi

if cmp -s "$source_file" "$target_file"; then
  echo "CLAUDE.md and GEMINI.md are in sync."
  exit 0
fi

echo "CLAUDE.md and GEMINI.md differ." >&2

if $fix; then
  if $dry_run; then
    echo "Would copy CLAUDE.md to GEMINI.md." >&2
    diff -u "$target_file" "$source_file" || true
    exit 1
  fi

  cp "$source_file" "$target_file"
  echo "Copied CLAUDE.md to GEMINI.md."
  exit 0
fi

echo "Run scripts/sync_agent_docs.sh --fix to update GEMINI.md." >&2
diff -u "$target_file" "$source_file" || true
exit 1
