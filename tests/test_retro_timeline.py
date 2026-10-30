"""Black-box tests for skills/retro/scripts/timeline.py, run as a command.

The /retro skill reads only this script's output, never the raw transcript. A missed fail, gap, loop, or
permission wait means the retro never sees that problem, so the tests parse the ``--json`` report and assert
on the marks it holds.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "timeline.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "retro"
FULL_PAGE = FIXTURES / "cloud_page_full.txt"
NEWER_PAGE = FIXTURES / "cloud_page_newer.json"
LOCAL_SESSION = FIXTURES / "local_session.jsonl"
SHAPES = FIXTURES / "cloud_shapes.json"
GQL_403 = "HTTP 403: GitHub GraphQL is not available from Claude Code sessions"


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


def report(*files: Path) -> dict[str, Any]:
    result = run("--json", *files)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_repeated_403_groups_into_one_fail_group() -> None:
    """Bug caught: grouping by raw error text splits the two 403s, because their request numbers differ.

    The retro then sees two single fails instead of one repeated failure.
    """
    data = report(FULL_PAGE)

    assert data["session"] == "sess_retro_1"
    assert len(data["fails"]) == 2
    groups = [group for group in data["fail_groups"] if "Bash(ro round)" in group["labels"]]
    assert len(groups) == 1, data["fail_groups"]
    assert groups[0]["count"] == 2
    assert "403" in groups[0]["error"]
    assert not groups[0]["error"].startswith("Exit code"), "the exit-code line hides the real error"
    assert groups[0]["first"] < groups[0]["last"]


def test_permission_wait_is_measured_and_unanswered_request_is_flagged() -> None:
    """Bug caught: the answer is not matched by request_id, or the status reply that lists pending requests is
    taken as the answer. Then the 3-hour wait shrinks to minutes. Also catches an unanswered request that is
    dropped instead of flagged.
    """
    perms = {perm["tool_use_id"]: perm for perm in report(FULL_PAGE)["perms"]}

    answered = perms["toolu_7"]
    assert answered["unanswered"] is False
    assert answered["behavior"] == "allow"
    assert answered["tool"] == "mcp__Linear__prepare_attachment_upload"
    assert answered["wait_seconds"] == pytest.approx(3 * 3600, abs=60)

    unanswered = perms["toolu_6"]
    assert unanswered["unanswered"] is True
    assert unanswered["answered_at"] is None
    # It waits until the next kept event, the assistant text 25 seconds later.
    assert unanswered["wait_seconds"] == pytest.approx(25, abs=1)


def test_gaps_tell_a_stall_inside_a_turn_from_idle_time_between_turns() -> None:
    """Bug caught: turn state is not tracked, so idle time between turns looks like a stall. Also catches
    harness events (system, status replies) that split a real gap into short pieces, and a permission wait
    that is not named as the cause of its gap.
    """
    gaps = {gap["start"][11:19]: gap for gap in report(FULL_PAGE)["gaps"]}

    assert set(gaps) == {"03:00:31", "03:15:40", "03:45:06"}, gaps
    stall = gaps["03:00:31"]
    assert stall["in_turn"] is True
    assert stall["cause"] is None
    assert stall["gap_seconds"] == pytest.approx(869, abs=1)

    idle = gaps["03:15:40"]
    assert idle["in_turn"] is False
    assert idle["gap_seconds"] == pytest.approx(1760, abs=1)

    permission = gaps["03:45:06"]
    assert permission["in_turn"] is True
    assert permission["cause"] == "permission"


def test_same_read_three_times_is_a_loop_and_different_commands_are_not() -> None:
    """Bug caught: the loop key uses the tool name only, so the two different Bash commands also count as a
    loop, or the key uses the tool_use id, so no loop is ever found.
    """
    loops = report(FULL_PAGE)["loops"]

    assert len(loops) == 1, loops
    assert loops[0]["label"] == "Read"
    assert loops[0]["count"] == 3
    assert "SKILL.md" in loops[0]["input"]


def test_no_action_result_counts_as_one_noop() -> None:
    """Bug caught: the phrase match is case-sensitive or runs on every result, so the noop count is 0 or 2."""
    noops = report(FULL_PAGE)["noops"]

    assert len(noops) == 1
    assert "No action is needed" in noops[0]["quote"]


def test_overlapping_pages_give_the_same_report_as_one_page() -> None:
    """Bug caught: events are not deduplicated by uuid, so overlapping pages double the fails, perms, and noops,
    and a duplicate event at the same time hides nothing but inflates every count. Pages arrive newest-first,
    so the newer page comes first here.
    """
    one = report(FULL_PAGE)
    both = report(NEWER_PAGE, FULL_PAGE)

    for key in ("session", "start", "end", "fail_groups", "fails", "perms", "gaps", "loops", "noops", "logs"):
        assert both[key] == one[key], key


def test_local_session_file_reports_its_failing_tool() -> None:
    """Bug caught: the local .jsonl format is not detected (it has `type` and `timestamp`, not `created_at`),
    so the script exits 2 or reports no fail.
    """
    data = report(LOCAL_SESSION)

    assert data["session"] == "local-session-7"
    assert len(data["fails"]) == 1
    fail = data["fails"][0]
    assert fail["label"] == "Bash(git push)"
    assert fail["error"] == "fatal: unable to access remote: 403"
    assert data["perms"] == []


@pytest.mark.parametrize(
    "path",
    [FIXTURES / "no_events.json", FIXTURES / "does_not_exist.json"],
    ids=["no-events", "missing-file"],
)
def test_file_without_events_fails_closed(path: Path) -> None:
    """Bug caught: an empty or missing input prints a clean report with no marks, so the retro says the run
    went well when the script read nothing.
    """
    result = run("--json", FULL_PAGE, path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert path.name in result.stderr


def test_text_mode_names_the_session() -> None:
    """Bug caught: the default text output crashes or loses the session label that the agent cites."""
    result = run("--session", "my-label", FULL_PAGE)

    assert result.returncode == 0, result.stderr
    assert "my-label" in result.stdout


def test_log_lines_in_assistant_text_are_marked() -> None:
    """Bug caught: the LOG prefix is matched anywhere in a line, or only at column 0, so a sentence that mentions
    LOG becomes a mark, or the indented LOG friction line is missed and the retro loses the agent's own notes.
    """
    logs = report(FULL_PAGE)["logs"]

    assert len(logs) == 1, logs
    assert logs[0]["time"].startswith("2026-10-29T06:45:11")
    assert logs[0]["line"].startswith("LOG friction | category=permission")
    assert all("comes at the end" not in log["line"] for log in logs)


def test_error_lines_in_output_count_as_soft_fails_but_prose_about_errors_does_not() -> None:
    """Bug caught: only ``is_error: true`` counts, so a 403 hidden by ``cmd ; echo done`` and a denied MCP call
    are never reported. Also catches a loose match that marks a read doc saying "GitHub returns HTTP 403 with".
    """
    fails = {fail["tool_use_id"]: fail for fail in report(SHAPES)["fails"]}

    assert set(fails) == {"t1", "t2", "t3", "t5"}, fails
    assert fails["t1"]["soft"] is True
    assert fails["t1"]["error"].startswith(GQL_403)
    assert fails["t5"]["soft"] is True
    assert "Permission for this action was denied" in fails["t5"]["error"]
    assert fails["t2"]["soft"] is False
    assert fails["t3"]["soft"] is False


def test_hard_fail_error_is_the_error_line_not_the_first_stdout_line() -> None:
    """Bug caught: the error text is the first non-exit-code line, which is stdout such as "Switched to a new
    branch", so the real error never reaches the retro.
    """
    fails = {fail["tool_use_id"]: fail for fail in report(SHAPES)["fails"]}

    assert fails["t2"]["error"].startswith(GQL_403)
    assert fails["t3"]["error"] == "fatal: a branch named 'x' already exists"


def test_bash_labels_skip_cd_assignments_export_and_timeout() -> None:
    """Bug caught: the label is the first two words of the whole command, giving ``Bash(cd /home/user/app)``
    or ``Bash(R=bddb12; git)`` instead of the command that ran.
    """
    labels = {fail["tool_use_id"]: fail["label"] for fail in report(SHAPES)["fails"]}

    assert labels == {
        "t1": "Bash(gh pr)",
        "t2": "Bash(gh search)",
        "t3": "Bash(git checkout)",
        "t5": "mcp__Linear__save_issue",
    }


def test_one_error_from_several_commands_is_one_group() -> None:
    """Bug caught: groups key on (label, error), so the GraphQL 403 from ``gh pr view`` and ``gh search`` shows as
    two single fails, and the retro misses that one cause broke every gh command.
    """
    groups = report(SHAPES)["fail_groups"]

    assert groups[0]["count"] == 2, groups
    assert groups[0]["repeated"] is True
    assert groups[0]["error"].startswith(GQL_403)
    assert sorted(groups[0]["labels"]) == ["Bash(gh pr)", "Bash(gh search)"]
    assert sum(group["count"] for group in groups) == 4


def test_loops_need_three_consecutive_identical_calls_in_one_turn() -> None:
    """Bug caught: identical calls are counted over the whole session, so a ReadNotifications call once per wake,
    or a Grep with another call between repeats, shows as a loop.
    """
    loops = report(SHAPES)["loops"]

    assert [(loop["label"], loop["count"]) for loop in loops] == [("Glob", 3)], loops


def test_more_noop_phrases_are_counted() -> None:
    """Bug caught: the noop pattern misses "needs no action", "Nothing to act on", and "Taking no action"."""
    quotes = [noop["quote"] for noop in report(SHAPES)["noops"]]

    assert quotes == ["This needs no action.", "Nothing to act on.", "Taking no action on this wake."]


def summary_lines(path: Path) -> list[str]:
    result = run(path)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    start = lines.index("Summary")
    end = lines.index("Timeline")
    return [line.strip() for line in lines[start + 1 : end] if line.strip()]


def test_text_summary_groups_perms_by_tool_and_lists_only_long_waits() -> None:
    """Bug caught: the summary prints one line per permission request, so a session with dozens of short prompts
    buries the long waits. Each tool gets one line, and only waits at the gap threshold are listed alone.
    """
    shapes = [line for line in summary_lines(SHAPES) if "create_pull_request" in line]
    assert len(shapes) == 1, shapes
    assert "x2" in shapes[0]
    assert "unanswered 0" in shapes[0]

    full = [line for line in summary_lines(FULL_PAGE) if "prepare_attachment_upload" in line]
    assert len(full) == 2, full
    assert "x2" in full[0] and "unanswered 1" in full[0]
    assert "3.0h" in full[1], "the 3-hour wait is listed on its own line"


def _local_text(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _failing_call(second: int, error: str) -> list[dict[str, Any]]:
    stamp = "2026-10-29T08:00:{:02d}.000Z"
    return [
        {
            "type": "assistant",
            "timestamp": stamp.format(second),
            "uuid": f"a{second}",
            "sessionId": "s",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": f"t{second}", "name": "Bash", "input": {"command": f"curl {second}"}}
                ],
            },
        },
        {
            "type": "user",
            "timestamp": stamp.format(second + 1),
            "uuid": f"u{second}",
            "sessionId": "s",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": f"t{second}", "is_error": True, "content": error}],
            },
        },
    ]


def test_different_http_statuses_are_different_fail_groups(tmp_path: Path) -> None:
    """Bug caught: replacing every digit run merges "HTTP 403" and "HTTP 500" into one repeated failure, so the
    retro reports one cause and hides the other. Request numbers must still merge.
    """
    path = tmp_path / "session.jsonl"
    path.write_text(
        _local_text(
            _failing_call(1, "error: HTTP 403 from proxy (request 1234)")
            + _failing_call(3, "error: HTTP 500 from proxy (request 5678)")
            + _failing_call(5, "error: HTTP 403 from proxy (request 9999)")
        )
    )

    groups = report(path)["fail_groups"]

    assert len(groups) == 2, groups
    by_status = {"403" if "403" in group["error"] else "500": group for group in groups}
    assert by_status["403"]["count"] == 2
    assert by_status["403"]["repeated"] is True
    assert by_status["500"]["count"] == 1
    assert by_status["500"]["repeated"] is False


def test_local_end_turn_ends_the_turn_and_counts_a_noop(tmp_path: Path) -> None:
    """Bug caught: a local transcript has no result event, so a finished turn stays open, the idle hour before
    the next user message shows as a stall, and a "no action" wake is never counted.
    """
    path = tmp_path / "session.jsonl"
    path.write_text(
        _local_text(
            [
                {
                    "type": "user",
                    "timestamp": "2026-10-29T08:00:00.000Z",
                    "uuid": "u1",
                    "sessionId": "s",
                    "message": {"role": "user", "content": "check the PR"},
                },
                {
                    "type": "assistant",
                    "timestamp": "2026-10-29T08:00:05.000Z",
                    "uuid": "a1",
                    "sessionId": "s",
                    "message": {
                        "role": "assistant",
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "No action is needed."}],
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-10-29T09:00:00.000Z",
                    "uuid": "u2",
                    "sessionId": "s",
                    "message": {"role": "user", "content": "any news?"},
                },
            ]
        )
    )

    data = report(path)

    assert len(data["noops"]) == 1, data["noops"]
    assert "No action is needed" in data["noops"][0]["quote"]
    assert len(data["gaps"]) == 1, data["gaps"]
    assert data["gaps"][0]["in_turn"] is False
