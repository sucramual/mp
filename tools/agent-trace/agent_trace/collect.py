"""`agent-trace collect`: a local OTLP/HTTP receiver that stores a filtered copy of agent telemetry.

Endpoints (JSON only; gzip Content-Encoding is accepted):
  POST /v1/traces, POST /v1/logs  -> 200 `{}`. Protobuf (no `json` in Content-Type) -> 415. Bad JSON -> 400.
  GET /health                     -> 200 `{"agent_trace": "collect"}`.
Every answer carries `X-Agent-Trace: collect`, so emitters can tell collect from another receiver such as Jaeger.

Filter: keep services `claude-code`, `agent-trace`, and any `codex*`; drop the rest. For Codex, keep only the spans
in CODEX_SPANS and the logs whose `event.name` is in CODEX_LOGS, drop the log attribute `output` (full command
output), and cut `arguments` to 200 characters.

Kept records are appended, one flat JSON line each, to `<spans dir>/<UTC receive day>.jsonl`. With --forward (or
AGENT_TRACE_FORWARD), kept native records (not `agent-trace` ones) are also re-encoded and POSTed to that OTLP base
URL in a background thread; errors there are ignored.

--ensure: when a collect already answers /health on the port, exit 0. Otherwise start a detached collect with the
same arguments (output to collect.log) and exit 0 once it answers, or exit 1 after 3 s.
"""

from __future__ import annotations

import argparse
import errno
import gzip
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent_trace import otlp, store

HEADER = "X-Agent-Trace"
CODEX_SPANS = {"run_turn", "session_task.turn", "handle_tool_call", "exec_command", "run_sampling_request"}
CODEX_LOGS = {"codex.tool_result", "codex.tool_decision"}
ARGUMENTS_LIMIT = 200
MAX_BODY = 64 * 1024 * 1024
TOOL_BIN = Path(__file__).resolve().parent.parent / "bin" / "agent-trace"


def keep(record: otlp.Record) -> otlp.Record | None:
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


def make_handler(collector: Collector) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent-trace-collect"

        def reply(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
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
            if "json" not in (self.headers.get("Content-Type") or "").lower():
                self.reply(415, {"error": "only OTLP JSON is supported"})
                return
            try:
                if "gzip" in (self.headers.get("Content-Encoding") or "").lower():
                    raw = gzip.decompress(raw)
                doc = json.loads(raw)
            except (OSError, EOFError, ValueError):
                self.reply(400, {"error": "bad JSON"})
                return
            if not isinstance(doc, dict):
                self.reply(400, {"error": "expected a JSON object"})
                return
            try:
                collector.accept(kind, doc)
            except OSError as error:
                self.reply(500, {"error": f"could not store: {error}"})
                return
            self.reply(200, {})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (http.server API)
            pass

    return Handler


class Server(ThreadingHTTPServer):
    # Without SO_REUSEADDR, binding 127.0.0.1 fails while another receiver (such as Jaeger) holds the wildcard
    # address on the same port, instead of silently taking its local traffic.
    allow_reuse_address = False
    daemon_threads = True


def is_collect(host: str, port: int, timeout: float = 0.5) -> bool:
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/health"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200 and response.headers.get(HEADER) is not None
    except (OSError, ValueError):
        return False


def in_use_message(port: int) -> str:
    return f"agent-trace collect: port {port} is in use (another OTLP receiver such as Jaeger?)"


def ensure(args: argparse.Namespace, spans_dir: Path, forward: str | None) -> int:
    if is_collect(args.host, args.port):
        return 0
    base = store.state_dir()
    store.ensure_dir(base)
    log_path = base / "collect.log"
    command = [sys.executable, str(TOOL_BIN), "collect", "--port", str(args.port), "--host", args.host]
    command += ["--dir", str(spans_dir)]
    if forward:
        command += ["--forward", forward]
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        child = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True, close_fds=True
        )
    finally:
        os.close(fd)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if is_collect(args.host, args.port, timeout=0.2):
            return 0
        if child.poll() is not None:
            break
        time.sleep(0.05)
    if child.poll() == 1:
        print(in_use_message(args.port), file=sys.stderr)
    else:
        print(
            f"agent-trace collect: collect did not answer on port {args.port} within 3 s; see {log_path}",
            file=sys.stderr,
        )
    return 1


def run(args: argparse.Namespace) -> int:
    spans_dir = Path(args.dir).expanduser() if args.dir else store.state_dir() / "spans"
    spans_dir = spans_dir.absolute()
    forward = args.forward or os.environ.get("AGENT_TRACE_FORWARD") or None
    if args.ensure:
        return ensure(args, spans_dir, forward)
    try:
        server = Server((args.host, args.port), make_handler(Collector(spans_dir, forward)))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(in_use_message(args.port), file=sys.stderr)
        else:
            print(f"agent-trace collect: cannot listen on {args.host}:{args.port}: {error}", file=sys.stderr)
        return 1
    print(f"agent-trace collect: listening on http://{args.host}:{args.port}, writing {spans_dir}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
