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

### Troubleshooting: `detect-secrets` modified `.secrets.baseline`

If pre-commit fails locally or in CI with:

```text
Detect secrets...........................................................Failed
- hook id: detect-secrets
- files were modified by this hook
```

the baseline has drifted, usually because line numbers of a previously flagged
literal moved or a new high-entropy literal landed. Recover with:

```bash
uv run detect-secrets scan --exclude-files '^(\.agents/|\.env|\.venv/|\.dispatcher/|\.ai/assets/session_notes\.md)$' > .secrets.baseline
git add .secrets.baseline
```

If the rescan adds a `results` entry for a literal you know is not a secret,
such as a test fixture, fake environment value, or sample payload, annotate the
source line with `# pragma: allowlist secret` and rescan. Real credentials must
never be committed; rotate them and add them to `.env`, which is gitignored.

## Branching Strategy

Feature branches merge into `dev`; only `dev` is allowed to merge into `main`.

```text
feat/*, fix/*, chore/*, ci/* -> dev
dev                           -> main
```

- Open feature, fix, chore, and CI branches against `dev`.
- Open `dev` to `main` pull requests to cut a release.
- Use conventional commit style for commit messages and pull request titles,
  for example `ci: add branch policy check`.

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
- Required status checks:
  - `branch-policy`
  - `lint / python 3.11`
  - `test / python 3.11`
- Dismiss stale reviews when new commits are pushed.
- Restrict direct pushes for non-admin users.

For `dev`:

- Require a pull request before merging.
- Required status checks:
  - `lint / python 3.11`
  - `test / python 3.11`

### Hotfix Exception

If a hotfix must bypass the `dev` to `main` flow, a maintainer can temporarily
relax the required `branch-policy` check in `main` protection, merge the hotfix
pull request, then re-enable the check. Record the reason in the hotfix pull
request description.
