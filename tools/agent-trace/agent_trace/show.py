"""`agent-trace show`: the gaps view of a work ID's run, from stored agent and native spans and from transcripts.

Selection. Every spans/*.jsonl file and fallback.jsonl is read. The agent records are the `agent-trace` records
with `run.ticket` == --work, plus the `agent-trace` records whose `session.id` is a --session. The sessions are
the --session values, the sessions bound to the work ID in sessions/<id>.ticket, and the session ids of those agent
records. Native records are the Claude Code spans of those sessions, and the Codex spans and logs whose `thread.id`
or `conversation.id` is one of them, plus any Codex record that shares a trace id with such a record.

Gaps. A session with native spans gives its gaps from them: a `block` for each permission prompt that was not
accepted, and a `fail` for each failed tool call. A session with none gives its gaps from its transcript
(`transcript_anomalies`). In both, failed reads, failed agent-trace calls, and soft fails are not gaps. A fail that
one of the next calls recovered is not a gap unless its label failed twice: in a transcript, the same call (the same
tool and input) run again; for a native span, a later call of the same tool, but never for Bash, whose span names
the program only.
Every idle gap longer than GAP_ANOMALY that no wait span covers is `idle`.

Output. One `text` fence: the run window and totals, the wall time and span coverage, GAPS (grouped by kind and
key, most costly first), RUN SHAPE (the bar chart of spans, its first SHAPE_ROWS rows), and SESSIONS. Then
Reconcile (gaps that no note answers), PRs (with GitHub state unless --offline), and Parks. Every time is UTC.
`--gantt` prints the whole bar chart alone instead, and `--timeline` the transcript timeline of each session.
Prompts, command text past the program, and identity attributes are never printed.

Exit 0 when anything matched, 1 when nothing matched, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_trace import otlp, store

MIN = 60 * 1_000_000_000
IDLE_COLLAPSE = 30 * MIN
GAP_ANOMALY = 10 * MIN
NOTE_BEFORE = 2 * MIN
NOTE_AFTER = 10 * MIN
NAME_LIMIT = 32
GAP_ROWS = 15  # rows of the GAPS list before "… N more"
SHAPE_ROWS = 16  # chart rows of RUN SHAPE, the run row included
SESSION_ROWS = 8
RECOVER_WINDOW = 3  # a fail is recovered when one of this many next calls of the same tool and program succeeds
READS = {"cat", "ls", "grep", "rg", "head", "tail"}  # a failed read is a lookup, never a gap
IDENTITY_ATTRS = {"user.email", "user.id", "user.account_uuid", "user.account_id", "organization.id"}
SESSION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CODEX_TURNS = {"session_task.turn", "run_turn"}
TIMELINE = Path(__file__).resolve().parents[3] / "skills" / "retro" / "scripts" / "timeline.py"

Interval = tuple[int, int]
Merge = tuple[int, int | None]  # (park time, merge time or None when unknown) of one parked PR


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


def utc(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, UTC).strftime("%H:%MZ")


def stamp(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, UTC).strftime("%m-%d %H:%MZ")


def window(start: int, end: int) -> str:
    return f"{stamp(start)} → {stamp(end)} ({fmt_duration(end - start)})"


def iso_ns(value: Any) -> int | None:
    """Nanoseconds since the epoch for an ISO 8601 time, or None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


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
    """One event that may be a gap: kind is block, fail, idle, wait, retry (chart only), or transcript (unread).

    A `wait` is an idle gap whose cause is known: it is in GAPS with its cause, but not in Reconcile.
    """

    ref: str
    kind: str
    start: int
    end: int
    session: str | None
    detail: str
    count: int = 1  # the fails that one transcript anomaly groups
    recovered: bool = False  # a later call of the same tool and program succeeded: on the chart, not a gap
    cause: str = ""  # what a wait waited on, such as "wait on merge": it groups the wait in GAPS
    words: str = ""  # the words that matched the ask, when the cause comes from words

    @property
    def cost(self) -> int:
        """The time this gap lost: the wait of a block, the length of an idle gap, else 0."""
        return self.end - self.start if self.kind in ("block", "idle", "wait") else 0

    @property
    def key(self) -> str:
        """What groups anomalies within one run: the cause, else the detail without its repeat count. Idle gaps
        without a cause share one key."""
        if self.cause:
            return self.cause
        if self.kind == "idle" and not self.detail.endswith("(polling)"):
            return "unexplained"
        return re.sub(r" x\d+\b", "", self.detail)


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
    tool_succeeded: set[str] = set()  # tool spans whose execution ran and succeeded
    pending: list[tuple[str, Anomaly]] = []  # (tool span id, error) until recovery is known
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
                anomaly = Anomaly(str(span.get("spanId")), "fail", start, end, sid, detail)
                pending.append((str(span.get("parentSpanId")), anomaly))
            else:
                tool_succeeded.add(str(span.get("parentSpanId")))
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

    failures: dict[str, int] = {}  # tool label -> failed calls in the whole session
    for span in spans:
        if span.get("name") == "claude_code.tool" and tool_errored.get(str(span.get("spanId"))):
            failures[tool_label(attrs_of(span))] = failures.get(tool_label(attrs_of(span)), 0) + 1

    def recovered(tool: dict[str, Any]) -> bool:
        """One of the next calls in this turn ran the same tool and succeeded, and the tool did not fail twice.

        A Bash span names its program but not the subcommand, so a later call of the same program proves nothing:
        a Bash fail is never recovered.
        """
        attrs = attrs_of(tool)
        label = tool_label(attrs)
        if attrs.get("tool_name") == "Bash" or failures.get(label, 0) > 1:
            return False
        group = siblings.get(str(tool.get("parentSpanId")), [])
        later = group[group.index(tool) + 1 :][:RECOVER_WINDOW] if tool in group else []
        return any(
            tool_label(attrs_of(other)) == label and str(other.get("spanId")) in tool_succeeded for other in later
        )

    for tool_id, anomaly in pending:
        tool = by_id.get(tool_id) or {}
        argv0 = str(attrs_of(tool).get("bash_argv0") or "")
        if argv0 == "agent-trace" or argv0 in READS:
            continue  # The agent's own trace calls and failed lookups are never errors.
        anomaly.recovered = bool(tool) and recovered(tool)
        data.errors.append(anomaly)
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
            data.errors.append(Anomaly(str(record.get("spanId")), "fail", when, when, sid, detail))
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


