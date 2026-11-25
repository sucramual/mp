"""State paths and JSONL files.

Layout under AGENT_TRACE_DIR (default ~/.local/state/agent-trace):

  spans/YYYY-MM-DD.jsonl   records that collect received, by UTC receive day
  fallback.jsonl           records that span, note, and hook wrote when collect did not answer
  sessions/<id>.ticket     the ticket bound to a session
  collect.log              output of a collect that `collect --ensure` started

Directories are mode 0700 and files 0600, because native spans hold the user's email address.

The readers also take the other machine's copy of this layout, which agent-runs-sync writes to
$AGENT_RUNS_DIR/remotes/<machine>/agent-trace (default ~/.local/state/agent-runs). Writers never touch a copy.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SESSION_FILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def state_dir() -> Path:
    value = os.environ.get("AGENT_TRACE_DIR")
    return Path(value).expanduser() if value else Path.home() / ".local" / "state" / "agent-trace"


def runs_dir() -> Path:
    value = os.environ.get("AGENT_RUNS_DIR")
    return Path(value).expanduser() if value else Path.home() / ".local" / "state" / "agent-runs"


def remote_dirs(name: str) -> list[Path]:
    """The folder `name` (such as agent-trace or claude-projects) in each machine copy of agent-runs-sync."""
    remotes = runs_dir() / "remotes"
    try:
        machines = sorted(path for path in remotes.iterdir() if path.is_dir())
    except OSError:
        return []
    return [machine / name for machine in machines if (machine / name).is_dir()]


def ensure_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def day_file(spans_dir: Path, when_ns: int) -> Path:
    day = datetime.fromtimestamp(when_ns / 1e9, tz=UTC).strftime("%Y-%m-%d")
    return spans_dir / f"{day}.jsonl"


def append_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Append one JSON line per record under an exclusive lock, so parallel writers never interleave lines."""
    if not records:
        return
    ensure_dir(path.parent)
    data = "".join(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n" for record in records)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, data.encode())
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object line of a file. Skips blank, partial, and non-object lines."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield value


def read_all(base: Path) -> list[dict[str, Any]]:
    """Every stored record: spans/*.jsonl in name order, then fallback.jsonl, here and then in each machine copy."""
    files = []
    for folder in [base, *remote_dirs("agent-trace")]:
        files += sorted((folder / "spans").glob("*.jsonl")) + [folder / "fallback.jsonl"]
    return [record for path in files for record in read_jsonl(path)]


def ticket_file(base: Path, session: str) -> Path | None:
    return base / "sessions" / f"{session}.ticket" if SESSION_FILE_ID.match(session) else None


def read_ticket(base: Path, session: str | None) -> str | None:
    path = ticket_file(base, session) if session else None
    try:
        return path.read_text().strip() or None if path else None
    except OSError:
        return None


def write_ticket(base: Path, session: str, ticket: str) -> None:
    path = ticket_file(base, session)
    if path is None or read_ticket(base, session) == ticket:
        return
    ensure_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (ticket + "\n").encode())
    finally:
        os.close(fd)


def sessions_bound_to(base: Path, ticket: str) -> list[str]:
    """The session ids whose sessions/<id>.ticket names this work ID, here or in a machine copy, in name order."""
    found: set[str] = set()
    for folder in [base, *remote_dirs("agent-trace")]:
        try:
            paths = sorted((folder / "sessions").glob("*.ticket"))
        except OSError:
            continue
        found.update(path.stem for path in paths if read_ticket(folder, path.stem) == ticket)
    return sorted(found)
