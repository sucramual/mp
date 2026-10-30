"""`agent-trace span start|end` and `agent-trace note friction|none`.

Every input is checked first. Any invalid value exits 2 with one line `agent-trace: <message>` on stderr, and
nothing is sent or written. All of that is standard library. A valid call then hands one zero-length span to the
OpenTelemetry SDK (launch.send runs export.py under `uv run --script`), which exports it to
AGENT_TRACE_ENDPOINT/v1/traces and prints nothing. A span that collect does not take (collect down, or another
receiver such as Jaeger, which sends no X-Agent-Trace header) goes to fallback.jsonl with one stderr warning, and
the exit code stays 0.

Scope (the namespace of span ids) is the ticket, else the session, else the TRACEPARENT trace id.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
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
TRACEPARENT_TRACE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


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
    for name in ("AGENT_TRACE_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
        if os.environ.get(name):
            return os.environ[name]
    return None


def endpoint() -> str:
    return (os.environ.get("AGENT_TRACE_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


class Context:
    """What every span of one call shares: ticket, session, and scope (the namespace of span ids)."""

    def __init__(self, ticket: str | None, session: str | None, traceparent_trace: str | None) -> None:
        self.ticket = ticket
        self.session = session
        self.scope = ticket or session or traceparent_trace

    def attrs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.session:
            out["session.id"] = self.session
        if self.ticket:
            out["run.ticket"] = self.ticket
        out["agent_trace.scope"] = self.scope
        return out

    def span_id(self, ident: str) -> str:
        return otlp.span_id_for(self.scope or "", ident)

    def request(self, specs: list[dict[str, Any]]) -> dict[str, Any]:
        """The send request for launch.send: one zero-length span per spec, all at this moment."""
        spans = [{**spec, "attrs": {**self.attrs(), **spec["attrs"]}} for spec in specs]
        return {
            "time": otlp.now_ns(),
            "trace_id": otlp.trace_id_for(self.scope or ""),
            "endpoint": endpoint(),
            "spans": spans,
        }


def traceparent_trace() -> str | None:
    """The trace id of TRACEPARENT, used only as the last scope. The SDK reads TRACEPARENT for the parent."""
    match = TRACEPARENT_TRACE.match((os.environ.get("TRACEPARENT") or "").strip().lower())
    return match.group(1) if match and set(match.group(1)) != {"0"} else None


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
    context = Context(ticket, session, traceparent_trace())
    if context.scope is None:
        raise Invalid(
            "no scope: pass --ticket, or set AGENT_TRACE_TICKET, CLAUDE_CODE_SESSION_ID, "
            "CODEX_THREAD_ID, or TRACEPARENT"
        )
    return context, given


def spec(
    name: str, attrs: dict[str, Any], *, span_id: str | None = None, parent: str | None = None, **extra: Any
) -> dict[str, Any]:
    """One span for export.py. ``span_id`` None means random; ``parent`` None means TRACEPARENT, if any."""
    return {"name": name, "span_id": span_id, "parent_span_id": parent, "attrs": attrs, **extra}


def build(args: argparse.Namespace, base: Path) -> tuple[dict[str, Any], Context, str | None]:
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
        one = spec(name, attrs, span_id=context.span_id(ident), parent=context.span_id(parent) if parent else None)
    elif args.command == "span":
        ident = check_pattern("--id", args.id, IDENT)
        status = check_choice("--status", args.status, STATUSES)
        note = check_text("--note", args.note) if args.note is not None else None
        context, given = resolve_context(args.ticket, session, base)
        attrs = {"agent_trace.phase": "end", "agent_trace.id": ident, "agent_trace.status": status}
        if note:
            attrs["agent_trace.note"] = note
        one = spec(ident, attrs, span_id=context.span_id(ident), error=status == "error")
    elif args.action == "friction":
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
        one = spec("agent_trace.note", attrs, event="friction")
    else:
        refs = [check_pattern("--ref", ref, REF) for ref in args.ref]
        context, given = resolve_context(args.ticket, session, base)
        attrs = {"agent_trace.note_kind": "none", "agent_trace.refs": refs}
        one = spec("agent_trace.note", attrs, event="none")
    return context.request([one]), context, given


def run(args: argparse.Namespace) -> int:
    base = store.state_dir()
    try:
        request, context, given = build(args, base)
    except Invalid as error:
        print(f"agent-trace: {error}", file=sys.stderr)
        return 2
    if given and context.session:
        try:
            store.write_ticket(base, context.session, given)
        except OSError as error:
            print(f"agent-trace: could not bind the ticket to the session: {error}", file=sys.stderr)
    from agent_trace import launch

    launch.send(request, base)
    return 0
