"""Black-box tests for `agent-trace collect`, the local OTLP/HTTP JSON receiver.

Each test starts the real collect as a subprocess on a free local port and stops it when the test ends.
The OTLP requests are small hand-built fixtures in tests/fixtures/agent_trace/ with anonymized identities.
"""

from __future__ import annotations

import base64
import gzip
import json
import socket
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from conftest import IsolatedEnv
from test_agent_trace_support import (
    FIXTURES,
    base_env,
    closed_port,
    collect,
    health,
    kill_matching,
    post,
    read_jsonl,
    recorder,
    run,
)

ID_KEYS = {"traceId", "spanId", "parentSpanId"}


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def stored(spans_dir: Path) -> list[dict[str, Any]]:
    return [record for path in sorted(spans_dir.glob("*.jsonl")) for record in read_jsonl(path)]


def wait_for_records(spans_dir: Path, count: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 5
    while len(records := stored(spans_dir)) < count and time.monotonic() < deadline:
        time.sleep(0.02)
    return records


def test_health_answers_with_the_collect_header(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    env = base_env(isolated_env.env, tmp_path / "state", "")
    with collect(env) as port:
        answer = health(port)
    assert answer is not None
    status, headers, body = answer
    assert status == 200
    assert headers["X-Agent-Trace"] == "collect"
    assert body == {"agent_trace": "collect"}


def test_stores_flat_records_in_the_utc_day_file(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    before = datetime.now(UTC).strftime("%Y-%m-%d")
    with collect(env) as port:
        assert post(port, "/v1/traces", (FIXTURES / "claude_traces.json").read_bytes()) == 200
        records = wait_for_records(state / "spans", 5)
    after = datetime.now(UTC).strftime("%Y-%m-%d")
    files = [path.name for path in (state / "spans").glob("*.jsonl")]
    assert files in ([f"{before}.jsonl"], [f"{after}.jsonl"])
    assert len(records) == 5
    by_name = {record["name"]: record for record in records}
    execution = by_name["claude_code.tool.execution"]
    assert execution["type"] == "span"
    assert execution["service"] == "claude-code"
    assert execution["status"] == {"code": 2, "message": "ShellError"}
    assert execution["attrs"]["success"] is False
    assert execution["parentSpanId"] == "1000000000000003"
    assert isinstance(execution["start"], int)
    llm = by_name["claude_code.llm_request"]
    assert llm["attrs"]["attempt"] == 2
    assert llm["events"][0]["attrs"] == {"attempt": 2}
    assert stat.S_IMODE((state / "spans").stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "spans" / files[0]).stat().st_mode) == 0o600


def test_codex_allowlist_keeps_turns_and_tools_and_drops_output(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    with collect(env) as port:
        assert post(port, "/v1/traces", (FIXTURES / "codex_traces.json").read_bytes()) == 200
        assert post(port, "/v1/logs", (FIXTURES / "codex_logs.json").read_bytes()) == 200
        records = wait_for_records(state / "spans", 7)
    spans = sorted(r["name"] for r in records if r["type"] == "span")
    assert spans == ["exec_command", "handle_tool_call", "run_sampling_request", "run_turn", "session_task.turn"]
    logs = {r["attrs"]["event.name"]: r for r in records if r["type"] == "log"}
    assert sorted(logs) == ["codex.tool_decision", "codex.tool_result"]
    result = logs["codex.tool_result"]
    assert result["service"] == "codex_exec"
    assert "output" not in result["attrs"]
    assert len(result["attrs"]["arguments"]) == 200
    assert result["attrs"]["success"] is False
    assert result["time"] == 1793350806_000_000_000


def test_unknown_service_is_dropped(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    doc = fixture("claude_traces.json")
    other = json.loads(json.dumps(doc["resourceSpans"][0]))
    other["resource"]["attributes"] = [{"key": "service.name", "value": {"stringValue": "other-app"}}]
    doc["resourceSpans"].append(other)
    with collect(env) as port:
        assert post(port, "/v1/traces", json.dumps(doc).encode()) == 200
        records = wait_for_records(state / "spans", 5)
        time.sleep(0.2)
        records = stored(state / "spans")
    assert len(records) == 5
    assert {r["service"] for r in records} == {"claude-code"}


def test_gzip_body_is_accepted(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    body = gzip.compress((FIXTURES / "claude_traces.json").read_bytes())
    with collect(env) as port:
        assert post(port, "/v1/traces", body, **{"Content-Encoding": "gzip"}) == 200
        records = wait_for_records(state / "spans", 5)
    assert len(records) == 5


def test_unknown_type_gets_415_and_bad_bodies_400_and_nothing_is_stored(
    isolated_env: IsolatedEnv, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    with collect(env) as port:
        assert post(port, "/v1/traces", b"hello", content_type="text/plain") == 415
        assert post(port, "/v1/traces", b"\xff\xff\xff", content_type="application/x-protobuf") == 400
        assert post(port, "/v1/traces", b"{not json") == 400
        assert post(port, "/v1/logs", b"[1, 2]") == 400
        assert post(port, "/v1/metrics", b"{}") == 404
        time.sleep(0.2)
        assert stored(state / "spans") == []
        assert post(port, "/v1/traces", (FIXTURES / "claude_traces.json").read_bytes()) == 200
        assert len(wait_for_records(state / "spans", 5)) == 5


def test_protobuf_requests_are_decoded_like_json(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    from google.protobuf.json_format import ParseDict
    from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    def to_base64_ids(doc: Any) -> Any:
        # Protobuf JSON writes bytes as base64; OTLP JSON fixtures use hex ids.
        if isinstance(doc, dict):
            return {
                k: base64.b64encode(bytes.fromhex(v)).decode() if k in ID_KEYS and v else to_base64_ids(v)
                for k, v in doc.items()
            }
        if isinstance(doc, list):
            return [to_base64_ids(item) for item in doc]
        return doc

    traces = ParseDict(to_base64_ids(fixture("claude_traces.json")), ExportTraceServiceRequest())
    logs = ParseDict(to_base64_ids(fixture("codex_logs.json")), ExportLogsServiceRequest())
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    with collect(env) as port:
        assert post(port, "/v1/traces", traces.SerializeToString(), content_type="application/x-protobuf") == 200
        assert post(port, "/v1/logs", logs.SerializeToString(), content_type="application/x-protobuf") == 200
        records = wait_for_records(state / "spans", 7)
    spans = {r["name"]: r for r in records if r["type"] == "span"}
    assert len(spans) == 5
    execution = spans["claude_code.tool.execution"]
    assert execution["traceId"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert execution["spanId"] == "1000000000000005"
    assert execution["parentSpanId"] == "1000000000000003"
    assert execution["status"] == {"code": 2, "message": "ShellError"}
    assert execution["attrs"]["success"] is False
    assert spans["claude_code.llm_request"]["attrs"]["attempt"] == 2
    assert spans["claude_code.interaction"]["start"] == 1793350800_000_000_000
    logs_by_name = {r["attrs"]["event.name"]: r for r in records if r["type"] == "log"}
    assert sorted(logs_by_name) == ["codex.tool_decision", "codex.tool_result"]
    assert "output" not in logs_by_name["codex.tool_result"]["attrs"]
    assert logs_by_name["codex.tool_result"]["spanId"] == "2000000000000005"


def test_forward_sends_native_records_but_not_agent_trace_ones(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder(collect_header=False) as jaeger:
        env = base_env(isolated_env.env, state, "")
        with collect(env, "--forward", jaeger.url) as port:
            emit_env = {**env, "AGENT_TRACE_ENDPOINT": f"http://127.0.0.1:{port}"}
            emitted = run(
                ["span", "start", "--id", "a", "--name", "A", "--kind", "phase", "--ticket", "RUN-1"], emit_env
            )
            assert (emitted.returncode, emitted.stderr) == (0, "")
            assert post(port, "/v1/traces", (FIXTURES / "claude_traces.json").read_bytes()) == 200
            assert post(port, "/v1/logs", (FIXTURES / "codex_logs.json").read_bytes()) == 200
            jaeger.wait_for(2)
            time.sleep(0.3)
        records = stored(state / "spans")
    assert {r["service"] for r in records} == {"agent-trace", "claude-code", "codex_exec"}
    assert sorted(r.path for r in jaeger.requests) == ["/v1/logs", "/v1/traces"]
    assert {s["service"] for s in jaeger.spans()} == {"claude-code"}
    assert len(jaeger.spans()) == 5
    [logs] = [r.body for r in jaeger.requests if r.path == "/v1/logs"]
    forwarded = logs["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    assert len(forwarded) == 2
    assert "SECRET-OUTPUT" not in json.dumps(logs)


def test_port_in_use_exits_1_with_message(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        result = run(["collect", "--port", str(port)], base_env(isolated_env.env, tmp_path / "state", ""))
    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"agent-trace collect: port {port} is in use (another OTLP receiver such as Jaeger?)"
    )


def test_ensure_starts_one_detached_collect(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = base_env(isolated_env.env, state, "")
    port = closed_port()
    try:
        first = run(["collect", "--ensure", "--port", str(port)], env)
        assert first.returncode == 0, first.stderr
        answer = health(port)
        assert answer is not None and answer[1]["X-Agent-Trace"] == "collect"
        second = run(["collect", "--ensure", "--port", str(port)], env)
        assert second.returncode == 0, second.stderr
        log = (state / "collect.log").read_text()
        assert log.count("agent-trace collect: listening on") == 1
    finally:
        kill_matching(str(state))


def test_ensure_fails_when_another_receiver_owns_the_port(isolated_env: IsolatedEnv, tmp_path: Path) -> None:
    state = tmp_path / "state"
    with recorder(collect_header=False) as jaeger:
        try:
            result = run(["collect", "--ensure", "--port", str(jaeger.port)], base_env(isolated_env.env, state, ""))
        finally:
            kill_matching(str(state))
    assert result.returncode == 1
    assert f"agent-trace collect: port {jaeger.port} is in use" in result.stderr
