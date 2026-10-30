# /// script
# requires-python = ">=3.11"
# dependencies = ["opentelemetry-proto==1.45.2"]
# ///
"""`agent-trace collect`: a local OTLP/HTTP receiver that stores a filtered copy of agent telemetry.

`bin/agent-trace collect` runs this file with `uv run --script`, so the pinned `opentelemetry-proto` package decodes
protobuf requests. `--ensure` stays in the standard library (ensure.py).

Endpoints (gzip Content-Encoding is accepted):
  POST /v1/traces, POST /v1/logs  -> 200. The body is OTLP protobuf (`application/x-protobuf`, as the OpenTelemetry
                                     SDK exporters send) or OTLP JSON (as Claude Code and Codex send). Any other
                                     Content-Type -> 415. A body that does not decode -> 400.
  GET /health                     -> 200 `{"agent_trace": "collect"}`.
Every answer carries `X-Agent-Trace: collect`, so emitters can tell collect from another receiver such as Jaeger.

Filter: keep services `claude-code`, `agent-trace`, and any `codex*`; drop the rest. For Codex, keep only the spans
in CODEX_SPANS and the logs whose `event.name` is in CODEX_LOGS, drop the log attribute `output` (full command
output), and cut `arguments` to 200 characters.

Kept records are appended, one flat JSON line each, to `<spans dir>/<UTC receive day>.jsonl`. With --forward (or
AGENT_TRACE_FORWARD), kept native records (not `agent-trace` ones) are also re-encoded and POSTed to that OTLP base
URL in a background thread; errors there are ignored.
Both encodings go through the same flatten, allowlist, and store path: a protobuf request is converted with
MessageToDict, and its base64 ids are turned into hex, before the OTLP JSON decoder sees it.
"""

from __future__ import annotations

import argparse
import errno
import gzip
import importlib
import json
import logging
import os
import signal
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path[0] = str(Path(__file__).resolve().parent.parent)

from google.protobuf.json_format import MessageToDict  # noqa: E402
from google.protobuf.message import DecodeError  # noqa: E402
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest  # noqa: E402
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest  # noqa: E402

# ty checks a PEP 723 script against its own dependencies only, so it cannot see this package. Import the local
# standard-library modules by name instead.
otlp = importlib.import_module("agent_trace.otlp")
store = importlib.import_module("agent_trace.store")
ensure = importlib.import_module("agent_trace.ensure")
HEADER = ensure.HEADER
in_use_message = ensure.in_use_message

CODEX_SPANS = {"run_turn", "session_task.turn", "handle_tool_call", "exec_command", "run_sampling_request"}
CODEX_LOGS = {"codex.tool_result", "codex.tool_decision"}
ARGUMENTS_LIMIT = 200
MAX_BODY = 64 * 1024 * 1024
PROTOBUF_TYPES = ("application/x-protobuf", "application/protobuf")


def keep(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return the record to store (possibly trimmed), or None to drop it."""
    service = record.get("service") or ""
    if service in ("claude-code", "agent-trace"):
        return record
    if not service.startswith("codex"):
        return None
    if record["type"] == "span":
        return record if record.get("name") in CODEX_SPANS else None
    attrs = dict(record.get("attrs") or {})
    if attrs.get("event.name") not in CODEX_LOGS:
        return None
    attrs.pop("output", None)
    if isinstance(attrs.get("arguments"), str):
        attrs["arguments"] = attrs["arguments"][:ARGUMENTS_LIMIT]
    return {**record, "attrs": attrs}


class Collector:
    def __init__(self, spans_dir: Path, forward: str | None) -> None:
        self.spans_dir = spans_dir
        self.forward = forward.rstrip("/") if forward else None

    def accept(self, kind: str, doc: Any) -> None:
        decoded = otlp.decode_traces(doc) if kind == "traces" else otlp.decode_logs(doc)
        kept = [record for record in map(keep, decoded) if record is not None]
        store.append_records(store.day_file(self.spans_dir, otlp.now_ns()), kept)
        native = [record for record in kept if record.get("service") != "agent-trace"]
        if self.forward and native:
            body = otlp.encode_traces(native) if kind == "traces" else otlp.encode_logs(native)
            threading.Thread(target=self._forward, args=(f"{self.forward}/v1/{kind}", body), daemon=True).start()

    @staticmethod
    def _forward(url: str, body: dict[str, Any]) -> None:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=2) as response:
                response.read()
        except Exception:  # noqa: BLE001 (forwarding is best effort)
            pass


def decode_protobuf(kind: str, raw: bytes) -> dict[str, Any]:
    """Decode an OTLP protobuf request into the OTLP JSON shape (hex ids) that otlp.decode_* reads."""
    message = ExportTraceServiceRequest() if kind == "traces" else ExportLogsServiceRequest()
    message.ParseFromString(raw)
    return otlp.ids_to_hex(MessageToDict(message))


def make_handler(collector: Collector) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent-trace-collect"

        def reply(self, code: int, body: dict[str, Any], *, protobuf: bool = False) -> None:
            # A protobuf caller gets an empty Export*ServiceResponse, which encodes to zero bytes.
            data = b"" if protobuf else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/x-protobuf" if protobuf else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header(HEADER, "collect")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path.split("?")[0] == "/health":
                self.reply(200, {"agent_trace": "collect"})
            else:
                self.reply(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?")[0]
            kind = {"/v1/traces": "traces", "/v1/logs": "logs"}.get(path)
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                self.reply(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length)
            if kind is None:
                self.reply(404, {"error": "not found"})
                return
            content_type = (self.headers.get("Content-Type") or "").lower()
            protobuf = any(name in content_type for name in PROTOBUF_TYPES)
            if not protobuf and "json" not in content_type:
                self.reply(415, {"error": "send OTLP protobuf or OTLP JSON"})
                return
            try:
                if "gzip" in (self.headers.get("Content-Encoding") or "").lower():
                    raw = gzip.decompress(raw)
                doc = decode_protobuf(kind, raw) if protobuf else json.loads(raw)
            except (OSError, EOFError, ValueError, DecodeError):
                self.reply(400, {"error": "the body does not decode"}, protobuf=protobuf)
                return
            if not isinstance(doc, dict):
                self.reply(400, {"error": "expected a JSON object"})
                return
            try:
                collector.accept(kind, doc)
            except OSError as error:
                self.reply(500, {"error": f"could not store: {error}"}, protobuf=protobuf)
                return
            self.reply(200, {}, protobuf=protobuf)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (http.server API)
            pass

    return Handler


class Server(ThreadingHTTPServer):
    # Without SO_REUSEADDR, binding 127.0.0.1 fails while another receiver (such as Jaeger) holds the wildcard
    # address on the same port, instead of silently taking its local traffic.
    allow_reuse_address = False
    daemon_threads = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-trace collect")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--dir")
    parser.add_argument("--forward")
    args = parser.parse_args(argv)
    logging.getLogger("google").disabled = True
    spans_dir = (Path(args.dir).expanduser() if args.dir else store.state_dir() / "spans").absolute()
    forward = args.forward or os.environ.get("AGENT_TRACE_FORWARD") or None
    try:
        server = Server((args.host, args.port), make_handler(Collector(spans_dir, forward)))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(in_use_message(args.port), file=sys.stderr)
        else:
            print(f"agent-trace collect: cannot listen on {args.host}:{args.port}: {error}", file=sys.stderr)
        return 1
    print(f"agent-trace collect: listening on http://{args.host}:{args.port}, writing {spans_dir}", file=sys.stderr)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
