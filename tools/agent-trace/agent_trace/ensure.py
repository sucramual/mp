"""`agent-trace collect --ensure`: start one detached collect unless one already answers. Standard library only.

GET /health on the port. When the answer carries `X-Agent-Trace`, a collect runs: exit 0. Otherwise start
`bin/agent-trace collect` (which runs collect.py under uv) in a new session with its output in collect.log, and exit
0 once it answers /health, or exit 1 after 3 s. A port that another receiver such as Jaeger holds makes the new
collect exit 1, and this prints the port-in-use message.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from agent_trace import store

HEADER = "X-Agent-Trace"
TOOL_BIN = Path(__file__).resolve().parent.parent / "bin" / "agent-trace"
WAIT = 3.0


def in_use_message(port: int) -> str:
    return f"agent-trace collect: port {port} is in use (another OTLP receiver such as Jaeger?)"


def is_collect(host: str, port: int, timeout: float = 0.5) -> bool:
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/health"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200 and response.headers.get(HEADER) is not None
    except (OSError, ValueError):
        return False


def run(args: argparse.Namespace) -> int:
    if is_collect(args.host, args.port):
        return 0
    spans_dir = (Path(args.dir).expanduser() if args.dir else store.state_dir() / "spans").absolute()
    forward = args.forward or os.environ.get("AGENT_TRACE_FORWARD") or None
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
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if is_collect(args.host, args.port, timeout=0.2):
            return 0
        if child.poll() is not None:
            break
        time.sleep(0.05)
    if child.poll() == 1 and in_use_message(args.port) in log_path.read_text(errors="replace"):
        print(in_use_message(args.port), file=sys.stderr)
    else:
        print(
            f"agent-trace collect: collect did not answer on port {args.port} within 3 s; see {log_path}",
            file=sys.stderr,
        )
    return 1
