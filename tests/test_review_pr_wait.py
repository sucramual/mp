"""Runs review-pr's reviewer wait, `scripts/wait-for-activity.sh`, against a fake `gh`.

The script must end the wait on any new PR activity, including an edited comment: the Codex reviewer
reports "done" by editing its summary comment, so a count of comments never changes. It must also end
the wait when a read fails, so the agent reads again and stops on the failure, instead of waiting blind.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "review-pr" / "scripts" / "wait-for-activity.sh"

# The fake gh answers each REST endpoint from a JSON file. From poll CHANGE_AT on, it answers from the
# "after" file when one exists. It counts polls by the reads of the pull endpoint.
FAKE_GH = r"""#!/bin/bash
set -u
endpoint="" jq=""
while [ $# -gt 0 ]; do
  case "$1" in
    api|--paginate) ;;
    --jq) jq="$2"; shift ;;
    *) endpoint="$1" ;;
  esac
  shift
done
key=$(printf '%s' "${endpoint%%\?*}" | tr '/' '_')
if [ "$key" = "repos_o_r_pulls_7" ]; then
  echo x >> "$FAKE_DIR/polls"
fi
polls=$(wc -l < "$FAKE_DIR/polls" | tr -d ' ')
file="$FAKE_DIR/$key.json"
if [ "$polls" -ge "${CHANGE_AT:-999}" ] && [ -f "$FAKE_DIR/$key.after.json" ]; then
  file="$FAKE_DIR/$key.after.json"
fi
[ -f "$file" ] || { echo "HTTP 404: Not Found" >&2; exit 1; }
jq -r "$jq" "$file"
"""

BASE = {
    "repos_o_r_pulls_7": {"head": {"sha": "abc"}},
    "repos_o_r_issues_7_comments": [{"id": 1, "updated_at": "2026-11-02T10:00:00Z", "body": "running"}],
    "repos_o_r_pulls_7_comments": [],
    "repos_o_r_pulls_7_reviews": [],
    "repos_o_r_issues_7_reactions": [],
}


def _run(tmp_path: Path, after: Mapping[str, object], change_at: int, drop: str | None = None):
    fake = tmp_path / "fake"
    fake.mkdir(parents=True)
    (fake / "polls").write_text("")
    for key, value in BASE.items():
        if key != drop:
            (fake / f"{key}.json").write_text(json.dumps(value))
    for key, value in after.items():
        (fake / f"{key}.after.json").write_text(json.dumps(value))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "CHANGE_AT": str(change_at),
        "REVIEW_PR_POLL_SECONDS": "0",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "o/r", "7"], env=env, capture_output=True, text=True, timeout=10, check=False
    )
    polls = len((fake / "polls").read_text().splitlines())
    return result, polls


def test_an_edited_reviewer_comment_ends_the_wait(tmp_path: Path) -> None:
    # Bug: a fingerprint of comment counts never changes when the Codex bot edits "running" to "completed".
    edited = [{"id": 1, "updated_at": "2026-11-02T10:05:00Z", "body": "completed"}]
    result, polls = _run(tmp_path, {"repos_o_r_issues_7_comments": edited}, change_at=3)
    assert result.returncode == 0, result.stderr
    assert "new PR activity" in result.stdout
    assert polls == 3, "the wait should go on through the unchanged polls and end on the first changed one"


def test_a_new_head_or_review_ends_the_wait(tmp_path: Path) -> None:
    after = {"repos_o_r_pulls_7": {"head": {"sha": "def"}}}
    result, _ = _run(tmp_path, after, change_at=2)
    assert result.returncode == 0, result.stderr
    assert "new PR activity" in result.stdout

    review = [{"id": 9, "state": "COMMENTED"}]
    result, _ = _run(tmp_path / "second", {"repos_o_r_pulls_7_reviews": review}, change_at=2)
    assert result.returncode == 0, result.stderr
    assert "new PR activity" in result.stdout


def test_a_failed_read_ends_the_wait_with_an_error(tmp_path: Path) -> None:
    # Bug: a loop that hides read errors waits forever on a PR it cannot read.
    result, polls = _run(tmp_path, {}, change_at=999, drop="repos_o_r_pulls_7_reviews")
    assert result.returncode != 0
    assert "read failed" in result.stderr
    assert "new PR activity" not in result.stdout
    assert polls == 1, "the wait should stop at the first read"
