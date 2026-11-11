"""Black-box tests for `agent-trace show`, the joined timeline of a ticket or sessions.

Each test writes stored records (the flat shape that collect and the fallback file use) to a temporary
AGENT_TRACE_DIR, runs the real tool with TZ=UTC, and parses its text output. The default output is the gaps
view; the bar-chart tests run `show --gantt`, which prints the old chart.

The main scenario, all on 2026-10-30 (UTC), ticket RUN-1, Claude session S1:
  09:00-09:20  interaction 1; 09:05 a Bash `false` tool fails; 09:06 the same tool runs again (a retry)
  09:20-11:40  no activity (2h20m: one idle column, and one reconcile gap)
  11:40-12:00  interaction 2; 11:41:30 an LLM request retry; 11:45-11:50 a rejected permission prompt
Agent spans: Implement 09:01-11:55 ok; Review 09:10-09:15 error; Review again 11:43-11:44 ok (a retry);
Wait for CI (kind wait) 11:51-11:54 parked; Deploy from 11:56, never ended (open).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from datetime import datetime
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


def gantt(env: dict[str, str], *args: str) -> tuple[int, str, str]:
    return show(env, *args, "--gantt")


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
    code, out, err = gantt(env, "--work", "RUN-1", "--offline")
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
    assert "spans 3h00m · active 32m · wait on Marcus 8m · errors 2 · retries 3 · open spans 1" in out.splitlines()


def test_idle_gap_is_one_column_in_every_row_and_labelled(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = gantt(env, "--work", "RUN-1", "--offline")
    bars = [r["bar"] for r in rows(out)]
    columns = {i for bar in bars for i, ch in enumerate(bar) if ch == "┆"}
    assert len(columns) == 1
    assert all(bar[next(iter(columns))] == "┆" for bar in bars)
    assert len(bars[0]) == 60
    text = "\n".join(fence(out))
    assert "┆ 2h20m idle" in text
    assert "09:00Z" in text and "12:00Z" in text


def test_error_retry_and_wait_markers(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = gantt(env, "--work", "RUN-1", "--offline")
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
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    entries = reconcile(out)
    # Native Bash spans name the program only, so the 09:06 `false` cannot prove that it recovered the 09:05 fail.
    # Retries are not a gap kind.
    assert [(e[0], e[1], e[2]) for e in entries] == [
        ("a000000000000003", "09:05Z", "fail"),
        ("gap-a000000000000010", "09:20Z", "idle"),
        ("a000000000000012", "11:45Z", "block"),
    ]
    assert entries[0][3] == "Bash false ShellError"
    assert entries[2][3] == "Bash git decision=reject"
    assert "agent-trace note friction" in out
    assert "agent-trace note none --ref" in out


def test_note_none_answers_its_ref(env: dict[str, str]) -> None:
    refs = ["a000000000000003", "a000000000000012"]
    write_store(state_of(env), scenario(), fallback=[note("none", at(12, 30), refs)])
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    refs = [e[0] for e in reconcile(out)]
    assert refs == ["gap-a000000000000010"]
    # A gap that `note none` answers is no gap: it leaves GAPS too.
    assert not any(line.startswith("  block") for line in section(out, "GAPS (cost = wait time)"))


def test_nearby_friction_note_answers_anomalies_in_its_window(env: dict[str, str]) -> None:
    friction = note(
        "friction",
        at(11, 52),  # inside the window of the 11:45-11:50 block, after the window of the idle gap
        [],
        **{"agent_trace.category": "permission", "agent_trace.what": "git was rejected", "agent_trace.fix": "allow it"},
    )
    write_store(state_of(env), [*scenario(), friction])
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    refs = [e[0] for e in reconcile(out)]
    assert refs == ["a000000000000003", "gap-a000000000000010"]
    # The friction takes the block that it answers: its count and its 5-minute wait.
    gaps = section(out, "GAPS (cost = wait time)")
    assert "friction 1×  5m  permission: git was rejected → allow it" in gaps
    assert not any(line.startswith("block") for line in gaps)


def test_all_answered_prints_reconcile_none(env: dict[str, str]) -> None:
    refs = ["a000000000000003", "gap-a000000000000010", "a000000000000012"]
    write_store(state_of(env), [*scenario(), note("none", at(12, 1), refs)])
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    assert "Reconcile: none" in out.splitlines()
    assert fence(out)[0].startswith("RUN-1  ")


def test_parks_and_identity_never_printed(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    assert "  wait-ci  waiting on CI" in out.splitlines()
    for secret in IDENTITY.values():
        assert secret not in out
    assert fence(out)[0].startswith("RUN-1  ")


def test_prs_with_github_state_and_head_moved(env: dict[str, str], isolated_env: IsolatedEnv, fake_exe: Any) -> None:
    fake_exe(
        "gh",
        f"""printf '%s\\n' "$*" >>"$HOME/gh.log"
