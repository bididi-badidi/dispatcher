from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from redis.exceptions import RedisError

from dispatcher.models import IssueState
from dispatcher.redis_store import RedisStateStore


class RedisStateStoreTests(unittest.TestCase):
    def test_get_repos_returns_decoded_set(self) -> None:
        client = MagicMock()
        client.smembers.return_value = {b"owner/one", "owner/two"}

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        self.assertEqual(store.get_repos(), ["owner/one", "owner/two"])
        client.smembers.assert_called_once_with("dispatcher:repos")

    def test_get_repos_empty_set(self) -> None:
        client = MagicMock()
        client.smembers.return_value = set()

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        self.assertEqual(store.get_repos(), [])

    def test_get_returns_none_when_missing(self) -> None:
        client = MagicMock()
        client.get.return_value = None

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        self.assertIsNone(store.get("owner/repo", 9))

    def test_get_deserialises_issue_state_payload(self) -> None:
        client = MagicMock()
        client.get.return_value = json.dumps(
            {
                "number": 9,
                "title": "Redis state",
                "url": "https://example.test/9",
                "status": "built",
                "branch": "feat/issue-9",
                "worktree": "/tmp/repo/feat/issue-9",
                "updated_at": "2026-05-24T00:00:00Z",
                "error": None,
            }
        )

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        self.assertEqual(store.get("owner/repo", 9)["status"], "built")

    def test_upsert_serialises_and_writes(self) -> None:
        client = MagicMock()
        state = IssueState(
            number=9,
            title="Redis state",
            url="https://example.test/9",
            status="built",
            branch="feat/issue-9",
            worktree="/tmp/repo/feat/issue-9",
            updated_at="2026-05-24T00:00:00Z",
        )

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        store.upsert("owner/repo", state)

        key, payload = client.set.call_args.args
        self.assertEqual(key, "dispatcher:state:owner/repo:9")
        self.assertEqual(json.loads(payload)["branch"], "feat/issue-9")

    def test_get_repos_redis_error_propagates(self) -> None:
        client = MagicMock()
        client.smembers.side_effect = RedisError("down")

        with patch("dispatcher.redis_store.redis.from_url", return_value=client):
            store = RedisStateStore("redis://example")

        with self.assertRaises(RedisError):
            store.get_repos()