def select(
    records: list[dict[str, Any]], ticket: str | None, wanted: list[str], bound: list[str] | None = None
) -> Selection:
    """Pick the records of one run. `wanted` sessions are explicit and give all their agent records.

    A `bound` session is only discovered: it gives its transcript and native spans, but its agent records
    count only when they name this ticket, because one session can serve several work IDs in turn.
    """
    wanted_set = set(wanted)

    def agent_match(record: dict[str, Any]) -> bool:
        if not is_agent(record):
            return False
        if ticket and attrs_of(record).get("run.ticket") == ticket:
            return True
        return session_of(record) in wanted_set

    agent = [r for r in records if agent_match(r)]
    sessions = list(dict.fromkeys([*wanted, *(bound or []), *[s for s in map(session_of, agent) if s]]))
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

    place(utc(t0), 0)
    place(utc(t1), width - 6)
    footnotes = []
    for start, end, column in layout.gaps:
        label = f"┆ {fmt_duration(end - start)} idle"
        if not place(label + " ", column) and not place(label, column):
            cells[column] = "┆"
            footnotes.append(f"┆ = {fmt_duration(end - start)} idle ({utc(start)}–{utc(end)})")
    return ["".join(cells).rstrip(), *footnotes]


# ---------------------------------------------------------------- report


def truncate(name: str, limit: int) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


