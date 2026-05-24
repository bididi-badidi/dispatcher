from __future__ import annotations

from typing import Any, Protocol

from dispatcher.models import IssueState


class StateBackend(Protocol):
    def get(self, repo: str, issue_number: int) -> dict[str, Any] | None: ...

    def upsert(self, repo: str, state: IssueState) -> None: ...

    def list_issue_states(self, repo: str) -> list[dict[str, Any]]: ...
