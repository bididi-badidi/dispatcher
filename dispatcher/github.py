from __future__ import annotations

from dispatcher.models import Config, Issue
from dispatcher.subprocess_utils import run_json


def list_triggered_issues(config: Config) -> list[Issue]:
    raw_issues = run_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            config.repo,
            "--label",
            config.label,
            "--state",
            "open",
            "--json",
            "number,title,url",
            "--limit",
            "20",
        ],
        cwd=config.paths.project_dir,
    )
    return [
        Issue(
            number=int(item["number"]),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
        )
        for item in raw_issues
    ]
