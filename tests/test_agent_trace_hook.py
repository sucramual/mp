"""Black-box tests for `agent-trace hook`, the PostToolUse hook that records `gh pr create` and `gh pr merge`.

The hook must never disturb the agent: it always exits 0, prints nothing, and survives any input.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import IsolatedEnv
from test_agent_trace_support import base_env, closed_port, read_jsonl, recorder, run

SHA = "0123456789abcdef0123456789abcdef01234567"


def bind(state: Path, session: str, ticket: str) -> None:
    (state / "sessions").mkdir(parents=True)
    (state / "sessions" / f"{session}.ticket").write_text(ticket + "\n")


def attrs(span: dict[str, Any]) -> dict[str, Any]:
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_pr_create_records_url_and_head(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    bind(state, "s1", "RUN-1")
    repo = isolated_env.root / "repo"
    repo.mkdir()
    isolated_env.git(repo, "init", "-q")
    isolated_env.git(repo, "commit", "-q", "--allow-empty", "-m", "c")
    head = isolated_env.git(repo, "rev-parse", "HEAD")
    payload = {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_use_id": "toolu_1",
        "cwd": str(repo),
        "tool_input": {"command": "gh pr create --fill --base main"},
        "tool_response": {"stdout": "Creating pull request\nhttps://github.com/acme/widgets/pull/42\n", "stderr": ""},
    }
    with recorder() as server:
        result = run(["hook"], base_env(isolated_env.env, state, server.url), input=json.dumps(payload))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    [span] = server.spans()
    assert span["name"] == "agent_trace.pr"
    assert span["service"] == "agent-trace"
    assert [e["name"] for e in span["events"]] == ["pr.create"]
    got = attrs(span)
    assert got["agent_trace.pr_action"] == "create"
    assert got["agent_trace.pr_url"] == "https://github.com/acme/widgets/pull/42"
    assert got["agent_trace.repo"] == "acme/widgets"
    assert got["agent_trace.head_sha"] == head
    assert got["agent_trace.tool_use_id"] == "toolu_1"
    assert got["session.id"] == "s1"
    assert got["run.ticket"] == "RUN-1"


def test_pr_merge_records_ref_repo_and_matched_head(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    payload = {
        "session_id": "s2",
        "tool_name": "Bash",
        "tool_input": {"command": f"cd /x && gh pr merge 12 --squash --match-head-commit {SHA} -R acme/widgets"},
        "tool_response": {"stdout": "", "stderr": ""},
    }
    env = base_env(isolated_env.env, state, "", TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
    with recorder() as server:
        env["AGENT_TRACE_ENDPOINT"] = server.url
        result = run(["hook"], env, input=json.dumps(payload))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    [span] = server.spans()
    got = attrs(span)
    assert got["agent_trace.pr_action"] == "merge"
    assert got["agent_trace.pr_ref"] == "12"
    assert got["agent_trace.repo"] == "acme/widgets"
    assert got["agent_trace.pr_url"] == "https://github.com/acme/widgets/pull/12"
    assert got["agent_trace.head_sha"] == SHA
    assert [e["name"] for e in span["events"]] == ["pr.merge"]
    assert span["traceId"] == "0af7651916cd43dd8448eb211c80319c"
    assert span["parentSpanId"] == "b7ad6b7169203331"


def test_codex_shell_tool_with_list_command(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    payload = {
        "session_id": "c1",
        "tool_name": "shell",
        "tool_input": {"command": ["gh", "pr", "merge", "https://github.com/acme/widgets/pull/7", "--merge"]},
        "tool_response": "",
    }
    with recorder() as server:
        result = run(["hook"], base_env(isolated_env.env, state, server.url), input=json.dumps(payload))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    [span] = server.spans()
    assert attrs(span)["agent_trace.pr_url"] == "https://github.com/acme/widgets/pull/7"


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not json",
        "[1, 2]",
        "{}",
        json.dumps({"tool_name": "Bash"}),
        json.dumps({"tool_name": "Bash", "tool_input": "gh pr create"}),
        json.dumps({"tool_name": "Read", "session_id": "s", "tool_input": {"command": "gh pr create"}}),
        json.dumps({"tool_name": "Bash", "session_id": "s", "tool_input": {"command": "git push"}}),
        json.dumps({"tool_name": "Bash", "session_id": "s", "tool_input": {"command": "gh pr view 3"}}),
    ],
)
def test_odd_or_unrelated_input_is_ignored(isolated_env: IsolatedEnv, tmp_path: Path, stdin: str) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        result = run(["hook"], base_env(isolated_env.env, state, server.url), input=stdin)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert server.requests == []
    assert not state.exists()


def test_huge_stdout_is_handled(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    payload = {
        "session_id": "s3",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": {"stdout": "x" * 5_000_000, "stderr": "boom " * 100},
    }
    with recorder() as server:
        result = run(["hook"], base_env(isolated_env.env, state, server.url), input=json.dumps(payload))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    [span] = server.spans()
    got = attrs(span)
    assert got["agent_trace.pr_action"] == "create"
    assert len(got["agent_trace.stderr"]) == 200
    assert "agent_trace.pr_url" not in got


def test_collect_down_writes_fallback_quietly_and_fast(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    payload = {
        "session_id": "s4",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create"},
        "tool_response": {"stdout": "https://github.com/acme/widgets/pull/9\n"},
    }
    began = time.monotonic()
    result = run(
        ["hook"], base_env(isolated_env.env, state, f"http://127.0.0.1:{closed_port()}"), input=json.dumps(payload)
    )
    elapsed = time.monotonic() - began
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert elapsed < 2.0
    [record] = read_jsonl(state / "fallback.jsonl")
    assert record["name"] == "agent_trace.pr"
    assert record["attrs"]["agent_trace.pr_url"] == "https://github.com/acme/widgets/pull/9"
    assert record["attrs"]["session.id"] == "s4"
