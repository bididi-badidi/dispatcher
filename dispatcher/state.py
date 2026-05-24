from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dispatcher.models import IssueState


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"repositories": {}}
        with self.path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def get(self, repo: str, issue_number: int) -> dict[str, Any] | None:
        repositories = self.load().get("repositories", {})
        return repositories.get(repo, {}).get("issues", {}).get(str(issue_number))

    def list_issue_states(self, repo: str) -> list[dict[str, Any]]:
        repositories = self.load().get("repositories", {})
        issues = repositories.get(repo, {}).get("issues", {})
        return [dict(state) for state in issues.values()]

    def upsert(self, repo: str, state: IssueState) -> None:
        data = self.load()
        repository = data.setdefault("repositories", {}).setdefault(repo, {})
        repository.setdefault("issues", {})[str(state.number)] = asdict(state)
        self.save(data)
