"""Black-box tests for skills/verify/scripts/plan_diff.py, run as a command.

The script decides whether Marcus gets a Spacelift confirm link. A false "identical" would let him apply a plan
that no review covered, so every test asserts the exit code and the lines that the script prints.
"""

from __future__ import annotations

import subprocess
import sys

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "verify" / "scripts" / "plan_diff.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "verify_plan_diff"


def run(reviewed: str, tracked: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / reviewed), str(FIXTURES / tracked)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_same_changes_in_another_order_are_identical() -> None:
    # Bug caught: comparing unsorted lists reports a false difference when Spacelift returns another order.
    result = run("reviewed.json", "same-other-order.json")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "identical",
        "ADD google_storage_bucket_iam_member.reader",
        "UPDATE google_storage_bucket.exports",
    ]


def test_an_extra_change_in_the_tracked_run_is_a_difference() -> None:
    # Bug caught: another PR's unapplied delete rides along in the tracked run, and the script calls it identical.
    result = run("reviewed.json", "extra-delete.json")

    assert result.returncode == 1
    assert "identical" not in result.stdout.splitlines()
    assert "+DELETE google_storage_bucket_iam_member.legacy_reader" in result.stdout.splitlines()


def test_an_entry_without_an_action_stops_the_comparison() -> None:
    # Bug caught: an entry with an empty action is dropped, so a change that no one can read passes as identical.
    result = run("reviewed.json", "missing-action.json")

    assert result.returncode == 2
    assert "google_storage_bucket_iam_member.reader" in result.stderr
    assert result.stdout == ""


def test_an_empty_plan_stops_the_comparison() -> None:
    # Bug caught: a failed or empty spacectl read on both sides compares as two equal empty lists.
    result = run("empty.json", "empty.json")

    assert result.returncode == 2
    assert "no changes" in result.stderr
    assert result.stdout == ""
