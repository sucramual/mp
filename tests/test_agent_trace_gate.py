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


# Protects: no shell layout hides a PR creation from the gate. Bug caught: in review, a newline, a comment line,
# and a comment line after a newline each let `gh pr create` through a shell-parsing gate.
# Bug caught: `dotfiles-pr ship`, the REST fallback, and `gh stack submit` open a PR with no `gh pr create` in the call.
# Echoed, quoted, and commented mentions also block: in a /neo session with no ticket, the fix is owed anyway.
@pytest.mark.parametrize(
    "command",
    [
        "cd /tmp\ngh pr create --fill",
        "echo hi\n\n  gh pr create -R o/r",
        "# Create the PR\ngh pr create --fill",
        "cd /tmp # go\ngh pr create",
        "cd /tmp\n# Create the PR\ngh pr create --fill",
        "gh --repo=o/r pr create --fill",
        "echo gh pr create",
        "cd /tmp # gh pr create",
        'echo "line one\ngh pr create"',
        '"$DOTFILES_PR" ship "feat: x" --body-file /tmp/body.md',
        "tools/dotfiles-pr/bin/dotfiles-pr ship 'msg'",
        "gh api 'repos/o/r/pulls' -f title=x -f head=b -f base=main -F body=@b.md",
        "gh api repos/o/r/pulls -X POST --input pr.json",
        "gh stack submit --remote origin",
    ],
    ids=[
        "newline",
        "blank-line-and-indent",
        "comment-line",
        "trailing-comment",
        "comment-after-newline",
        "repo-flag",
        "echoed",
        "commented",
        "quoted",
        "dotfiles-pr-ship-variable",
        "dotfiles-pr-ship-path",
        "rest-create-quoted",
        "rest-create-post",
        "stack-submit",
    ],
)
def test_blocks_any_pr_create_in_a_neo_session(command: str, isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, SKILL_CALL)))
    assert result.returncode == 2, result.stderr
    assert FIX in result.stderr


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
        ("gh pr list --search 'pr create'", [SKILL_CALL]),
        ("gh pr create --fill", [QUOTED_IN_TOOL_OUTPUT]),
        ("gh api 'repos/o/r/pulls?head=o:b&state=open'", [SKILL_CALL]),
        ("gh api -X PATCH 'repos/o/r/pulls/12' -F body=@b.md", [SKILL_CALL]),
        ("dotfiles-pr start fix-gate", [SKILL_CALL]),
    ],
    ids=[
        "other-skill",
        "no-skill",
        "pr-view",
        "other-gh-command",
        "quoted-in-tool-output",
        "rest-pr-lookup",
        "rest-pr-update",
        "dotfiles-pr-start",
    ],
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