printf '%s' '{{"state":"MERGED","headRefOid":"{MOVED}","mergeCommit":{{"oid":"{MERGE}"}}}}'
""",
    )
    write_store(state_of(env), [*scenario(), pr("create", at(9, 30)), pr("merge", at(11, 58))])
    _, out, _ = show(env, "--work", "RUN-1")
    [line] = [line for line in out.splitlines() if PR_URL in line]
    assert fence(out)[0].endswith("PRs 1 (merged 1)")
    assert "create, merge" in line
    assert "head 0123456" in line
    assert "merge abcdef0" in line
    assert "head moved" in line
    assert (isolated_env.home / "gh.log").read_text().split() == [
        "pr",
        "view",
        PR_URL,
        "--json",
        "state,headRefOid,mergeCommit,mergedAt,commits",
    ]


def test_prs_offline_skips_github_and_gh_failure_is_reported(
    env: dict[str, str], isolated_env: IsolatedEnv, fake_exe: Any
) -> None:
    fake_exe("gh", 'printf x >>"$HOME/gh.log"\nexit 1\n')
    write_store(state_of(env), [*scenario(), pr("merge", at(11, 58))])
    _, offline, _ = show(env, "--work", "RUN-1", "--offline")
    [line] = [line for line in offline.splitlines() if PR_URL in line]
    assert "merge" in line
    assert not (isolated_env.home / "gh.log").exists()
    _, online, _ = show(env, "--work", "RUN-1")
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
    code, out, err = gantt(env, "--session", S2, "--offline")
    assert code == 0, err
    got = [(r["name"], r["dur"]) for r in rows(out)]
    assert got == [("run bbbbbbbb", "10m"), ("  codex bbbbbbbb", "10m")]
    assert "✗" in rows(out)[1]["bar"]
    assert "errors 1" in out
    code, out, err = show(env, "--session", S2, "--offline")
    assert code == 0, err
    assert [e[:3] for e in reconcile(out)] == [["b000000000000003", "09:05Z", "fail"]]
    assert "user@example.com" not in out


# Protects: the per-session transcript view moved behind --timeline, and the default output no longer dumps it.
# Bug caught: the default output prints the transcript timeline (TURN rows and full error text) again, or
# --timeline loses it.
def test_timeline_flag_prints_the_transcript_view_and_the_default_does_not(env: dict[str, str], tmp_path: Path) -> None:
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
    penv = {**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}
    code, out, err = show(penv, "--work", "RUN-2", "--offline", "--timeline")
    assert code == 0, err
    lines = out.splitlines()
    assert f"Transcript timeline for {session}:" in lines
    assert any(line.startswith(f"session {session}") for line in lines)
    assert any("  TURN  " in line for line in lines)
    code, out, err = show(penv, "--work", "RUN-2", "--offline")
    assert code == 0, err
    lines = out.splitlines()
    assert fence(out)[0].startswith("RUN-2  ")
    assert f"Transcript timeline for {session}:" not in lines
    assert not any("  TURN  " in line or line.startswith(f"session {session}") for line in lines)
    code, out, err = gantt(penv, "--work", "RUN-2", "--offline")
    assert code == 0, err
    assert [(r["name"], r["status"]) for r in rows(out)] == [("run RUN-2", ""), ("  Implement", "ok")]


FB = "dddddddd-0000-4000-8000-000000000004"
FB_REFS = [
    "tx-dddddddd-fail-080006",
    "tx-dddddddd-block-080021",
    "tx-dddddddd-gap-080021",
    "tx-dddddddd-idle-084540",
    "tx-dddddddd-block-084611",
    "tx-dddddddd-block-084614",
]
AGENT_TRACE_BLOCK = (
    "PreToolUse:Bash hook error: [python3 /Users/x/dotfiles/tools/agent-trace/bin/agent-trace gate]: "
    "agent-trace gate: this /neo session has no work ID."
)
GUARD = (
    "PreToolUse:Bash hook error: [python3 /Users/x/dotfiles/config/agent-hooks/guard_irreversible.py]: "
    "Blocked by the guard_irreversible hook: spacectl stack confirm is irreversible."
)


def fallback_transcript(projects: Path) -> None:
    """A Claude Code transcript for session FB on 2026-10-29 (UTC). The store has no native spans for it.

    08:00:06 and 08:00:10: one cause fails twice (one repeated group). 08:00:13: a soft fail (an error line in the
    output of a read that succeeded). 08:00:16: a failed agent-trace call. 08:00:21: a permission denial. Then 30
    minutes with no event (idle). 08:30:25 to 08:45:30: one tool call runs 15 minutes (activity, not idle).
    08:45:40 to 08:45:50: the same call three times in a row (polling, an idle gap). 08:46:01: a failed read. 08:46:04:
    a fail that the next call of the same program recovers (08:46:07). 08:46:11: a hook block. 08:46:14: a hook
    block of an agent-trace call (a block, although failed agent-trace calls are not gaps).
    """

    def use(ident: str, when: str, command: str, text: str = "") -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        content.append({"type": "tool_use", "id": ident, "name": "Bash", "input": {"command": command}})
        return {
            "type": "assistant",
            "timestamp": when,
            "sessionId": FB,
            "message": {"role": "assistant", "content": content},
        }

    def result(ident: str, when: str, text: str, error: bool) -> dict[str, Any]:
        block = {"type": "tool_result", "tool_use_id": ident, "is_error": error, "content": text}
        return {"type": "user", "timestamp": when, "sessionId": FB, "message": {"role": "user", "content": [block]}}

    def said(role: str, when: str, text: str) -> dict[str, Any]:
        return {"type": role, "timestamp": when, "sessionId": FB, "message": {"role": role, "content": text}}

    lines = [
        said("user", "2026-10-29T08:00:00Z", "go"),
        use("t1", "2026-10-29T08:00:04Z", "gh pr view 7"),
        result("t1", "2026-10-29T08:00:06Z", "Exit code 1\n\nHTTP 404: not found (repos/x/pulls/7)", True),
        use("t2", "2026-10-29T08:00:08Z", "gh pr view 8"),
        result("t2", "2026-10-29T08:00:10Z", "Exit code 1\n\nHTTP 404: not found (repos/x/pulls/8)", True),
        use("t3", "2026-10-29T08:00:12Z", "cat notes.md"),
        result("t3", "2026-10-29T08:00:13Z", "error: this line is only text in the file", False),
        use("t4", "2026-10-29T08:00:15Z", "agent-trace show --work RUN-3"),
        result("t4", "2026-10-29T08:00:16Z", "Exit code 1\nagent-trace: no spans for work ID RUN-3", True),
        use("t5", "2026-10-29T08:00:20Z", "kubectl create job x"),
        result(
            "t5", "2026-10-29T08:00:21Z", "Permission for this action was denied by the auto mode classifier.", True
        ),
        # The agent resumes by itself: nothing names why it waited, so the gap stays unexplained.
        said("assistant", "2026-10-29T08:30:21Z", "Resuming."),
        # Text longer than the timeline's 160-character quote comes before the call, so the quote drops it.
        use("t6", "2026-10-29T08:30:25Z", "pytest -q", text="Running the full test suite now. " * 8),
        result("t6", "2026-10-29T08:45:30Z", "1 passed", False),
        use("t7", "2026-10-29T08:45:40Z", "gh run view 1"),
        result("t7", "2026-10-29T08:45:41Z", "in_progress", False),
        use("t8", "2026-10-29T08:45:45Z", "gh run view 1"),
        result("t8", "2026-10-29T08:45:46Z", "in_progress", False),
        use("t9", "2026-10-29T08:45:50Z", "gh run view 1"),
        result("t9", "2026-10-29T08:45:51Z", "completed", False),
        use("t10", "2026-10-29T08:46:00Z", "cat missing.md"),
        result("t10", "2026-10-29T08:46:01Z", "Exit code 1\ncat: missing.md: No such file or directory", True),
        use("t11", "2026-10-29T08:46:03Z", "python3 -m pytest"),
        result("t11", "2026-10-29T08:46:04Z", "Exit code 1\nFAILED tests/x.py", True),
        use("t12", "2026-10-29T08:46:06Z", "python3 -m pytest"),
        result("t12", "2026-10-29T08:46:07Z", "1 passed", False),
        use("t13", "2026-10-29T08:46:10Z", "spacectl stack confirm"),
        result("t13", "2026-10-29T08:46:11Z", GUARD, True),
        use("t14", "2026-10-29T08:46:13Z", "agent-trace note none --ref x"),
        result("t14", "2026-10-29T08:46:14Z", AGENT_TRACE_BLOCK, True),
        said("assistant", "2026-10-29T08:46:20Z", "done"),
    ]
    folder = projects / "-Users-x-repo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{FB}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def fallback_store(env: dict[str, str], *extra: dict[str, Any]) -> None:
    kind = {"agent_trace.kind": "phase"}
    start = agent("impl", "start", at(9, 0), ticket="RUN-3", session=FB, name="Implement", **kind)
    end = agent("impl", "end", at(9, 30), ticket="RUN-3", session=FB, **{"agent_trace.status": "ok"})
    write_store(state_of(env), [start, end, *extra])


def fallback_note(kind: str, refs: list[str]) -> dict[str, Any]:
    record = note(kind, at(10, 0), refs)
    record["attrs"].update({"run.ticket": "RUN-3", "agent_trace.scope": "RUN-3", "session.id": FB})
    return record


def test_fallback_transcript_anomalies_reach_reconcile(env: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    fallback_transcript(projects)
    fallback_store(env)
    code, out, err = show({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--work", "RUN-3", "--offline")
    assert code == 0, err
    assert "Reconcile: none" not in out.splitlines()
    entries = reconcile(out)
    assert [e[0] for e in entries] == FB_REFS
    assert [e[1:3] for e in entries] == [
        ["08:00Z", "fail"],
        ["08:00Z", "block"],
        ["08:00Z", "idle"],
        ["08:45Z", "idle"],
        ["08:46Z", "block"],
        ["08:46Z", "block"],
    ]
    # The tool and the program only, plus what blocked the call: no more command text, as for native spans.
    assert [e[3] for e in entries] == [
        "Bash gh x2",
        "Bash kubectl (auto mode)",
        "30m idle",
        "Bash gh x3 (polling)",
        "Bash spacectl (hook guard_irreversible)",
        "Bash agent-trace (hook agent-trace gate)",
    ]
    # The 15-minute tool call (08:30:25 to 08:45:30) is activity, so it is not an idle gap.
    # The soft fail, the failed read, the failed agent-trace call, and the recovered fail are not anomalies.
    assert not any(word in e[3] for e in entries if e[2] == "fail" for word in ("cat", "agent-trace", "python3"))


def test_fallback_anomalies_need_answers_before_reconcile_none(env: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    fallback_transcript(projects)
    penv = {**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}
    fallback_store(env, fallback_note("none", FB_REFS[:2]))
    _, out, _ = show(penv, "--work", "RUN-3", "--offline")
    assert [e[0] for e in reconcile(out)] == FB_REFS[2:]
    fallback_store(env, fallback_note("none", FB_REFS))
    _, out, _ = show(penv, "--work", "RUN-3", "--offline")
    assert "Reconcile: none" in out.splitlines()


def test_fallback_gap_inside_a_wait_span_is_not_an_anomaly(env: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    fallback_transcript(projects)
    day_before = T0 - 25 * 60 * M  # 2026-10-29T08:00:00Z
    kind = {"agent_trace.kind": "wait"}
    wait_start = agent("ci", "start", day_before + 60 * S, ticket="RUN-3", session=FB, name="Wait for CI", **kind)
    wait_end = agent("ci", "end", day_before + 29 * M, ticket="RUN-3", session=FB, **{"agent_trace.status": "ok"})
    fallback_store(env, wait_start, wait_end)
    _, out, _ = show({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--work", "RUN-3", "--offline")
    assert [e[0] for e in reconcile(out)] == [FB_REFS[0], FB_REFS[1], *FB_REFS[3:]]  # The idle gap is a wait.


def claude_transcript(projects: Path, session: str, *stamps: str) -> None:
    """A Claude Code transcript with one event at each ISO time, plus a line with no time."""
    folder = projects / "-Users-x-repo"
    folder.mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, str]] = [{"type": "summary", "summary": "no timestamp on this line"}]
    lines += [{"type": "user", "timestamp": stamp, "sessionId": session} for stamp in stamps]
    (folder / f"{session}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def section(output: str, title: str) -> list[str]:
    """The lines under a title line, stripped, up to the first line that is not indented."""
    lines = output.splitlines()
    start = lines.index(title)
    out = []
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        out.append(line.strip())
    return out


def test_wall_time_comes_from_the_transcripts_of_every_bound_session(env: dict[str, str], tmp_path: Path) -> None:
    # Bug (/matrix run retro, 2026-11-05): spans stopped after context compactions and one worker session had
    # none, so `show` printed a 2h46m run that really ran from 01:24Z to 01:44Z the next day. The chart went
    # into the Linear close comment as the whole run.
    write_store(state_of(env), scenario())
    sessions = state_of(env) / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{S2}.ticket").write_text("RUN-1\n")
    projects = tmp_path / "projects"
    claude_transcript(projects, S1, "2026-10-30T08:50:00.000Z", "2026-10-30T12:30:00Z", "2026-10-31T09:10:00.000Z")
    claude_transcript(projects, S2, "2026-10-30T10:00:00Z", "2026-10-30T10:30:00.000Z")
    code, out, err = show({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--work", "RUN-1", "--offline")
    assert code == 0, err

    summary = fence(out)
    # S1 spans run 09:00-12:00 (3h00m) of the 24h20m wall time: 180 / 1460 minutes is 12%.
    assert "wall 24h20m (10-30 08:50Z → 10-31 09:10Z) · span coverage 3h00m (12%)" in summary
    assert summary[0].startswith("RUN-1  10-30 08:50Z → 10-31 09:10Z (24h20m)  sessions 2")
    assert section(out, "SESSIONS") == [
        "claude aaaaaaaa  transcript 10-30 08:50Z → 10-31 09:10Z (24h20m)  spans 10-30 09:00Z → 10-30 12:00Z (3h00m)",
        "claude bbbbbbbb  transcript 10-30 10:00Z → 10-30 10:30Z (30m)  no spans",
    ]
    _, chart, _ = gantt({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--work", "RUN-1", "--offline")
    assert "wall 24h20m (10-30 08:50Z → 10-31 09:10Z) · span coverage 3h00m (12%)" in fence(chart)
    assert any(line.startswith("spans 3h00m · active 32m") for line in fence(chart))


def test_a_session_bound_to_a_later_work_id_does_not_leak_earlier_agent_spans(env: dict[str, str]) -> None:
    # Bug: bound sessions were passed as explicit selectors, so one session that served RUN-1 and then RUN-2
    # put the spans of both work IDs into the RUN-2 timeline.
    records = [
        agent("old", "start", at(9, 0), ticket="RUN-1", name="Old work", **{"agent_trace.kind": "phase"}),
        agent("old", "end", at(9, 10), ticket="RUN-1", **{"agent_trace.status": "ok"}),
        agent("new", "start", at(9, 20), ticket="RUN-2", name="New work", **{"agent_trace.kind": "phase"}),
        agent("new", "end", at(9, 30), ticket="RUN-2", **{"agent_trace.status": "ok"}),
    ]
    write_store(state_of(env), records)
    (state_of(env) / "sessions").mkdir(parents=True)
    (state_of(env) / "sessions" / f"{S1}.ticket").write_text("RUN-2\n")
    code, out, err = gantt(env, "--work", "RUN-2", "--offline")
    assert code == 0, err
    assert [r["name"] for r in rows(out)] == ["run RUN-2", "  New work"]


def test_wall_time_is_unknown_without_transcripts(env: dict[str, str]) -> None:
    # Bug a careless fix makes: falling back to the span window would print it as the wall time again.
    write_store(state_of(env), scenario())
    code, out, err = show(env, "--work", "RUN-1", "--offline")
    assert code == 0, err
    assert "wall unknown (no transcript found for 1 of 1 sessions)" in fence(out)
    assert section(out, "SESSIONS") == ["claude aaaaaaaa  no transcript  spans 10-30 09:00Z → 10-30 12:00Z (3h00m)"]


def test_jaeger_gets_one_joined_trace_without_identity(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    with recorder(collect_header=False) as jaeger:
        code, out, err = show(env, "--work", "RUN-1", "--offline", "--jaeger", jaeger.url)
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


# Protects: `show` selects a run by `--work`, and no longer accepts the old `--ticket` flag.
# Bug caught: the rename leaves `show` without `--work`, or keeps the retired alias alive.
def test_work_flag_selects_the_run_and_ticket_is_retired(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    code, by_work, err = show(env, "--work", "RUN-1", "--offline")
    old_code, old_out, old_err = show(env, "--ticket", "RUN-1", "--offline")
    assert code == 0, err
    assert fence(by_work)[0].startswith("RUN-1  ")
    assert old_code == 2
    assert "unrecognized arguments: --ticket" in old_err
    assert old_out == ""


def test_nothing_matched_exits_1(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    code, out, err = show(env, "--work", "NOPE-9")
    assert code == 1
    assert err.strip() == "agent-trace: no spans for work ID NOPE-9"
    assert out == ""


def test_needs_a_ticket_or_session(env: dict[str, str]) -> None:
    code, _, err = show(env)
    assert code == 2
    assert "--work or --session" in err


def test_narrow_width_moves_the_idle_label_to_a_footnote(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    _, out, _ = gantt(env, "--work", "RUN-1", "--offline", "--width", "20")
    assert {len(r["bar"]) for r in rows(out)} == {20}
    assert "┆ = 2h20m idle (09:20Z–11:40Z)" in fence(out)


def test_collected_native_spans_join_emitted_agent_spans(env: dict[str, str]) -> None:
    session = "aaaaaaaa-0000-4000-8000-000000000001"  # the session id in claude_traces.json
    emit_env = {**env, "CLAUDE_CODE_SESSION_ID": session}
    with collect(env) as port:
        emit_env["AGENT_TRACE_ENDPOINT"] = f"http://127.0.0.1:{port}"
        assert post(port, "/v1/traces", (FIXTURES / "claude_traces.json").read_bytes()) == 200
        for args in (
            ["span", "start", "--id", "impl", "--name", "Implement", "--kind", "phase", "--work", "RUN-5"],
            ["span", "end", "--id", "impl", "--status", "ok"],
        ):
            result = run(args, emit_env)
            assert (result.returncode, result.stderr) == (0, "")
    assert not (state_of(env) / "fallback.jsonl").exists()
    code, out, err = gantt(env, "--work", "RUN-5", "--offline")
    assert code == 0, err
    assert [r["name"] for r in rows(out)] == ["run RUN-5", "  Implement", "  claude aaaaaaaa"]
    code, out, err = show(env, "--work", "RUN-5", "--offline")
    assert code == 0, err
    kinds = {(e[0], e[2]) for e in reconcile(out)}
    assert {("1000000000000005", "fail"), ("1000000000000004", "block")} <= kinds
    assert "user@example.com" not in out


# Protects G1: the default output is a short gaps view in UTC, with no TURN rows and no transcript dump.
# Bug caught: one real run printed 580 lines (291 TURN rows, the transcript text of every session without native spans,
# local clock times beside UTC refs), so the agent used 15 of them. A local TZ must not change any time.
def test_default_output_is_short_gaps_first_and_utc(env: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    fallback_transcript(projects)
    many = []
    for n in range(40):
        kind = {"agent_trace.kind": "phase"}
        many.append(agent(f"p{n}", "start", at(9, n), ticket="RUN-3", session=FB, name=f"Phase {n}", **kind))
        many.append(agent(f"p{n}", "end", at(9, n + 1), ticket="RUN-3", session=FB, **{"agent_trace.status": "ok"}))
    for n in range(30):
        text = {"agent_trace.category": "doc", "agent_trace.what": f"thing {n}", "agent_trace.fix": f"fix {n}"}
        record = note("friction", at(10, n), [], **text)
        record["attrs"].update({"run.ticket": "RUN-3", "agent_trace.scope": "RUN-3", "session.id": FB})
        many.append(record)
    fallback_store(env, *many)
    sessions = state_of(env) / "sessions"
    sessions.mkdir(parents=True)
    for n in range(12):
        (sessions / f"eeeeeeee-0000-4000-8000-{n:012d}.ticket").write_text("RUN-3\n")
    local = {**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects), "TZ": "America/Los_Angeles"}
    code, out, err = show(local, "--work", "RUN-3", "--offline")
    assert code == 0, err
    lines = out.splitlines()
    assert lines.index("Reconcile:") <= 60, "\n".join(lines[:80])
    assert fence(out)[0].startswith("RUN-3  10-29 08:00Z → ")
    assert "GAPS (cost = wait time)" in lines
    assert any(line.startswith("  … ") and "more" in line for line in fence(out))
    # The chart is in the fence, but only its first rows: the rest are behind --gantt.
    chart = rows(out)
    assert chart[0]["name"] == "run RUN-3" and len(chart) <= 16
    assert any(line.startswith("… ") and "--gantt" in line for line in fence(out))
    assert not any("TURN" in line or "Transcript timeline" in line or line.startswith("session ") for line in lines)
    times = re.findall(r"\b\d\d:\d\d\b(?!Z)", "\n".join(lines))
    assert times == [], times
    assert [e[1] for e in reconcile(out)][:1] == ["08:00Z"]


def g2_records() -> list[dict[str, Any]]:
    """Native spans of one interaction (09:00-09:30) with six failing Bash calls and two that succeed."""
    records = [native("c000000000000001", "claude_code.interaction", at(9, 0), at(9, 30), None)]
    calls = [
        ("agent-trace", False),  # a failed agent-trace call: never an error
        ("cat", False),  # a failed read: never a gap
        ("python3", False),  # a native Bash span names no subcommand, so a later python3 call proves nothing
        ("python3", True),
        ("make", False),  # never recovered
        ("gh", False),  # gh fails twice with a success between: the same program failing twice is a gap
        ("gh", True),
        ("gh", False),
    ]
    for n, (argv0, ok) in enumerate(calls, start=1):
        tool, execution = f"c0000000000001{n:02d}", f"c0000000000002{n:02d}"
        bash = {"tool_name": "Bash", "bash_argv0": argv0}
        records.append(native(tool, "claude_code.tool", at(9, n), at(9, n, 5), "c000000000000001", **bash))
        status = {"code": 0, "message": ""} if ok else {"code": 2, "message": "ShellError"}
        records.append(
            native(execution, "claude_code.tool.execution", at(9, n), at(9, n, 5), tool, success=ok, status=status)
        )
    records += [
        agent("impl", "start", at(9, 0), name="Implement", **{"agent_trace.kind": "phase"}),
        agent("impl", "end", at(9, 30), **{"agent_trace.status": "ok"}),
    ]
    return records


# Protects G2 for native spans: failed agent-trace calls and failed reads never count as errors, and a native
# Bash fail is always a gap, because its span names the program but not the subcommand.
# Bug caught: every native tool error became a Reconcile item, including the agent-trace calls of the agent.
def test_native_soft_fails_are_not_errors_and_recovered_fails_are_not_gaps(env: dict[str, str]) -> None:
    write_store(state_of(env), g2_records())
    code, out, err = show(env, "--work", "RUN-1", "--offline")
    assert code == 0, err
    entries = reconcile(out)
    assert [(e[0], e[2], e[3]) for e in entries] == [
        ("c000000000000203", "fail", "Bash python3 ShellError"),
        ("c000000000000205", "fail", "Bash make ShellError"),
        ("c000000000000206", "fail", "Bash gh ShellError"),
        ("c000000000000208", "fail", "Bash gh ShellError"),
    ]
    assert "autonomy  blocks 0  fails 4  unexplained idle 0s  friction 0" in fence(out)
    gaps = section(out, "GAPS (cost = wait time)")
    assert "fail     2×  –  Bash gh ShellError" in gaps
    assert "fail     1×  –  Bash make ShellError" in gaps
    _, chart, _ = gantt(env, "--work", "RUN-1", "--offline")
    # The chart marks the python3, make, and gh fails, but never the agent-trace call or the read.
    assert any(line.startswith("spans 30m") and "errors 4" in line for line in fence(chart))


# Protects the GAPS costs: idle gaps of parallel sessions count once, and a friction note takes only the gaps of
# its own session.
# Bug caught: one real run showed 26h33m of unexplained idle in a 17h48m run, because the idle time of three sessions
# was added up; and a note of one session hid an idle gap of another session from GAPS but not from Reconcile.
def test_gap_costs_count_parallel_idle_once_and_notes_take_only_their_own_session(
    env: dict[str, str], tmp_path: Path
) -> None:
    projects = tmp_path / "projects"
    fallback_transcript(projects)
    twin = "ffffffff-0000-4000-8000-000000000006"
    folder = projects / "-Users-x-repo"
    (folder / f"{twin}.jsonl").write_text((folder / f"{FB}.jsonl").read_text().replace(FB, twin))
    fallback_store(env)
    (state_of(env) / "sessions").mkdir(parents=True)
    (state_of(env) / "sessions" / f"{twin}.ticket").write_text("RUN-3\n")
    penv = {**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}
    _, out, _ = show(penv, "--work", "RUN-3", "--offline")
    assert "autonomy  blocks 6  fails 4  unexplained idle 30m  friction 0" in fence(out)
    gaps = section(out, "GAPS (cost = wait time)")
    assert "idle     2×  30m  unexplained" in gaps
    assert "idle     2×  10s  Bash gh (polling)" in gaps

    text = {"agent_trace.category": "doc", "agent_trace.what": "slow", "agent_trace.fix": "go faster"}
    friction = note("friction", at(9, 0) - 25 * 60 * M + 2 * M, [], **text)  # 2026-10-29T08:02Z, in session FB
    friction["attrs"].update({"run.ticket": "RUN-3", "agent_trace.scope": "RUN-3", "session.id": FB})
    fallback_store(env, friction)
    _, out, _ = show(penv, "--work", "RUN-3", "--offline")
    gaps = section(out, "GAPS (cost = wait time)")
    assert "friction 1×  30m  doc: slow → go faster" in gaps
    assert "idle     1×  30m  unexplained" in gaps
    assert "tx-ffffffff-gap-080021" in [e[0] for e in reconcile(out)]


def native_tool(n: int, interaction: str, name: str, when: int, result: str) -> list[dict[str, Any]]:
    """One native tool call: result is "ok", "fail", or "rejected" (a permission prompt, then no execution)."""
    tool = f"d0000000000001{n:02d}"
    out = [native(tool, "claude_code.tool", when, when + 30 * S, interaction, tool_name=name)]
    if result == "rejected":
        out.append(
            native(
                f"d0000000000003{n:02d}",
                "claude_code.tool.blocked_on_user",
                when,
                when + 20 * S,
                tool,
                decision="reject",
            )
        )
        return out
    status = {"code": 0, "message": ""} if result == "ok" else {"code": 2, "message": "ToolError"}
    execution = native(
        f"d0000000000002{n:02d}",
        "claude_code.tool.execution",
        when,
        when + 30 * S,
        tool,
        success=result == "ok",
        status=status,
    )
    return [*out, execution]


# Protects native recovery: only a later call of the same tool that ran and succeeded recovers a fail, and a tool
# that failed twice in the session is a gap even when each fail was recovered.
# Bugs caught: a rejected call counted as a success and hid the fail before it; the failed-twice count looked at
# one turn only, so the same fail in every turn never reached Reconcile.
def test_native_recovery_needs_a_real_success_and_two_fails_are_a_gap(env: dict[str, str]) -> None:
    one, two = "d000000000000001", "d000000000000002"
    records = [
        native(one, "claude_code.interaction", at(9, 0), at(9, 20), None),
        native(two, "claude_code.interaction", at(9, 25), at(9, 40), None),
        *native_tool(1, one, "Edit", at(9, 1), "fail"),
        *native_tool(2, one, "Edit", at(9, 2), "ok"),
        *native_tool(3, one, "Write", at(9, 3), "fail"),
        *native_tool(4, one, "Write", at(9, 4), "rejected"),
        *native_tool(5, one, "NotebookEdit", at(9, 5), "fail"),
        *native_tool(6, one, "NotebookEdit", at(9, 6), "ok"),
        *native_tool(7, two, "Edit", at(9, 26), "fail"),
        *native_tool(8, two, "Edit", at(9, 27), "ok"),
        agent("impl", "start", at(9, 0), name="Implement", **{"agent_trace.kind": "phase"}),
    ]
    write_store(state_of(env), records)
    code, out, err = show(env, "--work", "RUN-1", "--offline")
    assert code == 0, err
    assert [(e[0], e[2]) for e in reconcile(out)] == [
        ("d000000000000201", "fail"),
        ("d000000000000203", "fail"),
        ("d000000000000304", "block"),
        ("d000000000000207", "fail"),
    ]


# Protects D7: the default output, and so the run log that Close posts, carries the span chart again, with UTC axis
# labels, above SESSIONS. `--gantt` still prints the whole chart alone.
# Bug caught: the chart is only behind --gantt, so the Linear run log loses the picture of the run; or its axis
# shows local clock times beside the UTC times of the rest of the output.
def test_default_output_carries_the_chart_in_utc(env: dict[str, str]) -> None:
    write_store(state_of(env), scenario())
    local = {**env, "TZ": "America/Los_Angeles"}
    code, out, err = show(local, "--work", "RUN-1", "--offline")
    assert code == 0, err
    _, chart, _ = gantt(local, "--work", "RUN-1", "--offline")
    assert [(r["name"], r["dur"], r["status"]) for r in rows(out)] == [
        (r["name"], r["dur"], r["status"]) for r in rows(chart)
    ]
    lines = fence(out)
    axis = next(line for line in lines if "09:00Z" in line)
    assert "12:00Z" in axis
    assert lines.index(axis) < lines.index("SESSIONS")
    assert "Reconcile:" in out.splitlines()


CA = "cccccccc-0000-4000-8000-000000000007"


def ns(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()) * S


def causes_transcript(projects: Path) -> None:
    """A transcript of session CA on 2026-10-29 (UTC) with a 20-minute gap after each assistant message.

    Each gap ends on another kind of event: a background task, a peer message, a linked-sessions reminder, a message
    that Marcus typed, a compaction summary, and the agent itself (no cause). Two gaps follow an ask in words.
    """

    def said(role: str, when: str, text: str) -> dict[str, Any]:
        return {"type": role, "timestamp": when, "sessionId": CA, "message": {"role": role, "content": text}}

    lines = [
        said("user", "2026-10-29T10:00:00Z", "<system-reminder> Linked sessions now: ch2 = local_ab-1 (working)"),
        said("assistant", "2026-10-29T10:00:05Z", "Waiting for CI."),
        said("user", "2026-10-29T10:20:05Z", "<task-notification><summary>CI done</summary></task-notification>"),
        said("assistant", "2026-10-29T10:20:10Z", "CI passed. The PR stays parked for you to queue."),
        said("user", "2026-10-29T10:40:10Z", "<task-notification><summary>watcher</summary></task-notification>"),
        said("assistant", "2026-10-29T10:40:15Z", "I sent my report."),
        said(
            "user",
            "2026-10-29T11:00:15Z",
            '<cross-session-message from="r" from-name="Matrix R">ok</cross-session-message>',
        ),
        said("assistant", "2026-10-29T11:00:20Z", "Noted."),
        said("user", "2026-10-29T11:20:20Z", "<system-reminder> Linked sessions now: ch2 = local_ab-1 (done, PR #7)"),
        said("assistant", "2026-10-29T11:20:25Z", "Shall I drop the old branch? Marcus decides the scope."),
        said("user", "2026-10-29T11:40:25Z", "yes, drop it"),
        said("assistant", "2026-10-29T11:40:30Z", "Dropped."),
        said("user", "2026-10-29T12:00:30Z", "This session is being continued from a previous conversation."),
        said("assistant", "2026-10-29T12:00:35Z", "Back."),
        said("assistant", "2026-10-29T12:20:35Z", "Resuming."),
        said("assistant", "2026-10-29T12:25:35Z", "Parked."),
        said("assistant", "2026-10-29T12:50:40Z", "Merged, verifying."),
        said("user", "2026-10-29T13:10:40Z", "looks good"),
    ]
    folder = projects / "-Users-x-repo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{CA}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def causes_store(env: dict[str, str], *extra: dict[str, Any]) -> None:
    """Spans of RUN-4 for session CA: PR 1 created at 12:00 and parked at 12:25 on commit abc1234."""
    where = {"ticket": "RUN-4", "session": CA}
    start = agent("pr1", "start", ns("2026-10-29T12:20:00Z"), name="PR 1", **where, **{"agent_trace.kind": "pr"})
    end = agent(
        "pr1",
        "end",
        ns("2026-10-29T12:25:00Z"),
        **where,
        **{"agent_trace.status": "parked", "agent_trace.note": "parked at abc1234"},
    )
    created = pr("create", ns("2026-10-29T12:00:00Z"))
    created["attrs"].update({"run.ticket": "RUN-4", "agent_trace.scope": "RUN-4", "session.id": CA})
    write_store(state_of(env), [start, end, created, *extra])


# Protects G10: each idle gap gets a cause, cost, and fix target from stored data, so GAPS names why the run waited
# and Reconcile keeps only the gaps that nothing explains.
# Bug caught: every idle gap is one "unexplained" line, so the top GAPS line names no cause; or a cause from words is
# not marked, so Marcus cannot judge it.
def test_idle_gaps_get_a_cause_from_the_event_that_ends_them(env: dict[str, str], tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    causes_transcript(projects)
    causes_store(env)
    code, out, err = show({**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}, "--work", "RUN-4", "--offline")
    assert code == 0, err
    gaps = section(out, "GAPS (cost = wait time)")
    router = "→ matrix: router answers or sets a decision default"
    assert "wait     1×  20m  background task (CI or watcher) → neo: wait span around the watch" in gaps
    assert f'wait     1×  20m  wait on router: merge (by words), matched "parked for you" + "queue" {router}' in gaps
    # The peer and the linked session that ended a gap are named: the sender, or the session whose state changed.
    assert f"wait     1×  20m  wait on router, from Matrix R {router}" in gaps
    assert "wait     1×  20m  wait on another session, from ch2 (done, PR #7) → matrix: router heartbeat" in gaps
    assert (
        'wait     1×  20m  wait on Marcus: scope, matched "Marcus decides" + "decides"'
        " → brief or ticket names the scope"
    ) in gaps
    assert "wait     1×  20m  context compaction → harness" in gaps
    # The gap that the agent ended by itself has no cause. Offline, the gap after the park has no merge time, so
    # it is not guessed: both stay unexplained and in Reconcile, and no wait is. The park holds only the first gap
    # after it: the later gap that Marcus ended still has its cause.
    assert "wait     1×  20m  wait on Marcus: reply → brief or ticket names the default" in gaps
    assert "idle     2×  45m  unexplained" in gaps
    assert [(e[0], e[2]) for e in reconcile(out)] == [
        ("tx-cccccccc-gap-120035", "idle"),
        ("tx-cccccccc-gap-122535", "idle"),
    ]
    assert "autonomy  blocks 0  fails 0  unexplained idle 45m  friction 0" in fence(out)


# Protects rule 2 of G10: the time from a park to the merge of its PR is a wait on merge, by the commit in the park
# note, with the merge time from GitHub or from the hook record of the merge.
# Bug caught: the gap after a park reads as unexplained idle although the PR merged later; or a merge time is guessed.
def test_gap_between_a_park_and_its_merge_is_a_wait_on_merge(
    env: dict[str, str], tmp_path: Path, isolated_env: IsolatedEnv, fake_exe: Any
) -> None:
    projects = tmp_path / "projects"
    causes_transcript(projects)
    causes_store(env)
    penv = {**env, "AGENT_TRACE_CLAUDE_PROJECTS": str(projects)}
    data = {
        "state": "MERGED",
        "headRefOid": "abc1234" + "0" * 33,
        "mergeCommit": {"oid": MERGE},
        "mergedAt": "2026-10-29T12:50:00Z",
        "commits": [{"oid": "0" * 40}, {"oid": "abc1234" + "0" * 33}],
    }
    fake_exe("gh", f"""printf '%s\\n' "$*" >>"$HOME/gh.log"\nprintf '%s' '{json.dumps(data)}'\n""")
    code, out, err = show(penv, "--work", "RUN-4")
    assert code == 0, err
    gaps = section(out, "GAPS (cost = wait time)")
    assert "wait     1×  25m  wait on merge → Marcus merge step" in gaps
    assert [e[0] for e in reconcile(out)] == ["tx-cccccccc-gap-120035"]
    # One gh call for the PR, shared by the PR list and the park lookup.
    assert len((isolated_env.home / "gh.log").read_text().splitlines()) == 1

    # Offline, the hook record of the merge gives the merge time instead.
    merged = pr("merge", ns("2026-10-29T12:50:00Z"), head="abc1234" + "0" * 33)
    merged["attrs"].update({"run.ticket": "RUN-4", "agent_trace.scope": "RUN-4", "session.id": CA})
    causes_store(env, merged)
    _, out, _ = show(penv, "--work", "RUN-4", "--offline")
    assert "wait     1×  25m  wait on merge → Marcus merge step" in section(out, "GAPS (cost = wait time)")
    assert [e[0] for e in reconcile(out)] == ["tx-cccccccc-gap-120035"]


# Protects the ask span: a wait span with --ask is a named wait in GAPS, not idle, and not a Reconcile item.
# Bug caught: the ask span hides the gap but GAPS never shows the wait, so its cost is lost.
def test_ask_span_is_a_wait_on_marcus_with_its_class(env: dict[str, str]) -> None:
    kind = {"agent_trace.kind": "wait", "agent_trace.ask": "merge"}
    start = agent("ask-1", "start", at(10, 0), name="Merge PR 7", **kind)
    end = agent("ask-1", "end", at(10, 45), **{"agent_trace.status": "ok"})
    write_store(state_of(env), [*scenario(), start, end])
    _, out, _ = show(env, "--work", "RUN-1", "--offline")
    assert "wait     1×  45m  wait on Marcus: merge → merge rule: the PR parks for Marcus" in section(
        out, "GAPS (cost = wait time)"
    )
    assert sid("RUN-1", "ask-1") not in [e[0] for e in reconcile(out)]
    assert reconcile(out)


# Protects G10 part (c): every wait cause and ask class has its fix target, from one table.
# Bug caught: a new cause or class prints no "→" target, so its GAPS line names no fix.
@pytest.mark.parametrize(
    ("cause", "target"),
    [
        ("wait on merge", "Marcus merge step"),
        ("wait on Marcus: merge", "merge rule: the PR parks for Marcus"),
        ("wait on Marcus: access (by words)", "intake grants the access"),
        ("wait on Marcus: scope", "brief or ticket names the scope"),
        ("wait on Marcus: info", "brief or ticket names the default"),
        ("wait on Marcus: reply", "brief or ticket names the default"),
        ("wait on router: info (by words)", "matrix: router answers or sets a decision default"),
        ("wait on router", "matrix: router answers or sets a decision default"),
        ("wait on another session", "matrix: router heartbeat"),
        ("background task (CI or watcher)", "neo: wait span around the watch"),
        ("context compaction", "harness"),
    ],
)
def test_each_wait_cause_has_a_fix_target(cause: str, target: str) -> None:
    sys.path.insert(0, str(REPO_ROOT / "tools" / "agent-trace"))
    show_module = importlib.import_module("agent_trace.show")
    assert show_module.fix_target(cause) == target
