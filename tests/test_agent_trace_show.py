"""Black-box tests for `agent-trace show`, the joined timeline of a ticket or sessions.

Each test writes stored records (the flat shape that collect and the fallback file use) to a temporary
AGENT_TRACE_DIR, runs the real tool with TZ=UTC, and parses its text output.

The main scenario, all on 2026-10-30 (UTC), ticket RUN-1, Claude session S1:
  09:00-09:20  interaction 1; 09:05 a Bash `false` tool fails; 09:06 the same tool runs again (a retry)
  09:20-11:40  no activity (2h20m: one idle column, and one reconcile gap)
  11:40-12:00  interaction 2; 11:41:30 an LLM request retry; 11:45-11:50 a rejected permission prompt
Agent spans: Implement 09:01-11:55 ok; Review 09:10-09:15 error; Review again 11:43-11:44 ok (a retry);
Wait for CI (kind wait) 11:51-11:54 parked; Deploy from 11:56, never ended (open).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT, IsolatedEnv
from test_agent_trace_support import FIXTURES, base_env, collect, post, recorder, run

M = 60 * 1_000_000_000
S = 1_000_000_000
T0 = 1793350800 * S  # 2026-10-30T09:00:00Z
S1 = "aaaaaaaa-0000-4000-8000-000000000001"
S2 = "bbbbbbbb-0000-4000-8000-000000000002"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
IDENTITY = {"user.email": "user@example.com", "organization.id": "org-0000-secret", "user.account_uuid": "acct-uuid-1"}
HEAD = "0123456789abcdef0123456789abcdef01234567"
MOVED = "fedcba9876543210fedcba9876543210fedcba98"
MERGE = "abcdef0123456789abcdef0123456789abcdef01"
PR_URL = "https://github.com/acme/widgets/pull/42"
ROW = re.compile(r"^(?P<name>.*?) +\|(?P<bar>[^|]*)\| +(?P<dur>\S+)(?: (?P<status>\S+))?$")


def at(hour: int, minute: int, second: int = 0) -> int:
    return T0 + ((hour - 9) * 60 + minute) * M + second * S


def sid(scope: str, ident: str) -> str:
    return hashlib.sha256(f"{scope}\0{ident}".encode()).hexdigest()[:16]


def native(span_id: str, name: str, start: int, end: int, parent: str | None, **attrs: Any) -> dict[str, Any]:
    status = attrs.pop("status", {"code": 0, "message": ""})
    events = attrs.pop("events", [])
    return {
        "type": "span",
        "service": "claude-code",
        "traceId": TRACE,
        "spanId": span_id,
        "parentSpanId": parent,
        "name": name,
        "start": start,
        "end": end,
        "status": status,
        "attrs": {**IDENTITY, "session.id": S1, **attrs},
        "events": events,
    }


def agent(
    ident: str, phase: str, when: int, *, ticket: str = "RUN-1", session: str = S1, **attrs: Any
) -> dict[str, Any]:
    name = attrs.pop("name", ident)
    return {
        "type": "span",
        "service": "agent-trace",
        "traceId": "0" * 31 + "1",
        "spanId": sid(ticket, ident),
        "parentSpanId": None,
        "name": name,
        "start": when,
        "end": when,
        "status": {"code": 2 if attrs.get("agent_trace.status") == "error" else 0, "message": ""},
        "attrs": {
            "session.id": session,
            "run.ticket": ticket,
            "agent_trace.scope": ticket,
            "agent_trace.phase": phase,
            "agent_trace.id": ident,
            **attrs,
        },
        "events": [],
    }


def note(kind: str, when: int, refs: list[str], **attrs: Any) -> dict[str, Any]:
    record = agent("note", "x", when, name="agent_trace.note")
    record["spanId"] = hashlib.sha256(f"{when}{refs}".encode()).hexdigest()[:16]
    for key in ("agent_trace.phase", "agent_trace.id"):
        record["attrs"].pop(key)
    record["attrs"].update({"agent_trace.note_kind": kind, "agent_trace.refs": refs, **attrs})
    return record


def pr(action: str, when: int, head: str = HEAD) -> dict[str, Any]:
    record = agent("pr", "x", when, name="agent_trace.pr")
    record["spanId"] = hashlib.sha256(f"pr{action}{when}".encode()).hexdigest()[:16]
    for key in ("agent_trace.phase", "agent_trace.id"):
        record["attrs"].pop(key)
    record["attrs"].update(
        {"agent_trace.pr_action": action, "agent_trace.pr_url": PR_URL, "agent_trace.repo": "acme/widgets"}
    )
    record["attrs"]["agent_trace.head_sha"] = head
    return record


def scenario() -> list[dict[str, Any]]:
    return [
        native("a000000000000001", "claude_code.interaction", at(9, 0), at(9, 20), "00f067aa0ba902b7"),
        native(
            "a000000000000002",
            "claude_code.tool",
            at(9, 5),
            at(9, 5, 10),
            "a000000000000001",
            tool_name="Bash",
            bash_argv0="false",
        ),
        native(
            "a000000000000003",
            "claude_code.tool.execution",
            at(9, 5),
            at(9, 5, 10),
            "a000000000000002",
            success=False,
            error_class="ShellError",
            status={"code": 2, "message": "ShellError"},
        ),
        native(
            "a000000000000004",
            "claude_code.tool",
            at(9, 6),
            at(9, 6, 5),
            "a000000000000001",
            tool_name="Bash",
            bash_argv0="false",
        ),
        native(
            "a000000000000005", "claude_code.tool.execution", at(9, 6), at(9, 6, 5), "a000000000000004", success=True
        ),
        native("a000000000000010", "claude_code.interaction", at(11, 40), at(12, 0), "00f067aa0ba902b7"),
        native(
            "a000000000000011",
            "claude_code.llm_request",
            at(11, 41),
            at(11, 42),
            "a000000000000010",
            events=[{"name": "gen_ai.request.attempt", "time": at(11, 41, 30), "attrs": {"attempt": 2}}],
        ),
        native(
            "a000000000000013",
            "claude_code.tool",
            at(11, 45),
            at(11, 50, 10),
            "a000000000000010",
            tool_name="Bash",
            bash_argv0="git",
        ),
        native(
            "a000000000000012",
            "claude_code.tool.blocked_on_user",
            at(11, 45),
            at(11, 50),
            "a000000000000013",
            decision="reject",
            source="hook",
        ),
        agent("impl", "start", at(9, 1), name="Implement", **{"agent_trace.kind": "phase"}),
        agent(
            "review-1", "start", at(9, 10), name="Review", **{"agent_trace.kind": "pr", "agent_trace.parent": "impl"}
        ),
        agent("review-1", "end", at(9, 15), **{"agent_trace.status": "error"}),
        agent(
            "review-2", "start", at(11, 43), name="Review", **{"agent_trace.kind": "pr", "agent_trace.parent": "impl"}
        ),
        agent("review-2", "end", at(11, 44), **{"agent_trace.status": "ok"}),
        agent(
            "wait-ci",
            "start",
            at(11, 51),
            name="Wait for CI",
            **{"agent_trace.kind": "wait", "agent_trace.parent": "impl"},
        ),
        agent("wait-ci", "end", at(11, 54), **{"agent_trace.status": "parked", "agent_trace.note": "waiting on CI"}),
        agent("impl", "end", at(11, 55), **{"agent_trace.status": "ok"}),
        agent("deploy", "start", at(11, 56), name="Deploy", **{"agent_trace.kind": "infra"}),
    ]


def write_store(state: Path, records: list[dict[str, Any]], *, fallback: list[dict[str, Any]] | None = None) -> None:
    (state / "spans").mkdir(parents=True, exist_ok=True)
    (state / "spans" / "2026-10-30.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    if fallback:
        (state / "fallback.jsonl").write_text("".join(json.dumps(r) + "\n" for r in fallback))


def show(env: dict[str, str], *args: str) -> tuple[int, str, str]:
    result = run(["show", *args], env)
    return result.returncode, result.stdout, result.stderr


def fence(output: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index("```text")
    return lines[start + 1 : lines.index("```", start + 1)]


def rows(output: str) -> list[dict[str, str]]:
    out = []
    for line in fence(output):
        match = ROW.match(line)
        if match:
            out.append({key: value or "" for key, value in match.groupdict().items()})
    return out


def reconcile(output: str) -> list[list[str]]:
    lines = output.splitlines()
    start = lines.index("Reconcile:")
    entries = []
    for line in lines[start + 1 :]:
        if not line.startswith("  ") or line.startswith("  agent-trace") or not line.strip():
            break
        entries.append(line.split(None, 3))
    return entries


@pytest.fixture
def env(isolated_env: IsolatedEnv, tmp_path: Path) -> dict[str, str]:
    return base_env(
        isolated_env.env, tmp_path / "state", "http://127.0.0.1:9", AGENT_TRACE_CLAUDE_PROJECTS=str(tmp_path / "none")
    )


def state_of(env: dict[str, str]) -> Path:
    return Path(env["AGENT_TRACE_DIR"])


def test_rows_tree_statuses_and_summary(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    code, out, err = show(env, "--ticket", "RUN-1", "--offline")
    assert code == 0, err
    got = [(r["name"], r["dur"], r["status"]) for r in rows(out)]
    assert got == [
        ("run RUN-1", "3h00m", ""),
        ("  Implement", "2h54m", "ok"),
        ("    Review", "5m", "error"),
        ("    Review", "1m", "ok"),
        ("    Wait for CI", "3m", "parked"),
        ("  Deploy", "4m", "open"),
        ("  claude aaaaaaaa", "40m", ""),
    ]
    assert len({len(r["bar"]) for r in rows(out)}) == 1
    assert "total 3h00m · active 32m · wait on Marcus 8m · errors 2 · retries 3 · open spans 1" in out.splitlines()


def test_idle_gap_is_one_column_in_every_row_and_labelled(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    bars = [r["bar"] for r in rows(out)]
    columns = {i for bar in bars for i, ch in enumerate(bar) if ch == "┆"}
    assert len(columns) == 1
    assert all(bar[next(iter(columns))] == "┆" for bar in bars)
    assert len(bars[0]) == 60
    text = "\n".join(fence(out))
    assert "┆ 2h20m idle" in text
    assert "09:00" in text and "12:00" in text


def test_error_retry_and_wait_markers(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    by_name = {}
    for r in rows(out):
        by_name.setdefault(r["name"].strip(), []).append(r["bar"])
    session = by_name["claude aaaaaaaa"][0]
    assert "✗" in session
    assert session.count("↻") == 2
    assert "▒" in session
    assert session.index("✗") < session.index("↻")
    first_review, second_review = by_name["Review"]
    assert "✗" in first_review and "↻" not in first_review
    assert "↻" in second_review
    assert "▒" in by_name["Wait for CI"][0]
    assert "▒" not in by_name["Deploy"][0]


def test_reconcile_lists_each_unanswered_anomaly(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    entries = reconcile(out)
    assert [(e[0], e[1], e[2]) for e in entries] == [
        ("a000000000000003", "09:05", "error"),
        ("a000000000000004", "09:06", "retry"),
        ("gap-a000000000000010", "09:20", "gap"),
        ("a000000000000011", "11:41", "retry"),
        ("a000000000000012", "11:45", "block"),
    ]
    assert entries[0][3] == "Bash false ShellError"
    assert "agent-trace note friction" in out
    assert "agent-trace note none --ref" in out


def test_note_none_answers_its_ref(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario(), fallback=[note("none", at(12, 30), ["a000000000000003"])])
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    refs = [e[0] for e in reconcile(out)]
    assert "a000000000000003" not in refs
    assert refs == ["a000000000000004", "gap-a000000000000010", "a000000000000011", "a000000000000012"]


def test_nearby_friction_note_answers_anomalies_in_its_window(env: dict[str, str]) -> None:
    friction = note(
        "friction",
        at(9, 7),
        [],
        **{"agent_trace.category": "flaky", "agent_trace.what": "false failed", "agent_trace.fix": "retry it"},
    )
    write_store(state_of(env), [*scenario(), friction])
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    refs = [e[0] for e in reconcile(out)]
    assert refs == ["gap-a000000000000010", "a000000000000011", "a000000000000012"]
    assert "flaky: false failed (fix: retry it)" in out


def test_all_answered_prints_reconcile_none(env: dict[str, str]) -> None:
    refs = ["a000000000000003", "a000000000000004", "gap-a000000000000010", "a000000000000011", "a000000000000012"]
    write_store(state_of(env), [*scenario(), note("none", at(12, 1), refs)])
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    assert "Reconcile: none" in out.splitlines()
    assert "run RUN-1" in out


def test_parks_and_identity_never_printed(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline")
    assert "  wait-ci  waiting on CI" in out.splitlines()
    for secret in IDENTITY.values():
        assert secret not in out
    assert "run RUN-1" in out


def test_prs_with_github_state_and_head_moved(env: dict[str, str], isolated_env: IsolatedEnv, fake_exe: Any) -> None:
    fake_exe(
        "gh",
        f"""printf '%s\\n' "$*" >>"$HOME/gh.log"
