from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import redis

from dispatcher.models import IssueState

_REPOS_KEY = "dispatcher:repos"


def _state_key(repo: str, issue_number: int) -> str:
    return f"dispatcher:state:{repo}:{issue_number}"


class RedisStateStore:
    """Redis-backed replacement for the local JSON state store."""

    def __init__(self, url: str) -> None:
        self._client = redis.from_url(url, decode_responses=True)

    def get_repos(self) -> list[str]:
        repos = self._client.smembers(_REPOS_KEY)
        return sorted(_decode(value) for value in repos)

    def get(self, repo: str, issue_number: int) -> dict[str, Any] | None:
        payload = self._client.get(_state_key(repo, issue_number))
        if payload is None:
            return None
        data = json.loads(_decode(payload))
        return dict(data)

    def upsert(self, repo: str, state: IssueState) -> None:
        self._client.set(_state_key(repo, state.number), json.dumps(asdict(state)))

    def close(self) -> None:
        self._client.close()


def _decode(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
