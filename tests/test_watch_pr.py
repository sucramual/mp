"""Runs the PR watcher, `skills/review-pr/scripts/watch-pr.sh`, against a fake `gh`.

The watcher is the one wait for an open PR. It must end the wait on each state change that needs the
worker, and print which one: a required check finishes, the review decision changes, a comment, review,
or reaction arrives, the head moves, a merge conflict appears, the PR becomes ready, or it merges or
closes. It must not end the wait on comments from bots that never need action. A failed read ends the
wait with an error, so the agent reads again and stops on the failure instead of waiting blind.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "review-pr" / "scripts" / "watch-pr.sh"

# The fake gh answers each endpoint from a JSON file: REST paths by their path, GraphQL by `graphql`.
# From poll CHANGE_AT on, it answers from the "after" file when one exists. It counts polls by the
# GraphQL reads, which the watcher makes once per poll.
FAKE_GH = r"""#!/bin/bash
set -u
endpoint="" jq=""
while [ $# -gt 0 ]; do
  case "$1" in
    api|--paginate) ;;
    -f|-F) shift ;;
    --jq) jq="$2"; shift ;;
    *) endpoint="$1" ;;
  esac
  shift
done
key=$(printf '%s' "${endpoint%%\?*}" | tr '/' '_')
if [ "$key" = "graphql" ]; then
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

SHA = "abc"


def check(name: str, conclusion: str | None, required: bool = True) -> dict[str, object]:
    """One check run in the GraphQL rollup. A None conclusion means the run is still in progress."""
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": "IN_PROGRESS" if conclusion is None else "COMPLETED",
        "conclusion": conclusion,
        "isRequired": required,
    }


def pr(
    *,
    state: str = "OPEN",
    mergeable: str = "MERGEABLE",
    review: str | None = "REVIEW_REQUIRED",
    head: str = SHA,
    checks: Sequence[Mapping[str, object]] = (check("backend", None),),
) -> dict[str, object]:
    """The GraphQL answer for the PR: its state, mergeability, review decision, head, and checks."""
    rollup = {"contexts": {"nodes": list(checks)}}
    node = {"commit": {"statusCheckRollup": rollup}}
    pull = {
        "state": state,
        "mergeable": mergeable,
        "reviewDecision": review,
        "headRefOid": head,
        "commits": {"nodes": [node]},
    }
    return {"data": {"repository": {"pullRequest": pull}}}


BASE: dict[str, object] = {
    "graphql": pr(),
    "repos_o_r_issues_7_comments": [
        {"id": 1, "updated_at": "2026-11-02T10:00:00Z", "user": {"login": "chatgpt-codex-connector[bot]"}},
        {"id": 2, "updated_at": "2026-11-02T10:00:00Z", "user": {"login": "nx-cloud[bot]"}},
    ],
    "repos_o_r_pulls_7_comments": [],
    "repos_o_r_pulls_7_reviews": [],
    "repos_o_r_issues_7_reactions": [],
}


def _run(
    tmp_path: Path,
    after: Mapping[str, object],
    change_at: int,
    *,
    base: Mapping[str, object] | None = None,
    drop: str | None = None,
    timeout: int | None = None,
    state_dir: Path | None = None,
):
    fake = tmp_path / "fake"
    fake.mkdir(parents=True)
    (fake / "polls").write_text("")
    for key, value in {**BASE, **(base or {})}.items():
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
        "WATCH_PR_POLL_SECONDS": "0",
        "WATCH_PR_STATE_DIR": str(state_dir or tmp_path / "state"),
    }
    args = ["bash", str(SCRIPT)]
    if timeout is not None:
        args += ["--timeout", str(timeout)]
    result = subprocess.run([*args, "o/r", "7"], env=env, capture_output=True, text=True, timeout=20, check=False)
    polls = len((fake / "polls").read_text().splitlines())
    return result, polls


def _events(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.startswith("event: ")]


def test_an_edited_reviewer_comment_ends_the_wait(tmp_path: Path) -> None:
    # Bug: a fingerprint of comment counts never changes when the Codex bot edits "running" to "completed".
    edited = [
        {"id": 1, "updated_at": "2026-11-02T10:05:00Z", "user": {"login": "chatgpt-codex-connector[bot]"}},
        {"id": 2, "updated_at": "2026-11-02T10:00:00Z", "user": {"login": "nx-cloud[bot]"}},
    ]
    result, polls = _run(tmp_path, {"repos_o_r_issues_7_comments": edited}, change_at=3)
    assert _events(result) == ["event: comment"]
    assert polls == 3, "the wait should go on through the unchanged polls and end on the first changed one"


def test_a_new_head_or_review_ends_the_wait(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, {"graphql": pr(head="def")}, change_at=2)
    assert _events(result) == ["event: head def"]

    review = [{"id": 9, "state": "COMMENTED", "user": {"login": "someone"}}]
    result, _ = _run(tmp_path / "second", {"repos_o_r_pulls_7_reviews": review}, change_at=2)
    assert _events(result) == ["event: review"]


def test_a_failed_read_ends_the_wait_with_an_error(tmp_path: Path) -> None:
    # Bug: a loop that hides read errors waits forever on a PR it cannot read.
    result, polls = _run(tmp_path, {}, change_at=999, drop="repos_o_r_pulls_7_reviews")
    assert result.returncode != 0
    assert "read failed" in result.stderr
    assert "event:" not in result.stdout
    assert polls == 1, "the wait should stop at the first read"


