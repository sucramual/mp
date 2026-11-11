"""Command-line parsing for agent-trace.

Each subcommand module is imported only when it runs, so `agent-trace hook` starts fast. The hook path skips
argparse entirely and never raises.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-trace", description="Record agent run spans and show a joined timeline."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="run the local OTLP/HTTP JSON receiver")
    collect.add_argument("--port", type=int, default=4318)
    collect.add_argument("--host", default="127.0.0.1")
    collect.add_argument("--dir", help="spans directory (default: $AGENT_TRACE_DIR/spans)")
    collect.add_argument("--forward", help="also POST kept native records to this OTLP base URL")
    collect.add_argument("--ensure", action="store_true", help="start a detached collect unless one answers")

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--work",
            dest="ticket",
            help="work ID: a ticket ID such as ABC-123, or a chain ID such as CH-2 "
            "(default: $AGENT_TRACE_WORK or the session binding)",
        )

    span = commands.add_parser("span", help="mark the start or end of an agent span")
    span_commands = span.add_subparsers(dest="action", required=True)
    start = span_commands.add_parser("start")
    start.add_argument("--id", required=True)
    start.add_argument("--name", required=True)
    start.add_argument("--kind", required=True)
    start.add_argument("--parent")
    start.add_argument(
        "--ask", help="for --kind wait: what the wait asks Marcus or the router for (merge|scope|access|info)"
    )
    common(start)
    end = span_commands.add_parser("end")
    end.add_argument("--id", required=True)
    end.add_argument("--status", required=True)
    end.add_argument("--note")
    common(end)

    note = commands.add_parser("note", help="record friction, or answer an anomaly with no friction")
    note_commands = note.add_subparsers(dest="action", required=True)
    friction = note_commands.add_parser("friction")
    friction.add_argument("--category", required=True)
    friction.add_argument("--what", required=True)
    friction.add_argument("--fix", required=True)
    friction.add_argument("--ref", action="append", default=[])
    common(friction)
    none = note_commands.add_parser("none")
    none.add_argument("--ref", action="append", required=True)
    common(none)

    commands.add_parser("hook", help="PostToolUse hook: record gh pr create and gh pr merge (reads JSON on stdin)")
    commands.add_parser("gate", help="PreToolUse gate: block edits and gh pr create in a /neo session with no work ID")

    show = commands.add_parser("show", help="print the joined timeline of a work ID or sessions")
    show.add_argument("--work", dest="ticket", help="work ID")
    show.add_argument("--session", action="append", default=[])
    show.add_argument("--width", type=int, default=60)
    show.add_argument("--jaeger", help="also POST the joined trace to this OTLP base URL")
    show.add_argument("--offline", action="store_true", help="do not ask GitHub about PRs")
    show.add_argument("--dir", help="state directory (default: $AGENT_TRACE_DIR)")
    view = show.add_mutually_exclusive_group()
    view.add_argument("--gantt", action="store_true", help="print the bar chart of spans instead of the gaps view")
    view.add_argument("--timeline", action="store_true", help="print the transcript timeline of each session instead")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        try:
            from agent_trace import hook

            hook.main()
        except BaseException:  # noqa: BLE001 (the hook must never fail the agent's tool call)
            pass
        return 0
    if argv[:1] == ["gate"]:
        try:
            from agent_trace import gate

            return gate.main()
        except BaseException:  # noqa: BLE001 (the gate fails open, so a bug never blocks a PR)
            return 0
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        from agent_trace import collect as module
    elif args.command in ("span", "note"):
        from agent_trace import emit as module
    else:
        from agent_trace import show as module
    return module.run(args)
