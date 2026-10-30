"""Merge gate: the controller merges a PR only when gate() returns "ready".

The controller runs this gate again on each PR activity event and every 10 minutes.
"""

from __future__ import annotations

import json
import subprocess
import sys

PASSING = {"success", "neutral", "skipped"}


def gh_json(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def read_check_runs(repo: str, head: str) -> list[dict] | None:
    """Return the check runs on head, or None when the read fails."""
    try:
        return gh_json(f"repos/{repo}/commits/{head}/check-runs")["check_runs"]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return None


def gate(repo: str, head: str) -> str:
    runs = read_check_runs(repo, head)
    if runs is None:
        return "not ready"
    if not runs:
        return "not ready"
    if all(run["status"] == "completed" and run["conclusion"] in PASSING for run in runs):
        return "ready"
    return "not ready"


if __name__ == "__main__":
    result = gate(sys.argv[1], sys.argv[2])
    print(result)
    sys.exit(0 if result == "ready" else 1)
