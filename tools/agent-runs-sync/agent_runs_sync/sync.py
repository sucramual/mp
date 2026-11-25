"""Copy agent run data between this machine and the devbox, so a retro on either machine sees both.

Each machine keeps a read-only copy of the other machine's run data under
$AGENT_RUNS_DIR/remotes/<name>/ (default ~/.local/state/agent-runs). Only the laptop can reach the devbox,
so the laptop runs this tool, pulls the devbox data, and pushes its own.

This file is also the remote half: the tool sends its own source over ssh and runs `list`, `pack`,
`mirror-list`, or `unpack` with the devbox's python3. So it uses only the standard library, and it must run
on Python 3.11.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

# A machine name is one plain folder name, because it becomes remotes/<name>/.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
DEFAULT_DAYS = 30
# One tar per batch, so a copy that the ssh time limit stops keeps every batch it finished.
DEFAULT_BATCH_MB = 32
Listing = dict[str, dict[str, list[int]]]


def roots(home: Path, env: dict[str, str]) -> dict[str, tuple[Path, list[str], bool]]:
    """Each copied root: name -> (folder, file globs, whether the day window applies)."""
    trace = Path(env["AGENT_TRACE_DIR"]).expanduser() if env.get("AGENT_TRACE_DIR") else None
    retro = Path(env["RETRO_DIR"]).expanduser() if env.get("RETRO_DIR") else None
    return {
        "claude-projects": (home / ".claude" / "projects", ["*/*.jsonl"], True),
        "codex-sessions": (home / ".codex" / "sessions", ["**/rollout-*.jsonl"], True),
        # Ticket bindings and reports are small and stay useful after the window, so they have no window.
        "agent-trace": (trace or home / ".local" / "state" / "agent-trace", ["spans/*.jsonl", "fallback.jsonl"], True),
        "agent-trace-sessions": (
            (trace or home / ".local" / "state" / "agent-trace") / "sessions",
            ["*.ticket"],
            False,
        ),
        "retro": (retro or home / "dotfiles" / ".retro", ["*.md"], False),
    }


# agent-trace-sessions is stored inside the agent-trace mirror, where agent-trace looks for it.
MIRROR_PATH = {"agent-trace-sessions": "agent-trace/sessions"}


def runs_dir(home: Path, env: dict[str, str]) -> Path:
    value = env.get("AGENT_RUNS_DIR")
    return Path(value).expanduser() if value else home / ".local" / "state" / "agent-runs"


def list_sources(days: int) -> Listing:
    """Every file in each root, as root -> relative path -> [size, mtime]."""
    cutoff = time.time() - days * 86400
    out: Listing = {}
    for name, (folder, globs, windowed) in roots(Path.home(), dict(os.environ)).items():
        files: dict[str, list[int]] = {}
        for pattern in globs:
            for path in folder.glob(pattern) if folder.is_dir() else []:
                info = _regular_stat(path)
                if info and (not windowed or info[1] >= cutoff):
                    files[path.relative_to(folder).as_posix()] = info
        out[name] = files
    return out


def list_mirror(name: str) -> Listing:
    """The files already copied from machine `name`, in the same shape as list_sources."""
    base = runs_dir(Path.home(), dict(os.environ)) / "remotes" / name
    out: Listing = {}
    for root in roots(Path.home(), {}):
        folder = base / MIRROR_PATH.get(root, root)
        files: dict[str, list[int]] = {}
        for path in folder.rglob("*") if folder.is_dir() else []:
            info = _regular_stat(path)
            if info:
                files[path.relative_to(folder).as_posix()] = info
        out[root] = files
    return out


def _regular_stat(path: Path) -> list[int] | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    if not path.is_file() or path.is_symlink():
        return None
    return [info.st_size, int(info.st_mtime)]


def pack(wanted: dict[str, list[str]]) -> bytes:
    """A tar of the wanted files, each named <root>/<relative path>."""
    folders = {name: folder for name, (folder, _, _) in roots(Path.home(), dict(os.environ)).items()}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for root, rels in wanted.items():
            for rel in rels:
                path = folders[root] / rel
                if _safe_rel(rel) and _regular_stat(path):
                    tar.add(path, arcname=f"{root}/{rel}", recursive=False)
    return buffer.getvalue()


def unpack(name: str, data: bytes) -> int:
    """Write each file of a pack() tar into remotes/<name>/, private to the user. Returns the file count."""
    base = runs_dir(Path.home(), dict(os.environ))
    target = base / "remotes" / name
    for folder in (base, base / "remotes", target):
        _private_dir(folder)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        for member in tar:
            root, _, rel = member.name.partition("/")
            if not member.isfile() or root not in roots(Path.home(), {}) or not _safe_rel(rel):
                raise ValueError(f"refused tar member: {member.name!r}")
            dest = target / MIRROR_PATH.get(root, root) / rel
            for parent in reversed(dest.relative_to(target).parents):
                _private_dir(target / parent)
            source = tar.extractfile(member)
            if source is None:
                raise ValueError(f"refused tar member: {member.name!r}")
            # Write a temp file, then rename it, so a reader never sees half a file.
            temp = dest.with_name(f".{dest.name}.part")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(source.read())
            os.chmod(temp, 0o600)
            os.utime(temp, (member.mtime, member.mtime))
            os.replace(temp, dest)
            count += 1
    return count


def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _safe_rel(rel: str) -> bool:
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(part not in ("", ".", "..") for part in parts)


def changed(source: Listing, mirror: Listing) -> dict[str, list[str]]:
    """The files whose size or mtime differ from the copy, by root."""
    out = {}
    for root, files in source.items():
        rels = sorted(rel for rel, info in files.items() if mirror.get(root, {}).get(rel) != info)
        if rels:
            out[root] = rels
    return out


def batches(wanted: dict[str, list[str]], listing: Listing, limit: int) -> list[dict[str, list[str]]]:
    """Split the wanted files into batches of at most `limit` bytes. A larger file gets a batch of its own."""
    out: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    size = 0
    for root, rels in wanted.items():
        for rel in rels:
            file_size = listing[root][rel][0]
            if current and size + file_size > limit:
                out.append(current)
                current, size = {}, 0
            current.setdefault(root, []).append(rel)
            size += file_size
    if current:
        out.append(current)
    return out


def _count(wanted: dict[str, list[str]]) -> int:
    return sum(len(rels) for rels in wanted.values())


# ---- the laptop side ----


class Unreachable(Exception):
    pass


def remote(host: str, command: list[str], data: bytes = b"") -> bytes:
    """Run this file's `command` on `host` with its python3, and return its stdout."""
    source = base64.b64encode(Path(__file__).read_bytes()).decode()
    bootstrap = f"import base64; exec(compile(base64.b64decode('{source}'), 'agent-runs-sync', 'exec'))"
    line = shlex.join(["python3", "-c", bootstrap, *command])
    result = subprocess.run(["ssh", *SSH_OPTIONS, host, line], input=data, capture_output=True, timeout=600)
    if result.returncode == 255:
        raise Unreachable(result.stderr.decode(errors="replace").strip())
    if result.returncode != 0:
        raise RuntimeError(f"remote {command[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def box_state(devbox_cmd: str) -> str:
    """The workstation state from `devbox status --json` (schema 1), or a reason it is unknown."""
    try:
        result = subprocess.run([devbox_cmd, "status", "--json"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"state unknown ({exc})"
    try:
        status = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return f"state unknown (devbox status --json exit {result.returncode})"
    state = status.get("state") if isinstance(status, dict) and status.get("schema") == 1 else None
    return state if isinstance(state, str) else "state unknown (no state in devbox status --json)"


def sync(host: str, me: str, days: int, devbox_cmd: str, batch_bytes: int) -> int:
    state = box_state(devbox_cmd)
    if state != "STATE_RUNNING":
        print(f"{host} is {state}, skipped")
        return 0
    pulled = pushed = 0
    try:
        theirs = json.loads(remote(host, ["list", "--days", str(days)]))
        for batch in batches(changed(theirs, list_mirror(host)), theirs, batch_bytes):
            pulled += unpack(host, remote(host, ["pack"], json.dumps(batch).encode()))

        ours = list_sources(days)
        for batch in batches(changed(ours, json.loads(remote(host, ["mirror-list", me]))), ours, batch_bytes):
            remote(host, ["unpack", me], pack(batch))
            pushed += _count(batch)
    except Unreachable as exc:
        print(f"{host} not reachable, skipped: {exc}")
        return 0
    print(f"pulled {pulled} files from {host}, pushed {pushed} files as {me}")
    return 0


def default_name() -> str:
    return socket.gethostname().split(".")[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-runs-sync", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="internal")
    for internal in ("list", "pack", "mirror-list", "unpack"):
        command = sub.add_parser(internal, help=argparse.SUPPRESS)
        if internal == "list":
            command.add_argument("--days", type=int, default=DEFAULT_DAYS)
        if internal in ("mirror-list", "unpack"):
            command.add_argument("name")
    parser.add_argument("--host", default="devbox", help="ssh host of the devbox (default: devbox)")
    parser.add_argument("--as", dest="me", default=None, help="this machine's name on the devbox (default: hostname)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="copy files changed in the last N days")
    parser.add_argument("--devbox-cmd", default="devbox", help="the devbox CLI that reports the box state")
    parser.add_argument("--batch-mb", type=float, default=DEFAULT_BATCH_MB, help="largest tar of one copy step")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.internal == "list":
        print(json.dumps(list_sources(args.days)))
    elif args.internal == "pack":
        sys.stdout.buffer.write(pack(json.load(sys.stdin)))
    elif args.internal in ("mirror-list", "unpack"):
        if not NAME.match(args.name):
            print(f"agent-runs-sync: bad machine name {args.name!r}", file=sys.stderr)
            return 2
        if args.internal == "mirror-list":
            print(json.dumps(list_mirror(args.name)))
        else:
            unpack(args.name, sys.stdin.buffer.read())
    else:
        me = args.me or default_name()
        for flag, value in (("--as", me), ("--host", args.host)):
            if not NAME.match(value):
                print(f"agent-runs-sync: {flag} must be a plain name, got {value!r}", file=sys.stderr)
                return 2
        if args.days < 1 or args.batch_mb <= 0:
            print("agent-runs-sync: --days must be 1 or more, and --batch-mb more than 0", file=sys.stderr)
            return 2
        try:
            return sync(args.host, me, args.days, args.devbox_cmd, int(args.batch_mb * 1_000_000))
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"agent-runs-sync: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
