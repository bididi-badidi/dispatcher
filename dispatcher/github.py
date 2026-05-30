from __future__ import annotations

from dispatcher.models import Config, Issue
from dispatcher.subprocess_utils import run_json


def _label_names(item: dict[object, object]) -> set[str]:
    labels = item.get("labels", [])
    if not isinstance(labels, list):
        return set()
    return {
        str(label["name"])
        for label in labels
        if isinstance(label, dict) and "name" in label
    }


def list_triggered_issues(config: Config, repo: str) -> list[Issue]:
    raw_issues = run_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            config.label,
            "--state",
            "open",
            "--json",
            "number,title,url,labels",
            "--limit",
            "20",
        ],
        cwd=config.paths.project_dir,
        debug=config.debug,
    )
    return [
        Issue(
            number=int(item["number"]),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            plan_model=(
                config.opus_model
                if {config.label, config.opus_label}.issubset(_label_names(item))
                else None
            ),
        )
        for item in raw_issues
    ]
