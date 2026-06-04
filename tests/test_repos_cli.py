from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dispatcher import repos_cli
from dispatcher.git import BranchLookup


class ReposCliTests(unittest.TestCase):
    def test_add_invokes_store_for_each_repo(self) -> None:
        store = MagicMock()

        with (
            _configured_env(),
            patch.object(repos_cli, "RedisStateStore", return_value=store),
        ):
            exit_code = repos_cli.main(["add", "owner/one", "owner.two/repo-three"])

        self.assertEqual(exit_code, 0)
        store.add_repo.assert_any_call("owner/one")
        store.add_repo.assert_any_call("owner.two/repo-three")
        store.close.assert_called_once_with()

    def test_add_invalid_repo_exits_nonzero(self) -> None:
        with _configured_env(), patch.object(repos_cli, "RedisStateStore") as store:
            with patch("sys.stderr") as stderr:
                exit_code = repos_cli.main(["add", "bad-name"])

        self.assertEqual(exit_code, 2)
        store.assert_not_called()
        stderr.write.assert_any_call(
            "error: invalid repo 'bad-name', expected owner/name"
        )

    def test_list_prints_sorted_store_members(self) -> None:
        store = MagicMock()
        store.get_repos.return_value = ["owner/a", "owner/z"]

        with (
            _configured_env(),
            patch.object(repos_cli, "RedisStateStore", return_value=store),
            patch("builtins.print") as print_,
        ):
            exit_code = repos_cli.main(["list"])

        self.assertEqual(exit_code, 0)
        print_.assert_any_call("owner/a")
        print_.assert_any_call("owner/z")
        store.close.assert_called_once_with()

    def test_remove_exits_zero_when_repo_is_absent(self) -> None:
        store = MagicMock()
        store.remove_repo.return_value = 0

        with (
            _configured_env(),
            patch.object(repos_cli, "RedisStateStore", return_value=store),
        ):
            exit_code = repos_cli.main(["remove", "owner/repo"])

        self.assertEqual(exit_code, 0)
        store.remove_repo.assert_called_once_with("owner/repo")
        store.close.assert_called_once_with()

    def test_missing_redis_url_exits_nonzero(self) -> None:
        with (
            _configured_env(redis_url=None),
            patch.object(repos_cli, "RedisStateStore") as store,
        ):
            with patch("sys.stderr") as stderr:
                exit_code = repos_cli.main(["list"])

        self.assertEqual(exit_code, 2)
        store.assert_not_called()
        stderr.write.assert_any_call("error: DISPATCHER_REDIS_URL is not set")


def _configured_env(redis_url: str | None = "redis://example"):
    temp_dir = tempfile.TemporaryDirectory()
    dispatcher_dir = Path(temp_dir.name) / "dispatcher"
    dispatcher_dir.mkdir()
    env = {}
    if redis_url is not None:
        env["DISPATCHER_REDIS_URL"] = redis_url

    return _PatchedEnv(temp_dir, dispatcher_dir, env)


class _PatchedEnv:
    def __init__(
        self,
        temp_dir: tempfile.TemporaryDirectory[str],
        dispatcher_dir: Path,
        env: dict[str, str],
    ) -> None:
        self._temp_dir = temp_dir
        self._cwd_patch = patch("pathlib.Path.cwd", return_value=dispatcher_dir)
        self._env_patch = patch.dict("os.environ", env, clear=True)
        self._branch_patch = patch(
            "dispatcher.config.lookup_branch",
            return_value=BranchLookup.PRESENT,
        )

    def __enter__(self) -> None:
        self._temp_dir.__enter__()
        self._cwd_patch.__enter__()
        self._env_patch.__enter__()
        self._branch_patch.__enter__()

    def __exit__(self, *args: object) -> None:
        self._branch_patch.__exit__(*args)
        self._env_patch.__exit__(*args)
        self._cwd_patch.__exit__(*args)
        self._temp_dir.__exit__(*args)
