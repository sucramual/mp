"""Start the OpenTelemetry SDK side of agent-trace with `uv run --script`. Standard library only.

`span`, `note`, and `hook` validate in the standard library, then hand a small JSON send request to export.py on
stdin. export.py (PEP 723 script with the pinned SDK) builds the spans, exports them with the SDK's OTLP/HTTP
exporter, and writes fallback.jsonl itself when collect does not take them. It prints one JSON result line.

When uv is not on PATH, or export.py does not print a result, this module writes the fallback records itself:
trace id from the scope hash, no TRACEPARENT parent. Sending never fails the caller.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_trace import otlp, store

HERE = Path(__file__).resolve().parent
EXPORT = HERE / "export.py"
COLLECT = HERE / "collect.py"
EXPORT_TIMEOUT = 60  # A cold uv cache downloads the pinned packages first.


def uv_command(script: Path, *args: str) -> list[str] | None:
    uv = shutil.which("uv")
    return [uv, "run", "-q", "--script", str(script), *args] if uv else None


def fallback_records(request: dict[str, Any]) -> list[otlp.Record]:
    when = int(request["time"])
    return [
        {
            "type": "span",
            "service": "agent-trace",
            "traceId": request["trace_id"],
            "spanId": spec.get("span_id") or secrets.token_hex(8),
            "parentSpanId": spec.get("parent_span_id"),
            "name": spec["name"],
            "start": when,
            "end": when,
            "status": {"code": 2 if spec.get("error") else 0, "message": ""},
            "attrs": spec["attrs"],
            "events": [{"name": spec["event"], "time": when, "attrs": {}}] if spec.get("event") else [],
        }
        for spec in request["spans"]
    ]


def send(request: dict[str, Any], base: Path, *, quiet: bool = False) -> None:
    """Send one request through export.py, or write the fallback records here. Prints at most one warning."""
    fallback = base / "fallback.jsonl"
    request = {**request, "fallback": str(fallback)}
    command = uv_command(EXPORT)
    reason = "uv not found"
    if command:
        try:
            result = subprocess.run(
                command, input=json.dumps(request), capture_output=True, text=True, timeout=EXPORT_TIMEOUT
            )
            answer = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else None
        except (OSError, subprocess.SubprocessError, ValueError):
            answer = None
        if isinstance(answer, dict) and answer.get("sent"):
            return
        if isinstance(answer, dict) and answer.get("fallback"):
            if not quiet:
                print(f"agent-trace: collect not reachable at {request['endpoint']}; wrote {fallback}", file=sys.stderr)
            return
        reason = "export.py failed"
    try:
        store.append_records(fallback, fallback_records(request))
    except OSError as error:
        if not quiet:
            print(f"agent-trace: cannot send ({reason}) and cannot write {fallback}: {error}", file=sys.stderr)
        return
    if not quiet:
        print(f"agent-trace: cannot send ({reason}); wrote {fallback}", file=sys.stderr)


def exec_collect(args: list[str]) -> int:
    """Replace this process with collect.py under uv. Returns only when uv is missing or exec fails."""
    command = uv_command(COLLECT, *args)
    if command is None:
        print("agent-trace collect: uv not found on PATH; install uv (https://docs.astral.sh/uv/)", file=sys.stderr)
        return 1
    try:
        os.execv(command[0], command)
    except OSError as error:
        print(f"agent-trace collect: cannot start uv: {error}", file=sys.stderr)
    return 1
