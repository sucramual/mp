"""Black-box tests for `agent-trace gate`, the PreToolUse PR-creation gate.

In a session that ran the /neo skill, `gh pr create` waits until the session has a ticket bound for its trace.
It blocks with exit 2 and a reason on stderr. In every other case, and on any error, it allows with exit 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import IsolatedEnv
from test_agent_trace_support import base_env, run

FIX = "agent-trace span start"
SKILL_CALL = {
    "type": "assistant",
    "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "neo", "args": "WO-5"}}]},
}
SLASH_COMMAND = {"type": "user", "message": {"content": "<command-name>/neo</command-name>\n<command-args>ABC-1"}}
QUOTED_IN_TOOL_OUTPUT = {
    "type": "user",
    "message": {"content": [{"type": "tool_result", "content": "SLASH = '<command-name>/neo</command-name>'"}]},
}
OTHER_SKILL = {
    "type": "assistant",
    "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "open-pr"}}]},
}


def transcript(tmp_path: Path, *lines: dict) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def payload(command: str, transcript_path: Path | str | None, session: str = "s1") -> str:
    data = {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"}
    if transcript_path is not None:
        data["transcript_path"] = str(transcript_path)
    return json.dumps(data)


def gate(isolated_env: IsolatedEnv, state: Path, stdin: str):
    return run(["gate"], base_env(isolated_env.env, state, ""), input=stdin)


# Protects: a /neo run cannot open a PR without a ticket-bound trace.
# Bug caught: on 2026-11-02 a /neo worker skipped agent-trace, so its ticket had no trace and no reconcile list.
@pytest.mark.parametrize("line", [SKILL_CALL, SLASH_COMMAND], ids=["skill-tool", "slash-command"])
def test_blocks_pr_create_in_a_neo_session_with_no_ticket(
    line: dict, isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    stdin = payload("cd repo && gh pr create --fill", transcript(tmp_path, line))
    result = gate(isolated_env, tmp_path / "state", stdin)
    assert result.returncode == 2, result.stderr
    assert FIX in result.stderr and "--ticket" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("command", ["cd /tmp\ngh pr create --fill", "echo hi\n\n  gh pr create -R o/r"])
def test_blocks_pr_create_on_a_new_line(command: str, isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    # Bug caught: an unquoted newline ends a command, but the tokenizer dropped it, so the gate was bypassed.
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, SKILL_CALL)))
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("command", ["# Create the PR\ngh pr create --fill", "cd /tmp # go\ngh pr create"])
def test_blocks_pr_create_after_a_comment_line(command: str, isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    # Bug caught: shlex read the next line as part of the comment, so the gate was bypassed.
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, SKILL_CALL)))
    assert result.returncode == 2, result.stderr


def test_allows_a_comment_that_names_the_command(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    command = "cd /tmp # gh pr create"
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, SKILL_CALL)))
    assert (result.returncode, result.stderr) == (0, "")


def test_allows_a_newline_inside_quotes(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    command = 'echo "line one\ngh pr create"'
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, SKILL_CALL)))
    assert (result.returncode, result.stderr) == (0, "")


def test_allows_pr_create_once_a_ticket_is_bound(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "sessions").mkdir(parents=True)
    (state / "sessions" / "s1.ticket").write_text("ABC-1\n")
    result = gate(isolated_env, state, payload("gh pr create --fill", transcript(tmp_path, SKILL_CALL)))
    assert (result.returncode, result.stderr) == (0, "")


# Protects: the gate stays out of every session that is not a /neo run, and out of other commands.
# Bug caught: a gate that blocks every PR on the machine, so people learn to remove it.
@pytest.mark.parametrize(
    ("command", "lines"),
    [
        ("gh pr create --fill", [OTHER_SKILL]),
        ("gh pr create --fill", []),
        ("gh pr view 12", [SKILL_CALL]),
        ("echo gh pr create", [SKILL_CALL]),
        ("gh pr create --fill", [QUOTED_IN_TOOL_OUTPUT]),
    ],
    ids=["other-skill", "no-skill", "pr-view", "echoed-text", "quoted-in-tool-output"],
)
def test_allows_outside_neo_pr_creation(
    command: str, lines: list[dict], isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, *lines)))
    assert (result.returncode, result.stderr) == (0, "")


# Protects: the gate fails open. Bug caught: a missing or broken transcript blocks a PR in a session it cannot read.
@pytest.mark.parametrize(
    "stdin",
    [
        payload("gh pr create --fill", None),
        payload("gh pr create --fill", "/no/such/transcript.jsonl"),
        "not json",
        "",
    ],
    ids=["no-transcript-path", "missing-transcript", "bad-json", "empty"],
)
def test_fails_open(stdin: str, isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    result = gate(isolated_env, tmp_path / "state", stdin)
    assert (result.returncode, result.stderr) == (0, "")
