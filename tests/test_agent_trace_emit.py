"""Black-box tests for `agent-trace span` and `agent-trace note`: validation, OTLP mapping, and the fallback file.

Each test runs the real tool as a subprocess. A recording server stands in for collect, so a test can assert what
was sent. AGENT_TRACE_DIR is a temporary directory, so no test writes to the real state directory.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest
from conftest import IsolatedEnv
from test_agent_trace_support import base_env, closed_port, read_jsonl, recorder, run

TP1 = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
TP2 = "00-11111111111111111111111111111111-2222222222222222-01"


def span_id(scope: str, ident: str) -> str:
    return hashlib.sha256(f"{scope}\0{ident}".encode()).hexdigest()[:16]


def trace_id(scope: str) -> str:
    return hashlib.sha256(f"agent-trace\0{scope}".encode()).hexdigest()[:32]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["span", "start", "--id", "a", "--name", "x", "--kind", "bogus"], "--kind must be one of"),
        (["span", "end", "--id", "a", "--status", "done"], "--status must be one of"),
        (["note", "friction", "--category", "other", "--what", "w", "--fix", "f"], "--category must be one of"),
        (["span", "start", "--id", "Bad_ID", "--name", "x", "--kind", "phase"], "--id must match"),
        (["span", "start", "--id", "a", "--name", "x", "--kind", "phase", "--parent", "../x"], "--parent must match"),
        (["note", "friction", "--category", "doc", "--what", "   ", "--fix", "f"], "--what must not be empty"),
        (["span", "end", "--id", "a", "--status", "ok", "--note", "a\nb"], "--note must not contain a newline"),
        (["span", "start", "--id", "a", "--name", "n" * 301, "--kind", "phase"], "--name must be at most 300"),
        (["note", "none", "--ref", "xyz"], "--ref must match"),
    ],
)
def test_invalid_input_exits_2_and_sends_and_writes_nothing(
    isolated_env: IsolatedEnv, tmp_path: Path, args: list[str], message: str
) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        result = run([*args, "--ticket", "RUN-1"], base_env(isolated_env.env, state, server.url))
    assert result.returncode == 2
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("agent-trace: ")
    assert message in lines[0]
    assert result.stdout == ""
    assert server.requests == []
    assert not state.exists()


def test_bad_ticket_exits_2_and_sends_nothing(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "", CLAUDE_CODE_SESSION_ID="s1")
    with recorder() as server:
        env["AGENT_TRACE_ENDPOINT"] = server.url
        result = run(["span", "start", "--id", "a", "--name", "x", "--kind", "phase", "--ticket", "abc-1"], env)
    assert result.returncode == 2
    assert result.stderr.strip().startswith("agent-trace: --ticket must match")
    assert server.requests == []
    assert not state.exists()


def test_no_scope_exits_2_and_sends_nothing(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        result = run(
            ["span", "start", "--id", "a", "--name", "x", "--kind", "phase"],
            base_env(isolated_env.env, state, server.url),
        )
    assert result.returncode == 2
    assert result.stderr.strip().startswith("agent-trace: no scope")
    assert server.requests == []
    assert not state.exists()


def test_missing_flag_exits_2_and_sends_nothing(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        result = run(["span", "start", "--id", "a", "--ticket", "RUN-1"], base_env(isolated_env.env, state, server.url))
    assert result.returncode == 2
    assert "--name" in result.stderr
    assert server.requests == []
    assert not state.exists()


def test_valid_start_sends_one_span_and_prints_nothing(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        result = run(
            ["span", "start", "--id", "build", "--name", "Build it", "--kind", "phase", "--ticket", "RUN-1"],
            base_env(isolated_env.env, state, server.url),
        )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert [r.path for r in server.requests] == ["/v1/traces"]
    [span] = server.spans()
    assert span["service"] == "agent-trace"
    assert span["name"] == "Build it"
    assert span["spanId"] == span_id("RUN-1", "build")
    assert span["traceId"] == trace_id("RUN-1")
    assert not span.get("parentSpanId")
    assert span["startTimeUnixNano"] == span["endTimeUnixNano"]
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["agent_trace.phase"] == {"stringValue": "start"}
    assert attrs["agent_trace.kind"] == {"stringValue": "phase"}
    assert attrs["agent_trace.id"] == {"stringValue": "build"}
    assert attrs["run.ticket"] == {"stringValue": "RUN-1"}
    assert attrs["agent_trace.scope"] == {"stringValue": "RUN-1"}
    assert not (state / "fallback.jsonl").exists()


def test_traceparent_sets_trace_and_parent_and_span_id_is_stable(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        env = base_env(isolated_env.env, state, server.url)
        start = run(
            ["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-1"],
            {**env, "TRACEPARENT": TP1},
        )
        end = run(
            ["span", "end", "--id", "build", "--status", "error", "--ticket", "RUN-1"], {**env, "TRACEPARENT": TP2}
        )
    assert start.returncode == end.returncode == 0
    first, second = server.spans()
    assert first["traceId"] == "0af7651916cd43dd8448eb211c80319c"
    assert first["parentSpanId"] == "b7ad6b7169203331"
    assert second["traceId"] == "11111111111111111111111111111111"
    assert first["spanId"] == second["spanId"] == span_id("RUN-1", "build")
    assert second["name"] == "build"
    assert second["status"]["code"] == 2


def test_parent_flag_overrides_traceparent(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        env = {**base_env(isolated_env.env, state, server.url), "TRACEPARENT": TP1}
        run(
            ["span", "start", "--id", "pr", "--name", "PR", "--kind", "pr", "--parent", "build", "--ticket", "RUN-1"],
            env,
        )
    [span] = server.spans()
    assert span["parentSpanId"] == span_id("RUN-1", "build")
    assert span["traceId"] == "0af7651916cd43dd8448eb211c80319c"


def test_ticket_binds_to_session_for_later_calls(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        env = base_env(isolated_env.env, state, server.url, CLAUDE_CODE_SESSION_ID="claude-s", AGENT_TRACE_SESSION="s1")
        run(["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-7"], env)
        result = run(["span", "end", "--id", "build", "--status", "ok", "--note", "done"], env)
    assert result.returncode == 0, result.stderr
    assert (state / "sessions" / "s1.ticket").read_text().strip() == "RUN-7"
    start, end = server.spans()
    end_attrs = {a["key"]: a["value"].get("stringValue") for a in end["attributes"]}
    assert end_attrs["run.ticket"] == "RUN-7"
    assert end_attrs["session.id"] == "s1"
    assert end_attrs["agent_trace.status"] == "ok"
    assert end_attrs["agent_trace.note"] == "done"
    assert end["spanId"] == start["spanId"]


def test_session_scope_without_ticket(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder() as server:
        env = base_env(isolated_env.env, state, server.url, CLAUDE_CODE_SESSION_ID="sess-9")
        result = run(["span", "start", "--id", "a", "--name", "A", "--kind", "check"], env)
    assert result.returncode == 0, result.stderr
    [span] = server.spans()
    assert span["spanId"] == span_id("sess-9", "a")
    attrs = {a["key"] for a in span["attributes"]}
    assert "run.ticket" not in attrs
    assert "session.id" in attrs


def test_notes_are_zero_length_spans_with_one_event(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    ref = "0123456789abcdef"
    with recorder() as server:
        env = base_env(isolated_env.env, state, server.url)
        friction = run(
            [
                "note",
                "friction",
                "--category",
                "permission",
                "--what",
                "W",
                "--fix",
                "F",
                "--ref",
                ref,
                "--ticket",
                "RUN-1",
            ],
            env,
        )
        none = run(["note", "none", "--ref", ref, "--ref", "gap-fedcba9876543210", "--ticket", "RUN-1"], env)
    assert friction.returncode == none.returncode == 0
    first, second = server.spans()
    for span in (first, second):
        assert span["name"] == "agent_trace.note"
        assert span["startTimeUnixNano"] == span["endTimeUnixNano"]
        assert len(span["events"]) == 1
    assert first["spanId"] != second["spanId"]
    attrs = {a["key"]: a["value"] for a in first["attributes"]}
    assert attrs["agent_trace.note_kind"] == {"stringValue": "friction"}
    assert attrs["agent_trace.category"] == {"stringValue": "permission"}
    assert attrs["agent_trace.what"] == {"stringValue": "W"}
    assert attrs["agent_trace.fix"] == {"stringValue": "F"}
    assert attrs["agent_trace.refs"] == {"arrayValue": {"values": [{"stringValue": ref}]}}
    assert first["events"][0]["name"] == "friction"
    second_attrs = {a["key"]: a["value"] for a in second["attributes"]}
    assert second_attrs["agent_trace.refs"]["arrayValue"]["values"][1] == {"stringValue": "gap-fedcba9876543210"}
    assert second["events"][0]["name"] == "none"


def test_fallback_when_collect_is_down(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    endpoint = f"http://127.0.0.1:{closed_port()}"
    result = run(
        ["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-1"],
        base_env(isolated_env.env, state, endpoint),
    )
    assert result.returncode == 0
    assert result.stdout == ""
    fallback = state / "fallback.jsonl"
    assert result.stderr.splitlines() == [f"agent-trace: collect not reachable at {endpoint}; wrote {fallback}"]
    [record] = read_jsonl(fallback)
    assert record["type"] == "span"
    assert record["service"] == "agent-trace"
    assert record["spanId"] == span_id("RUN-1", "build")
    assert record["attrs"]["agent_trace.kind"] == "phase"
    assert record["attrs"]["run.ticket"] == "RUN-1"
    assert isinstance(record["start"], int)
    assert stat.S_IMODE(fallback.stat().st_mode) == 0o600


def test_fallback_when_endpoint_is_not_collect(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder(collect_header=False) as jaeger:
        result = run(
            ["note", "none", "--ref", "0123456789abcdef", "--ticket", "RUN-1"],
            base_env(isolated_env.env, state, jaeger.url),
        )
    assert result.returncode == 0
    assert len(jaeger.requests) == 1
    assert "collect not reachable" in result.stderr
    [record] = read_jsonl(state / "fallback.jsonl")
    assert record["name"] == "agent_trace.note"
    assert record["attrs"]["agent_trace.refs"] == ["0123456789abcdef"]
