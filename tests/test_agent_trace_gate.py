"""Black-box tests for `agent-trace gate`, the PreToolUse ticket gate.

In a session that ran the /neo skill, a file edit and `gh pr create` wait until the session has a ticket bound.
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
    "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "neo", "args": "PB-5"}}]},
}
SLASH_COMMAND = {"type": "user", "message": {"content": "<command-name>/neo</command-name>\n<command-args>ABC-1"}}
QUOTED_IN_TOOL_OUTPUT = {
    "type": "user",
    "message": {"content": [{"type": "tool_result", "content": "SLASH = '<command-name>/neo</command-name>'"}]},
}
# Codex rollout records, in the shape of a local rollout and of codex-rs/app-server/tests/common/rollout.rs.
CODEX_META = {"type": "session_meta", "payload": {"id": "s1", "cwd": "/tmp"}}


def codex_user(text: str) -> dict:
    return {
        "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
    }


CODEX_SKILL = codex_user("<skill>\n<name>neo</name>\n<path>/h/.agents/skills/neo/SKILL.md</path>\n---\nname: neo")
CODEX_MENTION = {"type": "event_msg", "payload": {"type": "user_message", "message": "$neo ABC-1", "kind": "plain"}}
CODEX_READ = {
    "type": "response_item",
    "payload": {"type": "function_call", "name": "shell", "arguments": '{"command":["cat","/h/skills/neo/SKILL.md"]}'},
}
CODEX_OTHER_SKILL = codex_user("<skill>\n<name>open-pr</name>\n<path>/h/skills/open-pr/SKILL.md</path>")
CODEX_TOOL_OUTPUT = {
    "type": "response_item",
    "payload": {"type": "function_call_output", "output": "<skill>\n<name>neo</name>"},
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
    return tool_payload("Bash", {"command": command}, transcript_path, session)


def tool_payload(tool: str, tool_input: dict, transcript_path: Path | str | None, session: str = "s1") -> str:
    data = {"session_id": session, "tool_name": tool, "tool_input": tool_input, "cwd": "/tmp"}
    if transcript_path is not None:
        data["transcript_path"] = str(transcript_path)
    return json.dumps(data)


def gate(isolated_env: IsolatedEnv, state: Path, stdin: str):
    return run(["gate"], base_env(isolated_env.env, state, ""), input=stdin)


# Protects: a /neo run cannot open a PR without a ticket-bound trace.
# Bug caught: on 2026-11-02 a /neo worker skipped agent-trace, so its ticket had no trace and no reconcile list.
# In review, a Codex /neo session passed, because the gate read only Claude Code's transcript shape.
@pytest.mark.parametrize(
    "lines",
    [
        [SKILL_CALL],
        [SLASH_COMMAND],
        [CODEX_META, CODEX_MENTION, CODEX_SKILL],
        [CODEX_META, CODEX_MENTION],
        [CODEX_META, CODEX_READ],
    ],
    ids=["skill-tool", "slash-command", "codex-skill", "codex-mention", "codex-reads-skill"],
)
def test_blocks_pr_create_in_a_neo_session_with_no_ticket(
    lines: list[dict], isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    stdin = payload("cd repo && gh pr create --fill", transcript(tmp_path, *lines))
    result = gate(isolated_env, tmp_path / "state", stdin)
    assert result.returncode == 2, result.stderr
    assert FIX in result.stderr and "--work" in result.stderr
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


# Protects: a run that binds its work ID through the environment is not blocked.
# Bug caught: the gate reads only AGENT_TRACE_TICKET, so a run that sets AGENT_TRACE_WORK cannot open its PR.
def test_allows_pr_create_with_a_work_id_in_the_environment(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    env = base_env(isolated_env.env, tmp_path / "state", "", AGENT_TRACE_WORK="CH-2")
    result = run(["gate"], env, input=payload("gh pr create --fill", transcript(tmp_path, SKILL_CALL)))
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
        ("gh pr create --fill", [CODEX_META, CODEX_OTHER_SKILL]),
        ("gh pr create --fill", [CODEX_META, CODEX_TOOL_OUTPUT]),
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
        "codex-other-skill",
        "codex-tool-output",
    ],
)
def test_allows_outside_neo_pr_creation(
    command: str, lines: list[dict], isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    result = gate(isolated_env, tmp_path / "state", payload(command, transcript(tmp_path, *lines)))
    assert (result.returncode, result.stderr) == (0, "")


EDITS = [
    ("Edit", {"file_path": "/r/a.py", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "/r/a_test.py", "content": "x"}),
    ("MultiEdit", {"file_path": "/r/a.py", "edits": []}),
    ("NotebookEdit", {"notebook_path": "/r/n.ipynb", "new_source": "x"}),
]


# Protects: a /neo run binds its ticket before its first file change, so the trace covers the red test and the fix.
# Bug caught: on 2026-11-03 a /neo run bound its ticket only at PR time, so the trace held no span for
# intake, the red test, the fix, or the review. The PR gate alone fires too late for that.
@pytest.mark.parametrize(("tool", "tool_input"), EDITS, ids=[tool for tool, _ in EDITS])
def test_blocks_the_first_edit_in_a_neo_session_with_no_ticket(
    tool: str, tool_input: dict, isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    stdin = tool_payload(tool, tool_input, transcript(tmp_path, SKILL_CALL))
    result = gate(isolated_env, tmp_path / "state", stdin)
    assert result.returncode == 2, result.stderr
    assert FIX in result.stderr and "--work" in result.stderr
    assert "before its first file change" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(("tool", "tool_input"), EDITS, ids=[tool for tool, _ in EDITS])
def test_allows_edits_once_a_ticket_is_bound_or_outside_neo(
    tool: str, tool_input: dict, isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    (state / "sessions").mkdir(parents=True)
    (state / "sessions" / "s1.ticket").write_text("ABC-1\n")
    bound = gate(isolated_env, state, tool_payload(tool, tool_input, transcript(tmp_path, SKILL_CALL)))
    other = gate(isolated_env, tmp_path / "other", tool_payload(tool, tool_input, transcript(tmp_path, OTHER_SKILL)))
    assert (bound.returncode, bound.stderr) == (0, "")
    assert (other.returncode, other.stderr) == (0, "")


# Protects: intake reads stay allowed before the ticket exists. Bug caught: a gate that blocks Read or a plain
# shell call, so a /neo run cannot even look up or create its ticket.
@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [("Read", {"file_path": "/r/a.py"}), ("Bash", {"command": "git log -5 --oneline"}), ("Grep", {"pattern": "x"})],
    ids=["read", "shell", "grep"],
)
def test_allows_reads_in_a_neo_session_with_no_ticket(
    tool: str, tool_input: dict, isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    result = gate(isolated_env, tmp_path / "state", tool_payload(tool, tool_input, transcript(tmp_path, SKILL_CALL)))
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
