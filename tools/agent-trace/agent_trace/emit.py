"""`agent-trace span start|end` and `agent-trace note friction|none`.

Every input is checked first. Any invalid value exits 2 with one line `agent-trace: <message>` on stderr, and
nothing is sent or written. A valid call builds one zero-length span record, POSTs it as OTLP JSON to
AGENT_TRACE_ENDPOINT/v1/traces (timeout 1 s), and prints nothing. The POST counts as delivered only when the answer
is 200 with the X-Agent-Trace header, which tells collect apart from another OTLP receiver such as Jaeger. Otherwise
the record goes to fallback.jsonl with one stderr warning, and the exit code stays 0.

Scope (the namespace of span ids) is the ticket, else the session, else the TRACEPARENT trace id.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

from agent_trace import otlp, store

TICKET = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
IDENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
REF = re.compile(r"^(gap-)?[0-9a-f]{16}$")
KINDS = ("phase", "pr", "wait", "infra", "check")
STATUSES = ("ok", "error", "parked")
CATEGORIES = ("permission", "doc", "flaky", "workaround", "missing-tool")
TEXT_LIMIT = 300
DEFAULT_ENDPOINT = "http://127.0.0.1:4318"


class Invalid(Exception):
    """An input error. The message is printed after `agent-trace: `."""


def check_choice(flag: str, value: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise Invalid(f"{flag} must be one of {', '.join(choices)} (got {value!r})")
    return value


def check_pattern(flag: str, value: str, pattern: re.Pattern[str]) -> str:
    if not pattern.match(value):
        raise Invalid(f"{flag} must match {pattern.pattern} (got {value!r})")
    return value


def check_text(flag: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise Invalid(f"{flag} must not contain a newline")
    value = value.strip()
    if not value:
        raise Invalid(f"{flag} must not be empty")
    if len(value) > TEXT_LIMIT:
        raise Invalid(f"{flag} must be at most {TEXT_LIMIT} characters (got {len(value)})")
    return value


def session_id() -> str | None:
    return os.environ.get("AGENT_TRACE_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def endpoint() -> str:
    return (os.environ.get("AGENT_TRACE_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


class Context:
    """The ids that every record of one call shares."""

    def __init__(self, ticket: str | None, session: str | None, traceparent: tuple[str, str] | None) -> None:
        self.ticket = ticket
        self.session = session
        self.traceparent = traceparent
        self.scope = ticket or session or (traceparent[0] if traceparent else None)

    @property
    def trace_id(self) -> str:
        return self.traceparent[0] if self.traceparent else otlp.trace_id_for(self.scope or "")

    def attrs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.session:
            out["session.id"] = self.session
        if self.ticket:
            out["run.ticket"] = self.ticket
        out["agent_trace.scope"] = self.scope
        return out


def resolve_context(flag_ticket: str | None, session: str | None, base: Path) -> tuple[Context, str | None]:
    """Return the context and the ticket to bind (a ticket given by flag or env), or raise Invalid."""
    given = None
    if flag_ticket is not None:
        given = check_pattern("--ticket", flag_ticket, TICKET)
    elif os.environ.get("AGENT_TRACE_TICKET"):
        given = check_pattern("AGENT_TRACE_TICKET", os.environ["AGENT_TRACE_TICKET"], TICKET)
    ticket = given
    if ticket is None:
        bound = store.read_ticket(base, session)
        ticket = bound if bound and TICKET.match(bound) else None
    context = Context(ticket, session, otlp.parse_traceparent(os.environ.get("TRACEPARENT")))
    if context.scope is None:
        raise Invalid("no scope: pass --ticket, or set AGENT_TRACE_TICKET, CLAUDE_CODE_SESSION_ID, or TRACEPARENT")
    return context, given


def span_record(
    context: Context,
    *,
    span_id: str,
    name: str,
    parent: str | None,
    attrs: dict[str, Any],
    status_code: int = 0,
    event: str | None = None,
) -> otlp.Record:
    now = otlp.now_ns()
    merged = {**context.attrs(), **attrs}
    return {
        "type": "span",
        "service": "agent-trace",
        "traceId": context.trace_id,
        "spanId": span_id,
        "parentSpanId": parent,
        "name": name,
        "start": now,
        "end": now,
        "status": {"code": status_code, "message": ""},
        "attrs": merged,
        "events": [{"name": event, "time": now, "attrs": {}}] if event else [],
    }


def post_json(url: str, body: dict[str, Any], timeout: float) -> tuple[int, dict[str, str]]:
    """POST JSON without proxies. Returns (status, headers). Raises OSError (including HTTPError) on failure."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        response.read()
        return response.status, {key.lower(): value for key, value in response.headers.items()}


