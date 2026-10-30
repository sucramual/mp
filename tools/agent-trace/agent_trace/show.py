"""`agent-trace show`: one joined text timeline of a ticket's run, from stored agent and native spans.

Selection. Every spans/*.jsonl file and fallback.jsonl is read. The agent records are the `agent-trace` records
with `run.ticket` == --ticket, plus the `agent-trace` records whose `session.id` is a --session. The sessions are
the --session values plus the session ids of those agent records. Native records are the Claude Code spans of
those sessions, and the Codex spans and logs whose `thread.id` or `conversation.id` is one of them, plus any Codex
record that shares a trace id with such a record.

Model. One root row for the run. One row per agent span: `span start` and `span end` merge by (scope, id); a span
is a child of the agent span that its --parent names, else of the root; a start with no end is `open`. One row per
session that has native spans, drawn from its interaction spans (Codex: turns). Native children only mark the
session row: `✗` error, `↻` retry, `▒` waiting on Marcus. Notes and PR records are listed after the timeline.

Time. Gaps in activity longer than 30 minutes shrink to one `┆` column each. Clock times are local (set TZ).

Sections after the timeline: PRs (with GitHub state unless --offline), Parks, Notes, and Reconcile (anomalies that
no note answers). Prompts, command text, and identity attributes are never printed.

Exit 0 when anything matched, 1 when nothing matched, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_trace import otlp, store

MIN = 60 * 1_000_000_000
IDLE_COLLAPSE = 30 * MIN
GAP_ANOMALY = 10 * MIN
NOTE_BEFORE = 2 * MIN
NOTE_AFTER = 10 * MIN
NAME_LIMIT = 32
IDENTITY_ATTRS = {"user.email", "user.id", "user.account_uuid", "user.account_id", "organization.id"}
SESSION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CODEX_TURNS = {"session_task.turn", "run_turn"}
TIMELINE = Path(__file__).resolve().parents[3] / "skills" / "retro" / "scripts" / "timeline.py"

Interval = tuple[int, int]


# ---------------------------------------------------------------- helpers


def fmt_duration(ns: int) -> str:
    seconds = max(0, round(ns / 1e9))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def clock(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9).strftime("%H:%M")


def union(intervals: list[Interval]) -> list[Interval]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def measure(intervals: list[Interval]) -> int:
    return sum(end - start for start, end in union(intervals))


def subtract(intervals: list[Interval], minus: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    cuts = union(minus)
    for start, end in union(intervals):
        cursor = start
        for cut_start, cut_end in cuts:
            if cut_end <= cursor or cut_start >= end:
                continue
            if cut_start > cursor:
                out.append((cursor, cut_start))
            cursor = max(cursor, cut_end)
        if cursor < end:
            out.append((cursor, end))
    return out


def falsy(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def is_agent(record: dict[str, Any]) -> bool:
    return record.get("service") == "agent-trace"


def is_claude(record: dict[str, Any]) -> bool:
    return record.get("service") == "claude-code"


def is_codex(record: dict[str, Any]) -> bool:
    return str(record.get("service") or "").startswith("codex")


def attrs_of(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("attrs")
    return value if isinstance(value, dict) else {}


def session_of(record: dict[str, Any]) -> str | None:
    value = attrs_of(record).get("session.id")
    return value if isinstance(value, str) and value else None


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def time_of(record: dict[str, Any]) -> int:
    return as_int(record.get("start") if record.get("type") == "span" else record.get("time"))


# ---------------------------------------------------------------- model


@dataclass
class AgentSpan:
    scope: str
    ident: str
    span_id: str
    name: str
    kind: str
    parent: str | None
    start: int
    end: int | None
    status: str
    note: str
    session: str | None
    attrs: dict[str, Any]
    retry: bool = False
    children: list[AgentSpan] = field(default_factory=list)


@dataclass
class Anomaly:
    ref: str
    kind: str
    start: int
    end: int
    session: str | None
    detail: str


@dataclass
class Row:
    name: str
    active: list[Interval]
    errors: list[int] = field(default_factory=list)
    retries: list[int] = field(default_factory=list)
    waits: list[Interval] = field(default_factory=list)
    duration: int = 0
    status: str = ""


@dataclass
class SessionData:
    sid: str
    tool: str
    active: list[Interval] = field(default_factory=list)
    activity_spans: list[tuple[int, str]] = field(default_factory=list)
    errors: list[Anomaly] = field(default_factory=list)
    retries: list[Anomaly] = field(default_factory=list)
    blocks: list[Anomaly] = field(default_factory=list)
    waits: list[Interval] = field(default_factory=list)


def merge_agent_spans(records: list[dict[str, Any]]) -> list[AgentSpan]:
    starts: dict[tuple[str, str], dict[str, Any]] = {}
    ends: dict[tuple[str, str], dict[str, Any]] = {}
    for record in sorted(records, key=time_of):
        attrs = attrs_of(record)
        phase, ident = attrs.get("agent_trace.phase"), attrs.get("agent_trace.id")
        if record.get("type") != "span" or phase not in ("start", "end") or not isinstance(ident, str):
            continue
        key = (str(attrs.get("agent_trace.scope") or ""), ident)
        if phase == "start":
            starts.setdefault(key, record)
        else:
            ends[key] = record
    spans = []
    for key in list(dict.fromkeys([*starts, *ends])):
        start, end = starts.get(key), ends.get(key)
        first = start or end
        assert first is not None
        start_attrs = attrs_of(start) if start else {}
        end_attrs = attrs_of(end) if end else {}
        merged = {**start_attrs, **end_attrs}
        merged.pop("agent_trace.phase", None)
        spans.append(
            AgentSpan(
                scope=key[0],
                ident=key[1],
                span_id=str(first.get("spanId") or otlp.span_id_for(*key)),
                name=str(start.get("name") if start else key[1]),
                kind=str(start_attrs.get("agent_trace.kind") or ""),
                parent=start_attrs.get("agent_trace.parent"),
                start=time_of(first),
                end=time_of(end) if end else None,
                status=str(end_attrs.get("agent_trace.status") or "open") if end else "open",
                note=str(end_attrs.get("agent_trace.note") or ""),
                session=session_of(first),
                attrs=merged,
            )
        )
    spans.sort(key=lambda span: span.start)
    seen: set[tuple[str, str | None, str]] = set()
    for span in spans:
        key = (span.name, span.parent, span.scope)
        span.retry = key in seen
        seen.add(key)
    return spans


def tool_label(attrs: dict[str, Any]) -> str:
    parts = [str(attrs.get("tool_name") or "tool")]
    if attrs.get("bash_argv0"):
        parts.append(str(attrs["bash_argv0"]))
    return " ".join(parts)


def claude_session(sid: str, spans: list[dict[str, Any]]) -> SessionData:
    data = SessionData(sid, "claude")
    by_id = {span.get("spanId"): span for span in spans}
    tool_errored: dict[str, bool] = {}
    for span in spans:
        name, attrs = span.get("name"), attrs_of(span)
        start, end = int(span.get("start") or 0), int(span.get("end") or 0)
        if name == "claude_code.interaction":
            data.active.append((start, end))
            data.activity_spans.append((start, str(span.get("spanId"))))
        elif name == "claude_code.tool.execution":
            if (span.get("status") or {}).get("code") == 2 or falsy(attrs.get("success")):
                parent = by_id.get(span.get("parentSpanId")) or {}
                tool_errored[str(span.get("parentSpanId"))] = True
                detail = tool_label(attrs_of(parent))
                error_class = attrs.get("error_class") or (span.get("status") or {}).get("message")
                if error_class:
                    detail += f" {error_class}"
                data.errors.append(Anomaly(str(span.get("spanId")), "error", start, end, sid, detail))
        elif name == "claude_code.tool.blocked_on_user":
            data.waits.append((start, end))
            if attrs.get("decision") != "accept":
                parent = by_id.get(span.get("parentSpanId")) or {}
                detail = f"{tool_label(attrs_of(parent))} decision={attrs.get('decision') or 'unknown'}"
                data.blocks.append(Anomaly(str(span.get("spanId")), "block", start, end, sid, detail))
        elif name == "claude_code.llm_request":
            attempts = [
                (int(event.get("time") or 0), attrs_of(event).get("attempt"))
                for event in span.get("events") or []
                if event.get("name") == "gen_ai.request.attempt"
            ]
            retried = [(when, n) for when, n in attempts if isinstance(n, int) and n > 1]
            if retried:
                when, number = retried[0]
                anomaly = Anomaly(str(span.get("spanId")), "retry", when, when, sid, f"llm_request attempt {number}")
                data.retries.append(anomaly)
    siblings: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        if span.get("name") == "claude_code.tool":
            siblings.setdefault(str(span.get("parentSpanId")), []).append(span)
    for group in siblings.values():
        group.sort(key=lambda span: int(span.get("start") or 0))
        for index, span in enumerate(group):
            label = tool_label(attrs_of(span))
            earlier = [other for other in group[:index] if tool_label(attrs_of(other)) == label]
            if earlier and tool_errored.get(str(earlier[-1].get("spanId"))):
                start, end = int(span.get("start") or 0), int(span.get("end") or 0)
                data.retries.append(Anomaly(str(span.get("spanId")), "retry", start, end, sid, label))
    return data


def codex_session(sid: str, records: list[dict[str, Any]]) -> SessionData:
    data = SessionData(sid, "codex")
    for record in records:
        attrs = attrs_of(record)
        if record.get("type") == "span" and record.get("name") in CODEX_TURNS:
            start, end = int(record.get("start") or 0), int(record.get("end") or 0)
            data.active.append((start, end))
            data.activity_spans.append((start, str(record.get("spanId"))))
        elif attrs.get("event.name") == "codex.tool_result" and falsy(attrs.get("success")):
            when = time_of(record)
            detail = str(attrs.get("tool_name") or "tool")
            data.errors.append(Anomaly(str(record.get("spanId")), "error", when, when, sid, detail))
    return data


# ---------------------------------------------------------------- selection


@dataclass
class Selection:
    agent: list[dict[str, Any]]
    sessions: list[str]
    claude: dict[str, list[dict[str, Any]]]
    codex: dict[str, list[dict[str, Any]]]

    @property
    def native(self) -> list[dict[str, Any]]:
        return [r for group in (*self.claude.values(), *self.codex.values()) for r in group]


def select(records: list[dict[str, Any]], ticket: str | None, wanted: list[str]) -> Selection:
    wanted_set = set(wanted)

    def agent_match(record: dict[str, Any]) -> bool:
        if not is_agent(record):
            return False
        if ticket and attrs_of(record).get("run.ticket") == ticket:
            return True
        return session_of(record) in wanted_set

    agent = [r for r in records if agent_match(r)]
    sessions = list(dict.fromkeys([*wanted, *[s for s in map(session_of, agent) if s]]))
    session_set = set(sessions)
    claude: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        sid = session_of(record)
        if is_claude(record) and record.get("type") == "span" and sid in session_set:
            claude.setdefault(sid or "", []).append(record)
    trace_session: dict[str, str] = {}
    direct: list[tuple[dict[str, Any], str]] = []
    for record in records:
        if not is_codex(record):
            continue
        attrs = attrs_of(record)
        sid = next((attrs[k] for k in ("conversation.id", "thread.id") if attrs.get(k) in session_set), None)
        if sid:
            direct.append((record, sid))
            trace_session.setdefault(str(record.get("traceId")), sid)
    codex: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not is_codex(record):
            continue
        attrs = attrs_of(record)
        sid = next((attrs[k] for k in ("conversation.id", "thread.id") if attrs.get(k) in session_set), None)
        sid = sid or trace_session.get(str(record.get("traceId")))
        if sid:
            codex.setdefault(sid, []).append(record)
    return Selection(agent, sessions, claude, codex)


# ---------------------------------------------------------------- layout


@dataclass
class Layout:
    columns: list[tuple[int, int, bool]]  # (start, end, is_gap)
    segments: list[tuple[int, int, int, int]]  # (start, end, first column, column count)
    gaps: list[tuple[int, int, int]]  # (start, end, column)

    def column_of(self, when: int) -> int:
        for start, end, column in self.gaps:
            if start < when < end:
                return column
        best = 0
        for start, end, first, count in self.segments:
            if when < start:
                break
            span = max(1, end - start)
            best = first + min(count - 1, max(0, (when - start) * count // span))
        return best


def build_layout(t0: int, t1: int, activity: list[Interval], width: int) -> Layout:
    merged = union(activity)
    gaps = [
        (a_end, b_start)
        for (_, a_end), (b_start, _) in zip(merged, merged[1:], strict=False)
        if b_start - a_end > IDLE_COLLAPSE
    ]
    bounds = [t0, *[edge for gap in gaps for edge in gap], t1]
    segments = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds), 2)]
    available = max(len(segments), width - len(gaps))
    total = sum(end - start for start, end in segments) or 1
    counts = [1] * len(segments)
    spare = available - len(segments)
    shares = [(end - start) / total * spare for start, end in segments]
    for index, share in enumerate(shares):
        counts[index] += int(share)
    leftover = available - sum(counts)
    order = sorted(range(len(segments)), key=lambda i: shares[i] - int(shares[i]), reverse=True)
    for index in order[:leftover]:
        counts[index] += 1
    columns: list[tuple[int, int, bool]] = []
    placed_segments = []
    placed_gaps = []
    for index, (start, end) in enumerate(segments):
        first = len(columns)
        count = counts[index]
        for k in range(count):
            columns.append((start + (end - start) * k // count, start + (end - start) * (k + 1) // count, False))
        placed_segments.append((start, end, first, count))
        if index < len(gaps):
            placed_gaps.append((gaps[index][0], gaps[index][1], len(columns)))
            columns.append((gaps[index][0], gaps[index][1], True))
    return Layout(columns, placed_segments, placed_gaps)


def render_bar(row: Row, layout: Layout) -> str:
    cells = []
    marks_error = {layout.column_of(t) for t in row.errors}
    marks_retry = {layout.column_of(t) for t in row.retries}
    waits = union(row.waits)
    active = union(row.active)
    for index, (start, end, is_gap) in enumerate(layout.columns):
        if is_gap:
            cells.append("┆")
            continue
        if index in marks_error:
            cells.append("✗")
            continue
        if index in marks_retry:
            cells.append("↻")
            continue
        size = max(1, end - start)
        waited = sum(max(0, min(e, end) - max(s, start)) for s, e in waits)
        if waits and waited * 2 >= size:
            cells.append("▒")
            continue
        busy = any(min(e, end) > max(s, start) or (s == e and start <= s <= end) for s, e in active)
        cells.append("█" if busy else " ")
    return "".join(cells)


def axis_lines(layout: Layout, t0: int, t1: int, width: int) -> list[str]:
    cells = [" "] * width
    used = [False] * width

    def place(text: str, at: int) -> bool:
        if at < 0 or at + len(text) > width or any(used[at : at + len(text)]):
            return False
        for offset, char in enumerate(text):
            cells[at + offset] = char
            used[at + offset] = True
        return True

    place(clock(t0), 0)
    place(clock(t1), width - 5)
    footnotes = []
    for start, end, column in layout.gaps:
        label = f"┆ {fmt_duration(end - start)} idle"
        if not place(label + " ", column) and not place(label, column):
            cells[column] = "┆"
            footnotes.append(f"┆ = {fmt_duration(end - start)} idle ({clock(start)}–{clock(end)})")
    return ["".join(cells).rstrip(), *footnotes]


# ---------------------------------------------------------------- report


def truncate(name: str, limit: int) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def gh_view(url: str) -> str:
    try:
        result = subprocess.run(
            ["gh", "pr", "view", url, "--json", "state,headRefOid,mergeCommit"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise ValueError("gh failed")
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("gh failed")
    except (OSError, subprocess.SubprocessError, ValueError):
        return "merge sha unknown (gh failed)"
    return json.dumps(data)


def pr_lines(records: list[dict[str, Any]], offline: bool) -> list[str]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in sorted(records, key=time_of):
        attrs = attrs_of(record)
        key = str(attrs.get("agent_trace.pr_url") or attrs.get("agent_trace.pr_ref") or "unknown PR")
        groups.setdefault(key, []).append(attrs)
    lines = []
    for key, items in groups.items():
        actions = list(dict.fromkeys(str(a.get("agent_trace.pr_action")) for a in items))
        heads = [str(a["agent_trace.head_sha"]) for a in items if a.get("agent_trace.head_sha")]
        merge_heads = [
            str(a["agent_trace.head_sha"])
            for a in items
            if a.get("agent_trace.pr_action") == "merge" and a.get("agent_trace.head_sha")
        ]
        parts = [key, ", ".join(actions)]
        if heads:
            parts.append(f"head {heads[-1][:7]}")
        if not offline and key.startswith("https://github.com/"):
            answer = gh_view(key)
            if answer.startswith("{"):
                data = json.loads(answer)
                state = str(data.get("state") or "unknown").lower()
                commit = data.get("mergeCommit") if isinstance(data.get("mergeCommit"), dict) else None
                oid = str((commit or {}).get("oid") or "")
                parts.append(f"{state}, merge {oid[:7]}" if oid else f"{state}, merge sha unknown (not merged)")
                remote_head = str(data.get("headRefOid") or "")
                if merge_heads and remote_head and remote_head != merge_heads[-1]:
                    parts.append("head moved")
            else:
                parts.append(answer)
        lines.append("  " + "  ".join(parts))
    return lines


def transcript_fallback(sid: str) -> list[str]:
    if not SESSION_NAME.match(sid):
        return []
    root = Path(os.environ.get("AGENT_TRACE_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")
    files = sorted(root.glob(f"*/{sid}.jsonl"))
    if not files:
        return [f"(no transcript found for {sid} under {root})"]
    try:
        result = subprocess.run(
            [sys.executable, str(TIMELINE), "--session", sid, *map(str, files)],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return [f"(transcript timeline failed: {error})"]
    if result.returncode != 0:
        return [f"(transcript timeline failed: {result.stderr.strip()[:200]})"]
    return [f"Transcript timeline for {sid}:", *result.stdout.rstrip("\n").splitlines()]


def scrub(attrs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attrs.items() if key not in IDENTITY_ATTRS}


def jaeger_request(
    scope: str,
    label: str,
    t0: int,
    t1: int,
    agent_spans: list[AgentSpan],
    others: list[dict[str, Any]],
    native: list[dict[str, Any]],
) -> tuple[dict[str, Any], int, str]:
    trace = otlp.trace_id_for(scope)
    root_id = otlp.span_id_for(scope, "run")
    by_ident = {(span.scope, span.ident): span for span in agent_spans}
    spans: list[dict[str, Any]] = [
        {
            "type": "span",
            "service": "agent-trace",
            "traceId": trace,
            "spanId": root_id,
            "parentSpanId": None,
            "name": label,
            "start": t0,
            "end": t1,
            "status": {"code": 0, "message": ""},
            "attrs": {"agent_trace.scope": scope},
            "events": [],
        }
    ]
    for span in agent_spans:
        parent = by_ident.get((span.scope, span.parent)) if span.parent else None
        attrs = scrub(span.attrs)
        if span.end is None:
            attrs["agent_trace.open"] = True
        spans.append(
            {
                "type": "span",
                "service": "agent-trace",
                "traceId": trace,
                "spanId": span.span_id,
                "parentSpanId": parent.span_id if parent else root_id,
                "name": span.name,
                "start": span.start,
                "end": span.end if span.end is not None else max(t1, span.start),
                "status": {"code": 2 if span.status == "error" else 0, "message": ""},
                "attrs": attrs,
                "events": [],
            }
        )
    for record in [*others, *native]:
        if record.get("type") != "span":
            continue
        spans.append({**record, "traceId": trace, "attrs": scrub(attrs_of(record))})
    ids = {span["spanId"] for span in spans}
    for span in spans[1:]:
        if span.get("parentSpanId") not in ids or span.get("parentSpanId") == span["spanId"]:
            span["parentSpanId"] = root_id
    return otlp.encode_traces(spans), len(spans), trace


def post_jaeger(url: str, body: dict[str, Any]) -> None:
    import urllib.request

    target = url.rstrip("/")
    if not target.endswith("/v1/traces"):
        target += "/v1/traces"
    request = urllib.request.Request(
        target, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        response.read()


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for record in records:
        key = json.dumps(record, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(record)
    return out


def run(args: argparse.Namespace) -> int:
    if not args.ticket and not args.session:
        print("agent-trace: show needs --ticket or --session", file=sys.stderr)
        return 2
    base = Path(args.dir).expanduser() if args.dir else store.state_dir()
    width = max(10, int(args.width))
    selection = select(dedupe(store.read_all(base)), args.ticket, list(args.session))
    if not selection.agent and not selection.native:
        what = f"ticket {args.ticket}" if args.ticket else "session " + ", ".join(args.session)
        print(f"agent-trace: no spans for {what}", file=sys.stderr)
        return 1

    agent_spans_all = [r for r in selection.agent if r.get("type") == "span"]
    notes = [r for r in agent_spans_all if r.get("name") == "agent_trace.note"]
    prs = [r for r in agent_spans_all if r.get("name") == "agent_trace.pr"]
    spans = merge_agent_spans(agent_spans_all)
    sessions: list[SessionData] = []
    for sid in selection.sessions:
        if selection.claude.get(sid):
            sessions.append(claude_session(sid, selection.claude[sid]))
        elif selection.codex.get(sid):
            sessions.append(codex_session(sid, selection.codex[sid]))
    sessions.sort(key=lambda data: min((s for s, _ in data.active), default=0))

    times: list[int] = []
    for record in selection.native:
        if record.get("type") == "span":
            times += [int(record.get("start") or 0), int(record.get("end") or 0)]
    for span in spans:
        times += [span.start] + ([span.end] if span.end is not None else [])
    times = [t for t in times if t > 0] or [otlp.now_ns()]
    t0, t1 = min(times), max(times)

    def span_interval(span: AgentSpan) -> Interval:
        return span.start, max(span.start, span.end if span.end is not None else t1)

    wait_spans = [span for span in spans if span.kind == "wait"]
    waits_all = [*[w for data in sessions for w in data.waits], *map(span_interval, wait_spans)]
    turn_time = [i for data in sessions for i in data.active]
    activity = [*turn_time, *map(span_interval, wait_spans)]
    layout = build_layout(t0, t1, activity, width)

    scope = args.ticket or selection.sessions[0] if (args.ticket or selection.sessions) else "run"
    label = f"run {args.ticket}" if args.ticket else f"run {selection.sessions[0][:8]}"
    rows: list[Row] = []
    by_ident = {(span.scope, span.ident): span for span in spans}
    for span in spans:
        parent = by_ident.get((span.scope, span.parent)) if span.parent else None
        if parent is not None and parent is not span:
            parent.children.append(span)
    child_ids = {id(child) for span in spans for child in span.children}
    shown: set[int] = set()

    def add(span: AgentSpan, depth: int) -> None:
        if id(span) in shown:
            return
        shown.add(id(span))
        interval = span_interval(span)
        rows.append(
            Row(
                name="  " * depth + span.name,
                active=[interval],
                errors=[interval[1]] if span.status == "error" else [],
                retries=[span.start] if span.retry else [],
                waits=[interval] if span.kind == "wait" else [],
                duration=interval[1] - interval[0],
                status=span.status,
            )
        )
        for child in sorted(span.children, key=lambda s: s.start):
            add(child, depth + 1)

    for span in spans:
        if id(span) not in child_ids:
            add(span, 1)
    for span in spans:  # Spans in a parent cycle have no root; show them at the top level.
        add(span, 1)
    for data in sessions:
        rows.append(
            Row(
                name=f"  {data.tool} {data.sid[:8]}",
                active=data.active,
                errors=[a.start for a in data.errors],
                retries=[a.start for a in data.retries],
                waits=data.waits,
                duration=measure(data.active),
            )
        )
    root = Row(
        name=label,
        active=[i for row in rows for i in row.active],
        errors=[t for row in rows for t in row.errors],
        retries=[t for row in rows for t in row.retries],
        waits=waits_all,
        duration=t1 - t0,
    )
    rows.insert(0, root)

    name_width = min(NAME_LIMIT, max(len(row.name) for row in rows))
    bar_width = len(layout.columns)
    out = ["```text"]
    for row in rows:
        name = truncate(row.name, name_width)
        line = f"{name:<{name_width}} |{render_bar(row, layout)}| {fmt_duration(row.duration):>5}"
        out.append(line + (f" {row.status}" if row.status else ""))
    axis = axis_lines(layout, t0, t1, bar_width)
    out.append(" " * (name_width + 2) + axis[0])
    out += axis[1:]
    errors = sum(len(d.errors) for d in sessions) + sum(1 for s in spans if s.status == "error")
    retries = sum(len(d.retries) for d in sessions) + sum(1 for s in spans if s.retry)
    open_spans = sum(1 for s in spans if s.end is None)
    active = measure(subtract(turn_time, waits_all))
    out.append(
        f"total {fmt_duration(t1 - t0)} · active {fmt_duration(active)}"
        f" · wait on Marcus {fmt_duration(measure(waits_all))}"
        f" · errors {errors} · retries {retries} · open spans {open_spans}"
    )
    out.append("```")

    if prs:
        out += ["", "PRs:", *pr_lines(prs, args.offline)]
    parks = [span for span in spans if span.status == "parked"]
    if parks:
        out += ["", "Parks:", *[f"  {span.ident}  {span.note}".rstrip() for span in parks]]
    friction = [r for r in notes if attrs_of(r).get("agent_trace.note_kind") == "friction"]
    if friction:
        out += ["", "Notes:"]
        for record in sorted(friction, key=time_of):
            attrs = attrs_of(record)
            out.append(
                f"  {clock(time_of(record))}  {attrs.get('agent_trace.category')}: {attrs.get('agent_trace.what')}"
                f" (fix: {attrs.get('agent_trace.fix')})"
            )

    anomalies: list[Anomaly] = [a for d in sessions for a in (*d.errors, *d.retries, *d.blocks)]
    activity_starts = sorted(
        [(start, ref, data.sid) for data in sessions for start, ref in data.activity_spans]
        + [(span.start, span.span_id, span.session) for span in wait_spans]
    )
    merged = union(activity)
    for (_, gap_start), (gap_end, _) in zip(merged, merged[1:], strict=False):
        if gap_end - gap_start <= GAP_ANOMALY:
            continue
        after = next(((s, ref, sid) for s, ref, sid in activity_starts if s >= gap_end), None)
        if after:
            detail = f"{fmt_duration(gap_end - gap_start)} idle"
            anomalies.append(Anomaly(f"gap-{after[1]}", "gap", gap_start, gap_end, after[2], detail))
    answered_refs = {
        str(ref) for r in notes for ref in (attrs_of(r).get("agent_trace.refs") or []) if isinstance(ref, str)
    }
    unanswered = []
    for anomaly in sorted(anomalies, key=lambda a: (a.start, a.ref)):
        if anomaly.ref in answered_refs:
            continue
        near = any(
            session_of(r) == anomaly.session and anomaly.start - NOTE_BEFORE <= time_of(r) <= anomaly.end + NOTE_AFTER
            for r in friction
        )
        if not near:
            unanswered.append(anomaly)
    out.append("")
    if unanswered:
        out.append("Reconcile:")
        out += [f"  {a.ref}  {clock(a.start)}  {a.kind}  {a.detail}" for a in unanswered]
        ticket_flag = f" --ticket {args.ticket}" if args.ticket else ""
        out += [
            "Answer each with one of:",
            f'  agent-trace note friction --category <category> --what "<what>" --fix "<fix>" --ref <ref>{ticket_flag}',
            f"  agent-trace note none --ref <ref> [--ref <ref> ...]{ticket_flag}",
        ]
    else:
        out.append("Reconcile: none")

    for sid in selection.sessions:
        if not selection.claude.get(sid) and not selection.codex.get(sid):
            out += ["", f"warning: session {sid} has no native spans (collect was down or telemetry was off)"]
            out += transcript_fallback(sid)

    print("\n".join(out))

    if args.jaeger:
        others = [*notes, *prs]
        native = [r for r in selection.native if r.get("type") == "span"]
        body, count, trace = jaeger_request(str(scope), label, t0, t1, spans, others, native)
        try:
            post_jaeger(args.jaeger, body)
            print(f"jaeger: posted {count} spans, trace {trace}")
        except (OSError, ValueError) as error:
            print(f"agent-trace: warning: jaeger post failed: {error}", file=sys.stderr)
    return 0
