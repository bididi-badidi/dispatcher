# Task Archive

- [x] Phase 1 follow-up: encapsulated Codex, Gemini, and Claude subprocess execution under an abstract `AgentRunner`, with provider-specific non-interactive flags, CLI version logging, and rejection of yolo/dangerous bypass flags.
- [x] Phase 1 follow-up: scoped dispatcher issue state and stage logs by repository so matching GitHub issue numbers from multiple repos do not collide.
- [x] Phase 1 follow-up: made the default worktree prompt include the dispatcher-selected branch/path and fail fast when a provider does not create that expected worktree.
- [x] Phase 1 follow-up: fixed default target-repository path resolution when the dispatcher itself is running from a `dispatcher/main` worktree, so sibling repos resolve under `/Projects/{repo_name}` instead of `/Projects/dispatcher/{repo_name}`.
- [x] Phase 1 follow-up: refactored the dispatcher monolith into a modular `dispatcher/` package while preserving `main.py` as the CLI and compatibility import surface.
