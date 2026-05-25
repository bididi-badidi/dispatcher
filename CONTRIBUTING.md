# Contributing

## Local Setup

Use the project-managed Python environment and install development tools before
opening a pull request:

```bash
uv sync --all-groups
uv run pre-commit install
```

Run the same checks that CI runs:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pre-commit run --all-files
uv run pytest -v
```

Pre-commit runs Ruff formatting, Ruff linting, whitespace cleanup, end-of-file
normalisation, and `detect-secrets` checks. If the secrets baseline needs to be
refreshed after a deliberate non-secret change, run:

```bash
uv run detect-secrets scan --exclude-files '^(\.agents/|\.env|\.venv/|\.dispatcher/|\.ai/assets/session_notes\.md)$' > .secrets.baseline
```

Never commit real credentials. Keep local configuration in `.env`, which is
gitignored.

## Branching Strategy

Use short-lived feature branches and open pull requests directly to `main`:

```text
feature/* -> main
```

- Open feature, fix, chore, and CI branches against `main`.
- Use conventional commit style for commit messages and pull request titles,
  for example `ci: add pull request checks`.

## GitHub Issue Template

Use the **Bug or feature** issue form when filing work. Include the motivation,
acceptance criteria, any new environment variables, and migration or fallback
notes when relevant. Apply `automate` only when the dispatcher should pick up
the issue for the local automation pipeline.

## Branch Protection

Branch protection is configured manually in GitHub repository settings after
the first green CI run is available.

For `main`:

- Require a pull request before merging.
- Require status checks for `lint / python 3.11` and `test / python 3.11`.
- Dismiss stale reviews when new commits are pushed.
- Restrict direct pushes for non-admin users.