printf '%s' '{{"state":"MERGED","headRefOid":"{MOVED}","mergeCommit":{{"oid":"{MERGE}"}}}}'
""",
    )
    write_store(state_of(env), [*scenario(), pr("create", at(9, 30)), pr("merge", at(11, 58))])
    _, out, _ = show(env, "--ticket", "RUN-1")
    [line] = [line for line in out.splitlines() if PR_URL in line]
    assert "create, merge" in line
    assert "head 0123456" in line
    assert "merge abcdef0" in line
    assert "head moved" in line
    assert (isolated_env.home / "gh.log").read_text().split() == [
        "pr",
        "view",
        PR_URL,
        "--json",
        "state,headRefOid,mergeCommit",
    ]


def test_prs_offline_skips_github_and_gh_failure_is_reported(
    env: dict[str, str], isolated_env: IsolatedEnv, fake_exe: Any
) -> None:
    fake_exe("gh", 'printf x >>"$HOME/gh.log"\nexit 1\n')
    write_store(state_of(env), [*scenario(), pr("merge", at(11, 58))])
    _, offline, _ = show(env, "--ticket", "RUN-1", "--offline")
    [line] = [line for line in offline.splitlines() if PR_URL in line]
    assert "merge" in line
    assert not (isolated_env.home / "gh.log").exists()
    _, online, _ = show(env, "--ticket", "RUN-1")
    [line] = [line for line in online.splitlines() if PR_URL in line]
    assert "merge sha unknown (gh failed)" in line
    assert (isolated_env.home / "gh.log").exists()


def test_codex_session_row_and_tool_failure(env: dict[str, str]) -> None:
    trace = "171f36672a083c4bc41232663bf6fbb4"

    def codex(span_id: str, name: str, start: int, end: int, **attrs: Any) -> dict[str, Any]:
        record = native(span_id, name, start, end, None, **attrs)
        record.update(service="codex_exec", traceId=trace)
        record["attrs"].pop("session.id")
        return record

    records = [
        codex("b000000000000001", "session_task.turn", at(9, 0), at(9, 10), **{"thread.id": S2}),
        codex("b000000000000002", "run_turn", at(9, 0), at(9, 10), **{"thread.id": "13"}),
        codex("b000000000000003", "exec_command", at(9, 4), at(9, 5), **{"thread.id": "6"}),
        {
            "type": "log",
            "service": "codex_exec",
            "time": at(9, 5),
            "traceId": trace,
            "spanId": "b000000000000003",
            "attrs": {
                "event.name": "codex.tool_result",
                "conversation.id": S2,
                "tool_name": "exec_command",
                "success": False,
                **IDENTITY,
            },
        },
    ]
    write_store(state_of(env), records)
    code, out, err = show(env, "--session", S2, "--offline")
    assert code == 0, err
    got = [(r["name"], r["dur"]) for r in rows(out)]
    assert got == [("run bbbbbbbb", "10m"), ("  codex bbbbbbbb", "10m")]
    assert "✗" in rows(out)[1]["bar"]
    assert "errors 1" in out
    assert [e[:3] for e in reconcile(out)] == [["b000000000000003", "09:05", "error"]]
    assert "user@example.com" not in out


def test_missing_native_spans_warns_and_falls_back_to_the_transcript(env: dict[str, str], tmp_path: Path) -> None:
    session = "cccccccc-0000-4000-8000-000000000003"
    records = [
        agent(
            "impl",
            "start",
            at(9, 0),
            ticket="RUN-2",
            session=session,
            name="Implement",
            **{"agent_trace.kind": "phase"},
        ),
        agent("impl", "end", at(9, 30), ticket="RUN-2", session=session, **{"agent_trace.status": "ok"}),
    ]
    write_store(state_of(env), records)
    projects = tmp_path / "projects"
    (projects / "-Users-x-repo").mkdir(parents=True)
    transcript = (REPO_ROOT / "tests" / "fixtures" / "retro" / "local_session.jsonl").read_text()
    (projects / "-Users-x-repo" / f"{session}.jsonl").write_text(transcript.replace("local-session-7", session))
    code, out, err = show({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--ticket", "RUN-2", "--offline")
    assert code == 0, err
    lines = out.splitlines()
    warning = f"warning: session {session} has no native spans (collect was down or telemetry was off)"
    assert warning in lines
    assert f"Transcript timeline for {session}:" in lines
    assert any(line.startswith(f"session {session}") for line in lines)
    assert [(r["name"], r["status"]) for r in rows(out)] == [("run RUN-2", ""), ("  Implement", "ok")]


def test_jaeger_gets_one_joined_trace_without_identity(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    with recorder(collect_header=False) as jaeger:
        code, out, err = show(env, "--ticket", "RUN-1", "--offline", "--jaeger", jaeger.url)
    assert code == 0, err
    assert [r.path for r in jaeger.requests] == ["/v1/traces"]
    body = json.dumps(jaeger.requests[0].body)
    for secret in IDENTITY.values():
        assert secret not in body
    spans = jaeger.spans()
    run_trace = hashlib.sha256(b"agent-trace\0RUN-1").hexdigest()[:32]
    assert {s["traceId"] for s in spans} == {run_trace}
    ids = {s["spanId"] for s in spans}
    root = sid("RUN-1", "run")
    [root_span] = [s for s in spans if s["spanId"] == root]
    assert root_span["name"] == "run RUN-1"
    assert not root_span.get("parentSpanId")
    assert all(s.get("parentSpanId") in ids for s in spans if s["spanId"] != root)
    interaction = next(s for s in spans if s["spanId"] == "a000000000000001")
    assert interaction["parentSpanId"] == root
    review = next(s for s in spans if s["spanId"] == sid("RUN-1", "review-1"))
    assert review["parentSpanId"] == sid("RUN-1", "impl")
    deploy = next(s for s in spans if s["spanId"] == sid("RUN-1", "deploy"))
    assert {"key": "agent_trace.open", "value": {"boolValue": True}} in deploy["attributes"]
    assert f"jaeger: posted {len(spans)} spans, trace {run_trace}" in out.splitlines()


def test_nothing_matched_exits_1(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    code, out, err = show(env, "--ticket", "NOPE-9")
    assert code == 1
    assert err.strip() == "agent-trace: no spans for ticket NOPE-9"
    assert out == ""


def test_needs_a_ticket_or_session(env: dict[str, str]) -> None:
    code, _, err = show(env)
    assert code == 2
    assert "--ticket or --session" in err


def test_narrow_width_moves_the_idle_label_to_a_footnote(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--ticket", "RUN-1", "--offline", "--width", "20")
    assert {len(r["bar"]) for r in rows(out)} == {20}
    assert "┆ = 2h20m idle (09:20–11:40)" in fence(out)


def test_collected_native_spans_join_emitted_agent_spans(env: dict[str, str]) -> None:
    session = "aaaaaaaa-0000-4000-8000-000000000001"  # the session id in claude_traces.json
    emit_env = {**env, "CLAUDE_CODE_SESSION_ID": session}
    with collect(env) as port:
        emit_env["AGENT_TRACE_ENDPOINT"] = f"http://127.0.0.1:{port}"
        assert post(port, "/v1/traces", (FIXTURES / "claude_traces.json").read_bytes()) == 200
        for args in (
            ["span", "start", "--id", "impl", "--name", "Implement", "--kind", "phase", "--ticket", "RUN-5"],
            ["span", "end", "--id", "impl", "--status", "ok"],
        ):
            result = run(args, emit_env)
            assert (result.returncode, result.stderr) == (0, "")
    assert not (state_of(env) / "fallback.jsonl").exists()
    code, out, err = show(env, "--ticket", "RUN-5", "--offline")
    assert code == 0, err
    assert [r["name"] for r in rows(out)] == ["run RUN-5", "  Implement", "  claude aaaaaaaa"]
    kinds = {(e[0], e[2]) for e in reconcile(out)}
    assert {("1000000000000005", "error"), ("1000000000000004", "block"), ("1000000000000002", "retry")} <= kinds
    assert "user@example.com" not in out
