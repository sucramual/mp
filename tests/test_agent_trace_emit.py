"""Black-box tests for `agent-trace span` and `agent-trace note`: validation, OTLP mapping, and the fallback file.

Each test runs the real tool as a subprocess against a real `agent-trace collect`, and asserts on the records that
collect stored. The tool sends through the OpenTelemetry SDK (`uv run --script export.py`), so these tests also
prove that collect decodes what the SDK exporter sends (OTLP protobuf). AGENT_TRACE_DIR is a temporary directory.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from conftest import IsolatedEnv
from test_agent_trace_support import (
    base_env,
    closed_port,
    collect,
    read_jsonl,
    recorder,
    run,
    stored,
    wait_stored,
)

TP1 = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
TP2 = "00-11111111111111111111111111111111-2222222222222222-01"


def span_id(scope: str, ident: str) -> str:
    return hashlib.sha256(f"{scope}\0{ident}".encode()).hexdigest()[:16]


def trace_id(scope: str) -> str:
    return hashlib.sha256(f"agent-trace\0{scope}".encode()).hexdigest()[:32]


@dataclass
class Collected:
    env: dict[str, str]
    state: Path

    def records(self, count: int) -> list[dict[str, Any]]:
        return sorted(
            wait_stored(self.state, count), key=lambda r: (r["start"], r["attrs"].get("agent_trace.phase", ""))
        )


@pytest.fixture
def collected(isolated_env: IsolatedEnv, tmp_path: Path) -> Iterator[Collected]:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    with collect(env) as port:
        env["AGENT_TRACE_ENDPOINT"] = f"http://127.0.0.1:{port}"
        yield Collected(env, state)


def assert_nothing_written(state: Path) -> None:
    assert stored(state) == []
    assert not (state / "fallback.jsonl").exists()
    assert not (state / "sessions").exists()


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
    collected: Collected, args: list[str], message: str
) -> None:
    result = run([*args, "--ticket", "RUN-1"], {**collected.env, "CLAUDE_CODE_SESSION_ID": "s1"})
    assert result.returncode == 2
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("agent-trace: ")
    assert message in lines[0]
    assert result.stdout == ""
    time.sleep(0.2)
    assert_nothing_written(collected.state)


def test_bad_ticket_exits_2_and_sends_nothing(collected: Collected) -> None:
    env = {**collected.env, "CLAUDE_CODE_SESSION_ID": "s1"}
    result = run(["span", "start", "--id", "a", "--name", "x", "--kind", "phase", "--ticket", "abc-1"], env)
    assert result.returncode == 2
    assert result.stderr.strip().startswith("agent-trace: --ticket must match")
    time.sleep(0.2)
    assert_nothing_written(collected.state)


def test_no_scope_exits_2_and_sends_nothing(collected: Collected) -> None:
    result = run(["span", "start", "--id", "a", "--name", "x", "--kind", "phase"], collected.env)
    assert result.returncode == 2
    assert result.stderr.strip().startswith("agent-trace: no scope")
    time.sleep(0.2)
    assert_nothing_written(collected.state)


def test_missing_flag_exits_2_and_sends_nothing(collected: Collected) -> None:
    result = run(["span", "start", "--id", "a", "--ticket", "RUN-1"], collected.env)
    assert result.returncode == 2
    assert "--name" in result.stderr
    time.sleep(0.2)
    assert_nothing_written(collected.state)


def test_valid_start_stores_one_span_and_prints_nothing(collected: Collected) -> None:
    result = run(
        ["span", "start", "--id", "build", "--name", "Build it", "--kind", "phase", "--ticket", "RUN-1"],
        collected.env,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    [record] = collected.records(1)
    assert record["service"] == "agent-trace"
    assert record["name"] == "Build it"
    assert record["spanId"] == span_id("RUN-1", "build")
    assert record["traceId"] == trace_id("RUN-1")
    assert record["parentSpanId"] is None
    assert record["start"] == record["end"]
    assert record["attrs"]["agent_trace.phase"] == "start"
    assert record["attrs"]["agent_trace.kind"] == "phase"
    assert record["attrs"]["agent_trace.id"] == "build"
    assert record["attrs"]["run.ticket"] == "RUN-1"
    assert record["attrs"]["agent_trace.scope"] == "RUN-1"
    assert not (collected.state / "fallback.jsonl").exists()


def test_traceparent_sets_trace_and_parent_and_span_id_is_stable(collected: Collected) -> None:
    start = run(
        ["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-1"],
        {**collected.env, "TRACEPARENT": TP1},
    )
    end = run(
        ["span", "end", "--id", "build", "--status", "error", "--ticket", "RUN-1"],
        {**collected.env, "TRACEPARENT": TP2},
    )
    assert (start.returncode, start.stderr, end.returncode, end.stderr) == (0, "", 0, "")
    first, second = collected.records(2)
    assert first["traceId"] == "0af7651916cd43dd8448eb211c80319c"
    assert first["parentSpanId"] == "b7ad6b7169203331"
    assert second["traceId"] == "11111111111111111111111111111111"
    assert first["spanId"] == second["spanId"] == span_id("RUN-1", "build")
    assert second["name"] == "build"
    assert second["status"]["code"] == 2


def test_unsampled_traceparent_still_records(collected: Collected) -> None:
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-00"
    result = run(
        ["span", "start", "--id", "a", "--name", "A", "--kind", "check", "--ticket", "RUN-1"],
        {**collected.env, "TRACEPARENT": tp, "OTEL_SDK_DISABLED": "true", "OTEL_TRACES_SAMPLER": "always_off"},
    )
    assert (result.returncode, result.stderr) == (0, "")
    [record] = collected.records(1)
    assert record["parentSpanId"] == "b7ad6b7169203331"


def test_parent_flag_overrides_traceparent(collected: Collected) -> None:
    env = {**collected.env, "TRACEPARENT": TP1}
    args = ["span", "start", "--id", "pr", "--name", "PR", "--kind", "pr", "--parent", "build", "--ticket", "RUN-1"]
    assert run(args, env).returncode == 0
    [record] = collected.records(1)
    assert record["parentSpanId"] == span_id("RUN-1", "build")
    assert record["traceId"] == "0af7651916cd43dd8448eb211c80319c"


def test_ticket_binds_to_session_for_later_calls(collected: Collected) -> None:
    env = {**collected.env, "CLAUDE_CODE_SESSION_ID": "claude-s", "AGENT_TRACE_SESSION": "s1"}
    run(["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-7"], env)
    result = run(["span", "end", "--id", "build", "--status", "ok", "--note", "done"], env)
    assert result.returncode == 0, result.stderr
    assert (collected.state / "sessions" / "s1.ticket").read_text().strip() == "RUN-7"
    start, end = collected.records(2)
    assert end["attrs"]["run.ticket"] == "RUN-7"
    assert end["attrs"]["session.id"] == "s1"
    assert end["attrs"]["agent_trace.status"] == "ok"
    assert end["attrs"]["agent_trace.note"] == "done"
    assert end["spanId"] == start["spanId"]


def test_session_scope_without_ticket(collected: Collected) -> None:
    env = {**collected.env, "CLAUDE_CODE_SESSION_ID": "sess-9"}
    result = run(["span", "start", "--id", "a", "--name", "A", "--kind", "check"], env)
    assert result.returncode == 0, result.stderr
    [record] = collected.records(1)
    assert record["spanId"] == span_id("sess-9", "a")
    assert "run.ticket" not in record["attrs"]
    assert record["attrs"]["session.id"] == "sess-9"


def test_codex_thread_id_binds_ticket_for_later_calls(collected: Collected) -> None:
    env = {**collected.env, "CODEX_THREAD_ID": "codex-t1"}
    run(["span", "start", "--id", "impl", "--name", "Implement", "--kind", "phase", "--ticket", "RUN-1"], env)
    result = run(["span", "end", "--id", "impl", "--status", "ok"], env)
    assert result.returncode == 0, result.stderr
    assert (collected.state / "sessions" / "codex-t1.ticket").read_text().strip() == "RUN-1"
    _, end = collected.records(2)
    assert end["attrs"]["session.id"] == "codex-t1"
    assert end["attrs"]["run.ticket"] == "RUN-1"


def test_notes_are_zero_length_spans_with_one_event(collected: Collected) -> None:
    ref = "0123456789abcdef"
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
        collected.env,
    )
    none = run(["note", "none", "--ref", ref, "--ref", "gap-fedcba9876543210", "--ticket", "RUN-1"], collected.env)
    assert (friction.returncode, friction.stderr, none.returncode, none.stderr) == (0, "", 0, "")
    first, second = collected.records(2)
    for record in (first, second):
        assert record["name"] == "agent_trace.note"
        assert record["start"] == record["end"]
        assert len(record["events"]) == 1
    assert first["spanId"] != second["spanId"]
    assert first["attrs"]["agent_trace.note_kind"] == "friction"
    assert first["attrs"]["agent_trace.category"] == "permission"
    assert first["attrs"]["agent_trace.what"] == "W"
    assert first["attrs"]["agent_trace.fix"] == "F"
    assert first["attrs"]["agent_trace.refs"] == [ref]
    assert first["events"][0]["name"] == "friction"
    assert second["attrs"]["agent_trace.refs"] == [ref, "gap-fedcba9876543210"]
    assert second["events"][0]["name"] == "none"


def test_sdk_fallback_when_collect_is_down_is_fast_and_quiet(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    endpoint = f"http://127.0.0.1:{closed_port()}"
    env = {**base_env(isolated_env.env, state, endpoint), "TRACEPARENT": TP1}
    began = time.monotonic()
    result = run(["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-1"], env)
    elapsed = time.monotonic() - began
    assert result.returncode == 0
    assert result.stdout == ""
    assert elapsed < 3.0
    fallback = state / "fallback.jsonl"
    assert result.stderr.splitlines() == [f"agent-trace: collect not reachable at {endpoint}; wrote {fallback}"]
    [record] = read_jsonl(fallback)
    assert record["type"] == "span"
    assert record["service"] == "agent-trace"
    assert record["spanId"] == span_id("RUN-1", "build")
    assert record["traceId"] == "0af7651916cd43dd8448eb211c80319c"
    assert record["parentSpanId"] == "b7ad6b7169203331"
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
    assert len(result.stderr.splitlines()) == 1
    assert "collect not reachable" in result.stderr
    [record] = read_jsonl(state / "fallback.jsonl")
    assert record["name"] == "agent_trace.note"
    assert record["attrs"]["agent_trace.refs"] == ["0123456789abcdef"]


def test_without_uv_the_stdlib_writes_the_fallback(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    no_uv = tmp_path / "no-uv-bin"
    no_uv.mkdir()
    (no_uv / "python3").symlink_to(sys.executable)
    env = base_env(isolated_env.env, state, f"http://127.0.0.1:{closed_port()}", real_uv=False)
    env.update(PATH=f"{no_uv}{os.pathsep}/usr/bin{os.pathsep}/bin", TRACEPARENT=TP1)
    result = run(["span", "start", "--id", "build", "--name", "Build", "--kind", "phase", "--ticket", "RUN-1"], env)
    assert (result.returncode, result.stdout) == (0, "")
    fallback = state / "fallback.jsonl"
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.splitlines() == [f"agent-trace: cannot send (uv not found); wrote {fallback}"]
    [record] = read_jsonl(fallback)
    assert record["spanId"] == span_id("RUN-1", "build")
    assert record["traceId"] == trace_id("RUN-1")
    assert record["parentSpanId"] is None
    assert record["attrs"]["agent_trace.phase"] == "start"