def deliver(records: list[otlp.Record], base: Path, *, quiet: bool = False) -> None:
    """Send span records to collect, or append them to fallback.jsonl. Never raises for transport errors."""
    url = endpoint() + "/v1/traces"
    try:
        status, headers = post_json(url, otlp.encode_traces(records), timeout=1.0)
        if status == 200 and "x-agent-trace" in headers:
            return
    except (OSError, ValueError):
        pass
    fallback = base / "fallback.jsonl"
    try:
        store.append_records(fallback, records)
    except OSError as error:
        if not quiet:
            print(
                f"agent-trace: collect not reachable at {endpoint()}; could not write {fallback}: {error}",
                file=sys.stderr,
            )
        return
    if not quiet:
        print(f"agent-trace: collect not reachable at {endpoint()}; wrote {fallback}", file=sys.stderr)


def build(args: argparse.Namespace, base: Path) -> tuple[list[otlp.Record], Context, str | None]:
    session = session_id()
    if args.command == "span" and args.action == "start":
        ident = check_pattern("--id", args.id, IDENT)
        name = check_text("--name", args.name)
        kind = check_choice("--kind", args.kind, KINDS)
        parent = check_pattern("--parent", args.parent, IDENT) if args.parent is not None else None
        context, given = resolve_context(args.ticket, session, base)
        attrs: dict[str, Any] = {"agent_trace.phase": "start", "agent_trace.id": ident, "agent_trace.kind": kind}
        if parent:
            attrs["agent_trace.parent"] = parent
        parent_span = otlp.span_id_for(context.scope or "", parent) if parent else None
        if parent_span is None and context.traceparent:
            parent_span = context.traceparent[1]
        record = span_record(
            context, span_id=otlp.span_id_for(context.scope or "", ident), name=name, parent=parent_span, attrs=attrs
        )
        return [record], context, given
    if args.command == "span":
        ident = check_pattern("--id", args.id, IDENT)
        status = check_choice("--status", args.status, STATUSES)
        note = check_text("--note", args.note) if args.note is not None else None
        context, given = resolve_context(args.ticket, session, base)
        attrs = {"agent_trace.phase": "end", "agent_trace.id": ident, "agent_trace.status": status}
        if note:
            attrs["agent_trace.note"] = note
        record = span_record(
            context,
            span_id=otlp.span_id_for(context.scope or "", ident),
            name=ident,
            parent=context.traceparent[1] if context.traceparent else None,
            attrs=attrs,
            status_code=2 if status == "error" else 0,
        )
        return [record], context, given
    if args.action == "friction":
        category = check_choice("--category", args.category, CATEGORIES)
        what = check_text("--what", args.what)
        fix = check_text("--fix", args.fix)
        refs = [check_pattern("--ref", ref, REF) for ref in args.ref]
        context, given = resolve_context(args.ticket, session, base)
        attrs = {
            "agent_trace.note_kind": "friction",
            "agent_trace.category": category,
            "agent_trace.what": what,
            "agent_trace.fix": fix,
            "agent_trace.refs": refs,
        }
        event = "friction"
    else:
        refs = [check_pattern("--ref", ref, REF) for ref in args.ref]
        context, given = resolve_context(args.ticket, session, base)
        attrs = {"agent_trace.note_kind": "none", "agent_trace.refs": refs}
        event = "none"
    record = span_record(
        context,
        span_id=otlp.random_span_id(),
        name="agent_trace.note",
        parent=context.traceparent[1] if context.traceparent else None,
        attrs=attrs,
        event=event,
    )
    return [record], context, given


def run(args: argparse.Namespace) -> int:
    base = store.state_dir()
    try:
        records, context, given = build(args, base)
    except Invalid as error:
        print(f"agent-trace: {error}", file=sys.stderr)
        return 2
    if given and context.session:
        try:
            store.write_ticket(base, context.session, given)
        except OSError as error:
            print(f"agent-trace: could not bind the ticket to the session: {error}", file=sys.stderr)
    deliver(records, base)
    return 0