@functools.cache
def gh_view(url: str) -> str:
    """The GitHub state of a PR as JSON text, or a reason. One `gh` call per PR in each run of `show`."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", url, "--json", "state,headRefOid,mergeCommit,mergedAt,commits"],
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


def pr_lines(records: list[dict[str, Any]], offline: bool) -> tuple[list[str], list[str]]:
    """One line per PR, and the GitHub state of each PR that GitHub answered for."""
    states: list[str] = []
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
                states.append(state)
                commit = data.get("mergeCommit") if isinstance(data.get("mergeCommit"), dict) else None
                oid = str((commit or {}).get("oid") or "")
                parts.append(f"{state}, merge {oid[:7]}" if oid else f"{state}, merge sha unknown (not merged)")
                remote_head = str(data.get("headRefOid") or "")
                if merge_heads and remote_head and remote_head != merge_heads[-1]:
                    parts.append("head moved")
            else:
                parts.append(answer)
        lines.append("  " + "  ".join(parts))
    return lines, states


def run_timeline(sid: str, *extra: str) -> tuple[str | None, str]:
    """Run the retro timeline on a session's Claude Code transcripts: (stdout, "") or (None, a reason)."""
    root = Path(os.environ.get("AGENT_TRACE_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")
    files = sorted(root.glob(f"*/{sid}.jsonl"))
    if not files:
        return None, f"no transcript found for {sid} under {root}"
    try:
        result = subprocess.run(
            [sys.executable, str(TIMELINE), "--session", sid, *extra, *map(str, files)],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"transcript timeline failed: {error}"
    if result.returncode != 0:
        return None, f"transcript timeline failed: {result.stderr.strip()[:200]}"
    return result.stdout, ""


def transcript_fallback(sid: str) -> list[str]:
    if not SESSION_NAME.match(sid):
        return []
    stdout, reason = run_timeline(sid)
    if stdout is None:
        return [f"({reason})"]
    return [f"Transcript timeline for {sid}:", *stdout.rstrip("\n").splitlines()]


# The fix target of each wait, by its cause and ask class: where a change would shorten that wait. The first row
# whose cause starts the wait's cause wins, so a row with a class comes before the row of its cause alone.
FIX_TARGETS = (
    ("wait on merge", "Marcus merge step"),
    ("wait on Marcus: merge", "merge rule: the PR parks for Marcus"),
    ("wait on Marcus: access", "intake grants the access"),
    ("wait on Marcus: scope", "brief or ticket names the scope"),
    ("wait on Marcus", "brief or ticket names the default"),
    ("wait on router", "matrix: router answers or sets a decision default"),
    ("wait on another session", "matrix: router heartbeat"),
    ("background task", "neo: wait span around the watch"),
    ("context compaction", "harness"),
)
WAIT_CAUSES = {
    "peer": "wait on router",
    "background": "background task (CI or watcher)",
    "linked": "wait on another session",
    "compaction": "context compaction",
}


# Waits that a reserved rule causes: they print under RESERVED, not GAPS, and never go to Reconcile.
RESERVED_CAUSES = ("wait on merge", "wait on Marcus: merge")


def is_reserved(anomaly: Anomaly) -> bool:
    return anomaly.kind == "wait" and anomaly.cause.startswith(RESERVED_CAUSES)


def peer_transcript(peer: str) -> str | None:
    """The transcript session id of another session, from the `from` id of its messages, or None.

    The id is `local_<id>`. The transcript is `<id>.jsonl`, or the `cliSessionId` that the Claude desktop app's
    record of that session names (under $AGENT_TRACE_DESKTOP_SESSIONS).
    """
    bare = peer.removeprefix("local_")
    if SESSION_NAME.match(bare) and transcript_files(bare)[1]:
        return bare
    default = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    root = Path(os.environ.get("AGENT_TRACE_DESKTOP_SESSIONS") or default)
    if not SESSION_NAME.match(peer):
        return None
    for path in sorted(root.glob(f"*/*/{peer}.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        cli = record.get("cliSessionId") if isinstance(record, dict) else None
        if isinstance(cli, str) and SESSION_NAME.match(cli) and transcript_files(cli)[1]:
            return cli
    return None


@functools.cache
def marcus_waits(peer: str) -> tuple[tuple[int, int, str], ...]:
    """The gaps of another session (the router) that a message Marcus typed ended: (start, end, ask class).

    The class comes from the router's ask before its gap, else `reply`. Empty when its transcript cannot be read.
    """
    sid = peer_transcript(peer)
    stdout = run_timeline(sid, "--json", "--gap-minutes", str(GAP_ANOMALY / MIN))[0] if sid else None
    try:
        report = json.loads(stdout) if stdout else {}
    except ValueError:
        report = {}
    waits = []
    for gap in report.get("gaps") or [] if isinstance(report, dict) else []:
        start, end = iso_ns(gap.get("start")), iso_ns(gap.get("end"))
        if start and end and gap.get("ended_by") == "user":
            ask = gap.get("ask") if isinstance(gap.get("ask"), dict) else {}
            waits.append((start, end, str(ask.get("class") or "reply")))
    return tuple(waits)


def fix_target(cause: str) -> str:
    """The fix target of a wait cause, from FIX_TARGETS, or "" when the cause has none."""
    return next((fix for prefix, fix in FIX_TARGETS if cause.startswith(prefix)), "")


def gap_cause(gap: dict[str, Any], start: int, merges: list[Merge]) -> tuple[str, str]:
    """The cause of a transcript gap and the words that it matched: ("", "") when the gap stays unexplained.

    In order: the time between a park and the merge of its PR; a message that Marcus typed; an ask in the last
    assistant text, matched by words and marked so; then the event that ended the gap. `merges` holds only parks
    whose merge time is known: transcript_anomalies handles a park with an unknown merge time.
    """
    for parked, merged in merges:
        if merged is not None and parked <= start < merged:
            return "wait on merge", ""
    ask = gap.get("ask") if isinstance(gap.get("ask"), dict) else None
    words = ""
    if ask:
        words = 'matched "' + str(ask.get("who")) + '"' + (f' + "{ask.get("word")}"' if ask.get("word") else "")
    ended = str(gap.get("ended_by"))
    if ended == "user":
        return f"wait on Marcus: {ask.get('class') if ask else 'reply'}", words
    if ask:
        who = "Marcus" if "marcus" in str(ask.get("who")).lower() else "router"
        return f"wait on {who}: {ask.get('class')} (by words)", words
    woke = str(gap.get("woke_by") or "")
    return WAIT_CAUSES.get(ended, ""), (f"from {woke}" if woke else "")


def transcript_anomalies(
    sid: str, waits: list[Interval], fallback_time: int, merges: list[Merge] | None = None
) -> list[Anomaly]:
    """The anomalies of a session that has no native spans, from its transcript, for the Reconcile list.

    One `block` for each call that a hook or the auto-mode classifier blocked, with the hook name or the denial
    reason. One `fail` for each cause of failure (fails grouped by error text with digit runs replaced, as the
    timeline groups them), and one `idle` for each gap longer than GAP_ANOMALY that no wait span covers. A gap that
    is one long tool call is activity, not idle. An idle gap with a cause (see gap_cause) is a `wait`, which is
    not in Reconcile. `merges` holds the (park, merge) times of this session's parked PRs. Left out: soft fails (an
    error line in the output of a call that succeeded), failed agent-trace calls, failed reads, and a fail that the
    same call (the same tool and input) run again within the next calls recovered, unless its label failed twice.
    The same call 3 or more times in a row (polling) is `idle` too. When the transcript is missing or cannot be read,
    one `transcript` anomaly stands for it, so Reconcile never passes on missing evidence. Refs are
    `tx-<session8>-<kind>-<HHMMSS UTC>` (`gap` for an idle gap, `idle` for polling), stable across runs of `show`.
    """
    if not SESSION_NAME.match(sid):
        return []
    prefix = f"tx-{sid[:8]}"
    stdout, reason = run_timeline(sid, "--json", "--gap-minutes", str(GAP_ANOMALY / MIN))
    report: dict[str, Any] = {}
    if stdout is not None:
        try:
            loaded = json.loads(stdout)
            report = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            reason = "transcript timeline printed no JSON"
    if not report:
        return [Anomaly(f"{prefix}-unread", "transcript", fallback_time, fallback_time, sid, reason or "no events")]

    def hms(ns: int) -> str:
        return datetime.fromtimestamp(ns / 1_000_000_000, UTC).strftime("%H%M%S")

    def program(label: str) -> str:
        """The tool and the program only, as tool_label gives for native spans: never more command text."""
        tool, _, inner = label.partition("(")
        return " ".join([tool, *inner.rstrip(")").split()[:1]])

    found: list[Anomaly] = []
    plain: list[dict[str, Any]] = []
    for fail in report.get("fails") or []:
        if fail.get("soft"):
            continue
        block = fail.get("block") if isinstance(fail.get("block"), dict) else None
        label = program(str(fail.get("label") or "?"))
        if block is None:
            # A failed agent-trace call or read is never a gap; a block of one still is.
            if label != "Bash agent-trace" and label.split()[-1] not in READS:
                plain.append(fail)
            continue
        when = iso_ns(fail.get("time")) or fallback_time
        name = str(block.get("name") or "")
        by = str(block.get("by") or "")
        why = f"hook {name}".strip() if by == "hook" else name or by
        found.append(Anomaly(f"{prefix}-block-{hms(when)}", "block", when, when, sid, f"{label} ({why})"))
    labels: dict[str, int] = {}
    for fail in plain:
        labels[str(fail.get("label"))] = labels.get(str(fail.get("label")), 0) + 1
    groups: dict[str, list[dict[str, Any]]] = {}
    for fail in plain:
        if fail.get("recovered") is True and labels[str(fail.get("label"))] < 2:
            continue
        key = re.sub(r"(?<!HTTP )\b\d+", "N", str(fail.get("error") or ""))
        groups.setdefault(key, []).append(fail)
    for items in groups.values():
        # The window is the first fail only, so a friction note about another matter hours later answers nothing.
        start = iso_ns(items[0].get("time")) or fallback_time
        label = program(str(items[0].get("label") or "?"))
        detail = f"{label} x{len(items)}" if len(items) > 1 else label
        found.append(Anomaly(f"{prefix}-fail-{hms(start)}", "fail", start, start, sid, detail, count=len(items)))
    for loop in report.get("loops") or []:
        # The same call 3 or more times in a row, such as polling: time lost, so idle.
        start = iso_ns(loop.get("first")) or fallback_time
        end = iso_ns(loop.get("last")) or start
        detail = f"{program(str(loop.get('label') or '?'))} x{loop.get('count')} (polling)"
        found.append(Anomaly(f"{prefix}-idle-{hms(start)}", "idle", start, end, sid, detail))
    used: set[int] = set()  # the parks with an unknown merge time that a gap already stands for
    for gap in report.get("gaps") or []:
        start, end = iso_ns(gap.get("start")), iso_ns(gap.get("end"))
        if not start or not end:
            continue
        if gap.get("after_tool_use") is True and gap.get("cause") != "permission":
            continue  # One long tool call, such as a test run: the native path counts it as activity, not idle.
        left = subtract([(start, end)], waits)
        if max((b - a for a, b in left), default=0) <= GAP_ANOMALY:
            continue
        if gap.get("cause") == "permission":
            detail = f"{fmt_duration(end - start)} idle (permission wait)"
            found.append(Anomaly(f"{prefix}-gap-{hms(start)}", "idle", start, end, sid, detail))
            continue
        unknown = next((p for p, merged in merges or [] if merged is None and p <= start and p not in used), None)
        if unknown is not None:
            # The first gap after a park whose merge time is unknown (offline, gh failed, or not merged) may be the
            # wait on that merge: it stays unexplained, so the merge time is never guessed.
            used.add(unknown)
            found.append(
                Anomaly(f"{prefix}-gap-{hms(start)}", "idle", start, end, sid, f"{fmt_duration(end - start)} idle")
            )
            continue
        cause, words = gap_cause(gap, start, merges or [])
        if cause.startswith("wait on router"):
            # A chained wait: the router was itself waiting on Marcus at the same time, so the worker waited on him.
            peer = str(gap.get("peer_id") or next(iter(report.get("peers") or []), ""))
            hit = next((w for w in marcus_waits(peer) if w[0] < end and start < w[1]), None) if peer else None
            if hit is not None:
                cause, words = f"wait on Marcus: {hit[2]}, via router", ""
        kind, detail = ("wait", cause) if cause else ("idle", f"{fmt_duration(end - start)} idle")
        found.append(Anomaly(f"{prefix}-gap-{hms(start)}", kind, start, end, sid, detail, cause=cause, words=words))
    seen: dict[str, int] = {}
    for anomaly in found:
        seen[anomaly.ref] = seen.get(anomaly.ref, 0) + 1
        if seen[anomaly.ref] > 1:
            anomaly.ref = f"{anomaly.ref}-{seen[anomaly.ref]}"
    return found


def transcript_files(sid: str) -> tuple[str, list[Path]]:
    """The tool and the transcript files of a session: Claude Code first, then Codex."""
    if not SESSION_NAME.match(sid):
        return "session", []
    claude_root = Path(os.environ.get("AGENT_TRACE_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")
    files = sorted(claude_root.glob(f"*/{sid}.jsonl"))
    if files:
        return "claude", files
    codex_root = Path(os.environ.get("AGENT_TRACE_CODEX_SESSIONS") or Path.home() / ".codex" / "sessions")
    return "codex", sorted(codex_root.glob(f"**/rollout-*{sid}.jsonl"))


def transcript_window(sid: str) -> tuple[str, Interval] | None:
    """The tool and the (first, last) event time of a session's transcripts, or None when there are none."""
    tool, files = transcript_files(sid)
    times: list[int] = []
    for path in files:
        try:
            with path.open(errors="replace") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    when = iso_ns(record.get("timestamp")) if isinstance(record, dict) else None
                    if when:
                        times.append(when)
        except OSError:
            continue
    return (tool, (min(times), max(times))) if times else None


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


def gantt_lines(
    label: str,
    spans: list[AgentSpan],
    sessions: list[SessionData],
    t0: int,
    t1: int,
    activity: list[Interval],
    waits_all: list[Interval],
    width: int,
    limit: int | None = None,
) -> list[str]:
    """The bar chart: one row per agent span and per session with native spans, then the axis.

    With `limit`, only the first `limit` rows print, then one line that names the rest; `--gantt` prints them all.
    """
    layout = build_layout(t0, t1, activity, width)

    def span_interval(span: AgentSpan) -> Interval:
        return span.start, max(span.start, span.end if span.end is not None else t1)

    rows: list[Row] = []
    by_ident = {(span.scope, span.ident): span for span in spans}
    for span in spans:
        parent = by_ident.get((span.scope, span.parent)) if span.parent else None
        if parent is not None and parent is not span and span not in parent.children:
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
    hidden = len(rows) - limit if limit is not None and len(rows) > limit else 0
    rows = rows[: len(rows) - hidden]
    name_width = min(NAME_LIMIT, max(len(row.name) for row in rows))
    out = []
    for row in rows:
        name = truncate(row.name, name_width)
        line = f"{name:<{name_width}} |{render_bar(row, layout)}| {fmt_duration(row.duration):>5}"
        out.append(line + (f" {row.status}" if row.status else ""))
    axis = axis_lines(layout, t0, t1, len(layout.columns))
    out.append(" " * (name_width + 2) + axis[0])
    return out + axis[1:] + ([f"… {hidden} more rows (--gantt)"] if hidden else [])


def reserved_lines(reserved: list[Anomaly]) -> list[str]:
    """The RESERVED list: the waits that a reserved rule causes, with their count, wall time, and rule.

    The data does not name which merge rule parked a PR, so the rule is "merge rule".
    """
    if not reserved:
        return []
    cost = measure([(a.start, a.end) for a in reserved])
    by_words = sum(1 for a in reserved if a.cause.endswith("(by words)"))
    rule = "merge rule" + (f" ({by_words} by words)" if by_words else "")
    return ["RESERVED", f"  {'merge':<8} {len(reserved)}×  {fmt_duration(cost)}  {rule}"]


def gap_lines(
    anomalies: list[Anomaly],
    notes: list[dict[str, Any]],
    friction: list[dict[str, Any]],
    reserved: list[Anomaly] | None = None,
) -> list[str]:
    """The GAPS list: each anomaly and friction note, grouped by kind and key, most costly first.

    An anomaly that `note none` answers is no gap. An anomaly that a friction note answers (by ref, or by time as
    Reconcile does) moves into that friction's group, which takes its count of notes and the anomaly's cost.
    A group's cost is the wall time that its anomalies cover, so idle gaps of parallel sessions count once.
    A reserved wait that no note answers is no GAPS line: it is added to `reserved`, for the RESERVED list.
    """
    by_ref: dict[str, dict[str, Any]] = {}
    for record in sorted(notes, key=time_of):
        for ref in attrs_of(record).get("agent_trace.refs") or []:
            if isinstance(ref, str):
                by_ref.setdefault(ref, record)

    def friction_key(record: dict[str, Any]) -> str:
        attrs = attrs_of(record)
        return f"{attrs.get('agent_trace.category')}: " + " ".join(str(attrs.get("agent_trace.fix")).lower().split())

    groups: dict[tuple[str, str], list[Any]] = {}  # (kind, key) -> [count, cost intervals, text]
    for record in sorted(friction, key=time_of):
        attrs = attrs_of(record)
        text = f"{attrs.get('agent_trace.category')}: {attrs.get('agent_trace.what')} → {attrs.get('agent_trace.fix')}"
        group = groups.setdefault(("friction", friction_key(record)), [0, [], text, []])
        group[0] += 1
    for anomaly in anomalies:
        record = by_ref.get(anomaly.ref) or next(
            (
                r
                for r in friction
                if session_of(r) == anomaly.session
                and anomaly.start - NOTE_BEFORE <= time_of(r) <= anomaly.end + NOTE_AFTER
            ),
            None,
        )
        cost = [(anomaly.start, anomaly.end)] if anomaly.cost else []
        if record is not None and attrs_of(record).get("agent_trace.note_kind") != "friction":
            continue  # `note none`: no gap.
        if record is not None:
            groups[("friction", friction_key(record))][1].extend(cost)
            continue
        if reserved is not None and is_reserved(anomaly):
            reserved.append(anomaly)
            continue
        text = anomaly.key
        group = groups.setdefault((anomaly.kind, anomaly.key), [0, [], text, []])
        group[0] += anomaly.count
        group[1].extend(cost)
        if anomaly.words and anomaly.words not in group[3]:
            group[3].append(anomaly.words)
    for group in groups.values():
        group[1] = measure(group[1])
        if group[3]:
            # The words that matched, or the session that the wait ended on: at most two, so Marcus can judge them.
            group[2] += ", " + "; ".join(group[3][:2]) + (" …" if len(group[3]) > 2 else "")
    for (kind, key), group in groups.items():
        target = fix_target(key) if kind == "wait" else ""
        if target:
            group[2] += f" → {target}"
    ranked = sorted(groups.items(), key=lambda item: (-item[1][1], -item[1][0], item[0][0], item[1][2]))
    out = [
        f"  {kind:<8} {count}×  {fmt_duration(cost) if cost else '–'}  {text}"
        for (kind, _), (count, cost, text, _) in ranked[:GAP_ROWS]
    ]
    if len(ranked) > GAP_ROWS:
        out.append(f"  … {len(ranked) - GAP_ROWS} more")
    return out or ["  none"]


def park_merges(spans: list[AgentSpan], prs: list[dict[str, Any]], offline: bool) -> dict[str, list[Merge]]:
    """The (park, merge) times of each session's parked PRs, found by the SHA in the park note.

    Online, the merge time is GitHub `mergedAt` of the run's PR that has that commit: the hook records each merge
    attempt, also one that failed, so only GitHub proves a merge. Offline, it is the time of the hook record of the
    merge, but only of a record with no stderr text, which a failed `gh pr merge` writes. Otherwise the merge time is
    unknown (None): offline, when a gh call failed, or when the PR has not merged. Online, a park whose SHA is in no
    PR of the run is left out.
    """
    urls = list(dict.fromkeys(str(attrs_of(r).get("agent_trace.pr_url") or "") for r in prs))
    found: dict[str, list[Merge]] = {}
    for span in spans:
        sha = re.search(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", span.note)
        if span.status != "parked" or span.end is None or not span.session or sha is None:
            continue
        merged = None
        if offline:
            merged = next(
                (
                    time_of(r)
                    for r in prs
                    if attrs_of(r).get("agent_trace.pr_action") == "merge"
                    and str(attrs_of(r).get("agent_trace.head_sha") or "").startswith(sha.group(0))
                    and not attrs_of(r).get("agent_trace.stderr")
                ),
                None,
            )
        known = merged is not None
        failed = False  # a gh call failed, so the PR of this park may be among the PRs it did not answer for
        if not known and not offline:
            for url in (u for u in urls if u.startswith("https://github.com/")):
                answer = gh_view(url)
                failed = failed or not answer.startswith("{")
                data = json.loads(answer) if answer.startswith("{") else {}
                commits = data.get("commits")
                oids = (
                    [str(c.get("oid") or "") for c in commits if isinstance(c, dict)]
                    if isinstance(commits, list)
                    else []
                )
                if any(oid.startswith(sha.group(0)) for oid in oids):
                    merged, known = iso_ns(data.get("mergedAt")), True
                    break
        if known or offline or failed:
            found.setdefault(span.session, []).append((span.end, merged))
    return found


def run(args: argparse.Namespace) -> int:
    if not args.ticket and not args.session:
        print("agent-trace: show needs --work or --session", file=sys.stderr)
        return 2
    base = Path(args.dir).expanduser() if args.dir else store.state_dir()
    width = max(10, int(args.width))
    wanted = list(args.session)
    bound = [s for s in store.sessions_bound_to(base, args.ticket) if s not in wanted] if args.ticket else []
    selection = select(dedupe(store.read_all(base)), args.ticket, wanted, bound)
    if not selection.agent and not selection.native:
        what = f"work ID {args.ticket}" if args.ticket else "session " + ", ".join(args.session)
        print(f"agent-trace: no spans for {what}", file=sys.stderr)
        return 1

    if getattr(args, "timeline", False):
        out = []
        for sid in selection.sessions:
            out += [*transcript_fallback(sid), ""]
        print("\n".join(out).rstrip("\n"))
        return 0

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

    scope = args.ticket or selection.sessions[0] if (args.ticket or selection.sessions) else "run"
    label = f"run {args.ticket}" if args.ticket else f"run {selection.sessions[0][:8]}"

    span_windows: dict[str, Interval] = {}
    for sid in selection.sessions:
        own = [
            (int(r.get("start") or 0), int(r.get("end") or 0))
            for r in [*selection.claude.get(sid, []), *selection.codex.get(sid, [])]
            if r.get("type") == "span"
        ]
        own += [span_interval(span) for span in spans if span.session == sid]
        edges = [t for interval in own for t in interval if t > 0]
        if edges:
            span_windows[sid] = (min(edges), max(edges))
    loose = [span_interval(span) for span in spans if span.session not in span_windows]
    transcripts = {sid: transcript_window(sid) for sid in selection.sessions}
    found = [found[1] for found in transcripts.values() if found]
    missing = sum(1 for found in transcripts.values() if not found)
    wall: Interval | None = None
    if found:
        wall = (min(start for start, _ in found), max(end for _, end in found))
        covered = measure(
            [
                (max(start, wall[0]), min(end, wall[1]))
                for start, end in [*span_windows.values(), *loose]
                if min(end, wall[1]) > max(start, wall[0])
            ]
        )
        share = round(100 * covered / max(1, wall[1] - wall[0]))
        wall_line = f"wall {fmt_duration(wall[1] - wall[0])} ({stamp(wall[0])} → {stamp(wall[1])})"
        wall_line += f" · span coverage {fmt_duration(covered)} ({share}%)"
        if missing:
            wall_line += f" · no transcript for {missing} of {len(transcripts)} sessions"
    else:
        wall_line = f"wall unknown (no transcript found for {missing} of {len(transcripts)} sessions)"

    if getattr(args, "gantt", False):
        errors = sum(len(d.errors) for d in sessions) + sum(1 for s in spans if s.status == "error")
        retries = sum(len(d.retries) for d in sessions) + sum(1 for s in spans if s.retry)
        open_spans = sum(1 for s in spans if s.end is None)
        active = measure(subtract(turn_time, waits_all))
        out = ["```text", *gantt_lines(label, spans, sessions, t0, t1, activity, waits_all, width), wall_line]
        out.append(
            f"spans {fmt_duration(t1 - t0)} · active {fmt_duration(active)}"
            f" · wait on Marcus {fmt_duration(measure(waits_all))}"
            f" · errors {errors} · retries {retries} · open spans {open_spans}"
        )
        out.append("```")
        print("\n".join(out))
        return post_run(args, scope, label, t0, t1, spans, notes, prs, selection)

    friction = [r for r in notes if attrs_of(r).get("agent_trace.note_kind") == "friction"]
    anomalies: list[Anomaly] = [a for d in sessions for a in (*d.errors, *d.blocks) if not a.recovered]
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
            anomalies.append(Anomaly(f"gap-{after[1]}", "idle", gap_start, gap_end, after[2], detail))
    wait_intervals = [span_interval(span) for span in wait_spans]
    for span in wait_spans:
        ask = str(span.attrs.get("agent_trace.ask") or "")
        if ask:
            # An ask span: neo waits on Marcus or the router. Its cause is known, so it is a wait, not idle.
            start, end = span_interval(span)
            cause = f"wait on Marcus: {ask}"
            anomalies.append(Anomaly(span.span_id, "wait", start, end, span.session, cause, cause=cause))
    merges = park_merges(spans, prs, args.offline) if any(span.status == "parked" for span in spans) else {}
    for sid in selection.sessions:
        if not selection.claude.get(sid) and not selection.codex.get(sid):
            anomalies += transcript_anomalies(sid, wait_intervals, t0, merges.get(sid, []))
    answered_refs = {
        str(ref) for r in notes for ref in (attrs_of(r).get("agent_trace.refs") or []) if isinstance(ref, str)
    }
    unanswered = []
    for anomaly in sorted(anomalies, key=lambda a: (a.start, a.ref)):
        if anomaly.ref in answered_refs or anomaly.kind == "wait":
            continue
        near = any(
            session_of(r) == anomaly.session and anomaly.start - NOTE_BEFORE <= time_of(r) <= anomaly.end + NOTE_AFTER
            for r in friction
        )
        if not near:
            unanswered.append(anomaly)

    pr_text, states = pr_lines(prs, args.offline) if prs else ([], [])
    counts = {state: states.count(state) for state in dict.fromkeys(states)}
    pr_summary = f"PRs {len(pr_text)}" + (
        " (" + ", ".join(f"{state} {n}" for state, n in counts.items()) + ")" if counts else ""
    )
    w0, w1 = wall or (t0, t1)
    name = args.ticket or selection.sessions[0][:8]
    header = f"{name}  {stamp(w0)} → {stamp(w1)} ({fmt_duration(w1 - w0)})  sessions {len(selection.sessions)}"
    blocks = sum(a.count for a in anomalies if a.kind == "block")
    # All waits count here, reserved ones too: parallel sessions count once.
    reserved: list[Anomaly] = []
    gaps = gap_lines(anomalies, notes, friction, reserved)
    waited = measure([(a.start, a.end) for a in anomalies if a.kind == "wait"])
    held = measure([(a.start, a.end) for a in reserved])
    fails = sum(a.count for a in anomalies if a.kind == "fail")
    idle = measure([(a.start, a.end) for a in unanswered if a.kind == "idle"])  # parallel sessions count once
    out = [
        "```text",
        f"{header}  {pr_summary}",
        f"autonomy  blocks {blocks}  fails {fails}  unexplained idle {fmt_duration(idle)}  friction {len(friction)}"
        + (f"  waits {fmt_duration(waited)} (reserved {fmt_duration(held)})" if waited else ""),
        wall_line,
        "GAPS (cost = wait time)",
        *gaps,
        *reserved_lines(reserved),
        "RUN SHAPE",
        *gantt_lines(label, spans, sessions, t0, t1, activity, waits_all, width, limit=SHAPE_ROWS),
        "SESSIONS",
    ]
    tools = {data.sid: data.tool for data in sessions}

    def first_seen(sid: str) -> int:
        found = transcripts[sid]
        starts = [found[1][0]] if found else []
        starts += [span_windows[sid][0]] if sid in span_windows else []
        return min(starts, default=0)

    ordered = sorted(selection.sessions, key=first_seen)
    for sid in ordered[:SESSION_ROWS]:
        found = transcripts[sid]
        tool = tools.get(sid) or (found[0] if found else "session")
        parts = [f"{tool} {sid[:8]}", f"transcript {window(*found[1])}" if found else "no transcript"]
        parts.append(f"spans {window(*span_windows[sid])}" if sid in span_windows else "no spans")
        out.append("  " + "  ".join(parts))
    if len(ordered) > SESSION_ROWS:
        out.append(f"  … {len(ordered) - SESSION_ROWS} more sessions")
    out += ["more: --timeline (transcript events of each session) | --gantt (the whole chart alone)", "```", ""]

    if unanswered:
        out.append("Reconcile:")
        out += [f"  {a.ref}  {utc(a.start)}  {a.kind}  {a.detail}" for a in unanswered]
        ticket_flag = f" --work {args.ticket}" if args.ticket else ""
        out += [
            "Answer each with one of:",
            f'  agent-trace note friction --category <category> --what "<what>" --fix "<fix>" --ref <ref>{ticket_flag}',
            f"  agent-trace note none --ref <ref> [--ref <ref> ...]{ticket_flag}",
        ]
    else:
        out.append("Reconcile: none")

    if pr_text:
        out += ["", "PRs:", *pr_text]
    parks = [span for span in spans if span.status == "parked"]
    if parks:
        out += ["", "Parks:", *[f"  {span.ident}  {span.note}".rstrip() for span in parks]]
    print("\n".join(out))
    return post_run(args, scope, label, t0, t1, spans, notes, prs, selection)


def post_run(
    args: argparse.Namespace,
    scope: str,
    label: str,
    t0: int,
    t1: int,
    spans: list[AgentSpan],
    notes: list[dict[str, Any]],
    prs: list[dict[str, Any]],
    selection: Selection,
) -> int:
    """Post the joined run to Jaeger when --jaeger asks for it. Exit 0: a failed post is only a warning."""
    if args.jaeger:
        native = [r for r in selection.native if r.get("type") == "span"]
        body, count, trace = jaeger_request(str(scope), label, t0, t1, spans, [*notes, *prs], native)
        try:
            post_jaeger(args.jaeger, body)
            print(f"jaeger: posted {count} spans, trace {trace}")
        except (OSError, ValueError) as error:
            print(f"agent-trace: warning: jaeger post failed: {error}", file=sys.stderr)
    return 0