def test_a_finished_required_check_ends_the_wait_with_its_result(tmp_path: Path) -> None:
    # Bug: Auto-fix wakes the run on a failure, not on a pass, so a green PR waited with nothing awake.
    passed = pr(checks=[check("backend", "SUCCESS")])
    result, polls = _run(tmp_path, {"graphql": passed}, change_at=3)
    assert _events(result) == ["event: check-finished pass backend"]
    assert polls == 3

    failed = pr(checks=[check("backend", "FAILURE")])
    result, _ = _run(tmp_path / "second", {"graphql": failed}, change_at=2)
    assert _events(result) == ["event: check-finished fail backend"]


def test_a_check_that_is_not_required_does_not_end_the_wait(tmp_path: Path) -> None:
    # Bug: a watcher that wakes on every one of a monorepo's 60 checks spends a turn on each.
    base = {"graphql": pr(checks=[check("backend", None), check("lint-extra", None, required=False)])}
    after = {"graphql": pr(checks=[check("backend", None), check("lint-extra", "FAILURE", required=False)])}
    result, polls = _run(tmp_path, after, change_at=2, base=base, timeout=1)
    assert _events(result) == ["event: timeout"]
    assert polls >= 2, "the wait should have seen the changed check before it timed out"


def test_a_review_decision_change_ends_the_wait(tmp_path: Path) -> None:
    after = {"graphql": pr(review="CHANGES_REQUESTED")}
    result, _ = _run(tmp_path, after, change_at=2)
    assert _events(result) == ["event: review-decision CHANGES_REQUESTED"]


def test_a_merge_conflict_ends_the_wait(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, {"graphql": pr(mergeable="CONFLICTING")}, change_at=2)
    assert _events(result) == ["event: conflict"]


def test_a_pr_that_becomes_ready_ends_the_wait(tmp_path: Path) -> None:
    # Bug (2026-11-03): an approved PR with green checks waited 7.5 hours, because nothing woke the worker
    # when GitHub finished computing that it could merge.
    green = [check("backend", "SUCCESS")]
    base = {"graphql": pr(review="APPROVED", mergeable="UNKNOWN", checks=green)}
    after = {"graphql": pr(review="APPROVED", mergeable="MERGEABLE", checks=green)}
    result, _ = _run(tmp_path, after, change_at=2, base=base, state_dir=tmp_path / "seeded")
    # The first run has no record, so it reports what it found: the approval and the green check.
    first = _events(result)
    assert "event: ready" not in first
    assert "event: review-decision APPROVED" in first

    result, _ = _run(tmp_path / "second", after, change_at=2, base=base, state_dir=tmp_path / "seeded")
    assert _events(result) == ["event: ready"]


def test_a_merged_or_closed_pr_ends_the_wait(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, {"graphql": pr(state="MERGED")}, change_at=2)
    assert _events(result) == ["event: merged"]

    result, _ = _run(tmp_path / "second", {"graphql": pr(state="CLOSED")}, change_at=2)
    assert _events(result) == ["event: closed"]


def test_bot_status_comments_and_review_start_marks_do_not_end_the_wait(tmp_path: Path) -> None:
    # Bug (2026-11-03): edits to the Nx Cloud status comment woke the worker 6 times with nothing to do.
    comments = [
        {"id": 1, "updated_at": "2026-11-02T10:00:00Z", "user": {"login": "chatgpt-codex-connector[bot]"}},
        {"id": 2, "updated_at": "2026-11-02T10:09:00Z", "user": {"login": "nx-cloud[bot]"}},
        {"id": 3, "updated_at": "2026-11-02T10:09:00Z", "user": {"login": "github-actions[bot]"}},
    ]
    eyes = [{"id": 5, "content": "eyes"}]
    after = {"repos_o_r_issues_7_comments": comments, "repos_o_r_issues_7_reactions": eyes}
    result, polls = _run(tmp_path, after, change_at=2, timeout=1)
    assert _events(result) == ["event: timeout"]
    assert polls >= 2, "the wait should have seen the bot comments before it timed out"

    # The same kind of change from a reviewer still ends the wait.
    thumbs = [{"id": 6, "content": "+1"}]
    result, _ = _run(tmp_path / "second", {"repos_o_r_issues_7_reactions": thumbs}, change_at=2)
    assert _events(result) == ["event: reaction"]


def test_a_change_between_two_runs_ends_the_next_run_at_once(tmp_path: Path) -> None:
    # Bug: a watcher that takes its baseline at start misses a check that finished while the worker was
    # busy, so the worker waits for a change that already happened.
    state = tmp_path / "state"
    review = [{"id": 9, "state": "COMMENTED", "user": {"login": "someone"}}]
    result, _ = _run(tmp_path / "first", {"repos_o_r_pulls_7_reviews": review}, change_at=2, state_dir=state)
    assert _events(result) == ["event: review"]

    finished = {"graphql": pr(checks=[check("backend", "SUCCESS")])}
    result, polls = _run(tmp_path / "second", {}, change_at=999, base=finished, state_dir=state)
    assert _events(result) == ["event: check-finished pass backend"]
    assert polls == 1, "the run should end on its first read"


def test_a_state_that_the_last_run_saw_does_not_end_the_next_run(tmp_path: Path) -> None:
    # Bug: a watcher that reports any ready PR at start wakes a parked PR at once, again and again.
    state = tmp_path / "state"
    ready = {"graphql": pr(review="APPROVED", checks=[check("backend", "SUCCESS")])}
    result, _ = _run(tmp_path / "first", {}, change_at=999, base=ready, state_dir=state)
    assert "event: ready" in _events(result)

    result, _ = _run(tmp_path / "second", {}, change_at=999, base=ready, state_dir=state, timeout=1)
    assert _events(result) == ["event: timeout"]
