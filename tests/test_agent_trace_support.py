"""Shared helpers for the agent-trace tests. This module holds no tests.

The tests run tools/agent-trace/bin/agent-trace as a subprocess. A recording HTTP server stands in for
collect (with the ``X-Agent-Trace`` header) or for another OTLP receiver such as Jaeger (without it).
"""

from __future__ import annotations

import gzip
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from conftest import REPO_ROOT

TOOL = REPO_ROOT / "tools" / "agent-trace" / "bin" / "agent-trace"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "agent_trace"
PYTHON = sys.executable


@dataclass
class Request:
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class Recorder:
    """A local HTTP server that records each POST and answers 200 ``{}``."""

    url: str
    port: int
    requests: list[Request] = field(default_factory=list)

    def spans(self) -> list[dict[str, Any]]:
        """Every OTLP span in the recorded trace requests, with ``service`` added from the resource."""
        out = []
        for request in self.requests:
            for resource_spans in request.body.get("resourceSpans", []):
                service = resource_attrs(resource_spans).get("service.name")
                for scope_spans in resource_spans.get("scopeSpans", []):
                    for span in scope_spans.get("spans", []):
                        out.append({**span, "service": service})
        return out

    def wait_for(self, count: int, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while len(self.requests) < count and time.monotonic() < deadline:
            time.sleep(0.02)


def resource_attrs(resource_block: dict[str, Any]) -> dict[str, Any]:
    return attrs_of(resource_block.get("resource", {}).get("attributes", []))


def any_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "arrayValue" in value:
        return [any_value(item) for item in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return attrs_of(value["kvlistValue"].get("values", []))
    return None


def attrs_of(attributes: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: any_value(item.get("value", {})) for item in attributes}


@contextmanager
def recorder(*, collect_header: bool = True) -> Iterator[Recorder]:
    """Start a recording server on a free port. With ``collect_header`` it answers like collect does."""
    state = Recorder(url="", port=0)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            state.requests.append(Request(self.path, dict(self.headers), json.loads(raw or b"null")))
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if collect_header:
                self.send_header("X-Agent-Trace", "collect")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.port = server.server_address[1]
    state.url = f"http://127.0.0.1:{state.port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def closed_port() -> int:
    """A local port that nothing listens on (bound once, then closed)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def base_env(env: dict[str, str], state_dir: Path, endpoint: str, **extra: str) -> dict[str, str]:
    """``env`` plus the agent-trace variables. TZ is UTC so clock times are stable."""
    return {**env, "AGENT_TRACE_DIR": str(state_dir), "AGENT_TRACE_ENDPOINT": endpoint, "TZ": "UTC", **extra}


def run(args: list[str], env: dict[str, str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([PYTHON, str(TOOL), *args], env=env, input=input, text=True, capture_output=True, timeout=60)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def health(port: int) -> tuple[int, dict[str, str], Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except OSError:
        return None


@contextmanager
def collect(env: dict[str, str], *args: str) -> Iterator[int]:
    """Run ``agent-trace collect`` on a free port until the block ends. Yields the port."""
    port = closed_port()
    process = subprocess.Popen(
        [PYTHON, str(TOOL), "collect", "--port", str(port), *args],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while health(port) is None:
            if process.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"collect did not start: {process.stderr.read() if process.stderr else ''}")
            time.sleep(0.05)
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stderr:
            process.stderr.close()


def post(port: int, path: str, body: bytes, content_type: str = "application/json", **headers: str) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": content_type, **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def kill_matching(pattern: str) -> None:
    """Kill every process whose command line contains ``pattern`` (a unique temp path)."""
    result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    for pid in result.stdout.split():
        try:
            os.kill(int(pid), 15)
        except (ProcessLookupError, ValueError):
            pass
