#!/usr/bin/env python3
"""Merge the tracked Codex base config into the machine-owned local config.

Usage:
  merge_config.py [--overlay <work-overlay.toml>] <tracked-base.toml> <local-config.toml>

The Codex app edits single keys in $CODEX_HOME/config.toml and follows
symlinks, so the local file must be a real, untracked file. This script:

  - converts a legacy symlink into a real file holding the link's resolved
    contents and mode, so values the app wrote through the link survive. When
    the link points into a git work tree, keys from the file's revision before
    its latest commit fill in any key the current contents lack (the first
    sync after the app keys left the tracked file already sees the stripped
    file);
  - does the same history recovery once for a link that dotfiles-pr already
    converted: dotfiles-pr converts the link in-process, with no TOML parser,
    so before the checkout moves it only byte-copies the link's file into place
    and records the link's path and the checkout's HEAD in
    <local-config>.dotfiles-legacy-link. This script reads that record, looks
    up history as of that HEAD, and deletes the record after a merge.
    Both conversions follow one rule: the real file gets the resolved bytes
    and mode, and the backup is a content copy named like install.sh's;
  - removes keys the previous base set but the new base dropped, when the
    local value still equals the previous base value. The last-applied base
    is kept next to the target as <local-config>.dotfiles-base. Without that
    file nothing is removed;
  - deep-merges tables: keys only in the local file are kept, and the tracked
    base wins for every key it defines. Values compare type-strictly, so a
    local `enabled = 1` is corrected to a tracked `enabled = true`;
  - prints one drift line per local value the base overwrote;
  - backs up the local file (.bak, then .bak.<timestamp>) and writes
    atomically, but only when the merged result differs from what is there.
    A rewrite drops comments and formatting; the .bak keeps them.
  - aborts without touching the target when the file changed while this
    script ran (the Codex app wrote to it); re-running is safe.

With --overlay, the base is the tracked base deep-merged with the overlay file, and the overlay wins on
a conflict. The private work overlay holds keys that the public repo must not, such as a trusted work
project. install.sh and dotfiles-pr sync pass it when the overlay has config/codex/config.toml. The
last-applied base then holds the combined keys, so a later merge without the overlay removes its keys.

The tracked base and the overlay are only read, never written. Standard library only.
"""

from __future__ import annotations

import copy
import datetime
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 (e.g. the Xcode Command Line Tools python3)
    sys.exit("merge_config.py: needs Python 3.11+ for tomllib")

PROG = "merge_config.py"
HEADER = (
    "# Machine-owned Codex config (not tracked in git). The Codex app edits this file.\n"
    "# install.sh merges ~/dotfiles/config/codex/config.toml into it; tracked keys win.\n"
)
BASE_STATE_SUFFIX = ".dotfiles-base"
LEGACY_LINK_SUFFIX = ".dotfiles-legacy-link"  # Written by dotfiles-pr's convert_codex_link.
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
REPO_DIR = Path(__file__).resolve().parents[2]
KeyPath = tuple[str, ...]


def display(path: Path) -> str:
    """Shorten a path for log lines: repo-relative, else ~-relative, else absolute."""
    for root, prefix in ((REPO_DIR, ""), (Path.home(), "~/")):
        try:
            return prefix + str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


# --- comparing and merging ---------------------------------------------------


def same(a: object, b: object) -> bool:
    """Type-strict deep equality: 1, 1.0, and true all differ; two NaNs are equal."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=False))
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def merge(local: dict, base: dict, path: KeyPath = ()) -> tuple[dict, list[tuple[str, object, object]]]:
    """Return (local ∪ base with base winning on conflicts, drift list)."""
    merged = dict(local)
    drift: list[tuple[str, object, object]] = []
    for key, base_value in base.items():
        key_path = (*path, key)
        if key not in local:
            merged[key] = base_value
        elif isinstance(base_value, dict) and isinstance(local[key], dict):
            merged[key], sub_drift = merge(local[key], base_value, key_path)
            drift.extend(sub_drift)
        else:
            if not same(local[key], base_value):
                drift.append((dotted(key_path), local[key], base_value))
            merged[key] = base_value
    return merged, drift


def fill_missing(current: dict, lower: dict) -> dict:
    """Return current plus every key of lower that current lacks. Never overrides current."""
    filled = dict(current)
    for key, value in lower.items():
        if key not in current:
            filled[key] = value
        elif isinstance(value, dict) and isinstance(current[key], dict):
            filled[key] = fill_missing(current[key], value)
    return filled


def leaves(table: dict, path: KeyPath = ()) -> Iterator[tuple[KeyPath, object]]:
    """Yield (key path, value) for every non-table value and every empty table."""
    for key, value in table.items():
        if isinstance(value, dict) and value:
            yield from leaves(value, (*path, key))
        else:
            yield (*path, key), value


def lookup(table: dict, path: KeyPath) -> tuple[bool, object]:
    node: object = table
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def remove_dropped(local: dict, previous_base: dict, base: dict) -> dict:
    """Delete keys the previous base set and the new base dropped, if local still has the old value."""
    result = copy.deepcopy(local)
    for path, old_value in leaves(previous_base):
        if lookup(base, path)[0]:
            continue
        found, local_value = lookup(result, path)
        if not found:
            continue
        if not same(local_value, old_value):
            print(f"  Codex config note: {dotted(path)} is no longer tracked but was changed locally; kept")
            continue
        parents = [result]
        for key in path[:-1]:
            parents.append(parents[-1][key])
        del parents[-1][path[-1]]
        # Drop tables that this deletion emptied.
        for depth in range(len(path) - 1, 0, -1):
            if parents[depth]:
                break
            del parents[depth - 1][path[depth - 1]]
        print(f"  Codex config removed: {dotted(path)}")
    return result


# --- TOML writer (covers the value types tomllib can return) ---------------


def format_key(key: str) -> str:
    return key if BARE_KEY.fullmatch(key) else format_string(key)


def dotted(path: KeyPath) -> str:
    return ".".join(format_key(part) for part in path)


def format_string(value: str) -> str:
    # Literal strings keep JSON-ish values readable; they cannot hold ' or control chars.
    if (
        ("\\" in value or '"' in value)
        and "'" not in value
        and not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
    ):
        return f"'{value}'"
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def format_value(value: object) -> str:
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return format_string(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{format_key(k)} = {format_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"unsupported TOML value: {value!r}")


def dumps(data: dict) -> str:
    lines: list[str] = []

    def emit_table(table: dict, path: KeyPath) -> None:
        scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
        tables = [(k, v) for k, v in table.items() if isinstance(v, dict)]
        # A table holding only sub-tables is implied by their headers.
        if path and (scalars or not tables):
            lines.extend(["", f"[{dotted(path)}]"])
        lines.extend(f"{format_key(k)} = {format_value(v)}" for k, v in scalars)
        for key, sub in tables:
            emit_table(sub, (*path, key))

    emit_table(data, ())
    return HEADER + "\n".join(lines).lstrip("\n") + "\n"


# --- files -----------------------------------------------------------------


def parse(data: bytes, source: object) -> dict:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        sys.exit(f"{PROG}: cannot parse {source}: {error}")


def fingerprint(path: Path) -> tuple[object, ...] | None:
    """Identify the target's current state: the link or file itself, plus what a link points to."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    marks: tuple[object, ...] = (st.st_ino, st.st_mtime_ns, st.st_size)
    if stat.S_ISLNK(st.st_mode):
        try:
            linked = os.stat(path)
            marks += (linked.st_ino, linked.st_mtime_ns, linked.st_size)
        except FileNotFoundError:
            marks += (None,)
    return marks


def git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:  # git is not installed
        return None
    return result.stdout if result.returncode == 0 else None


def revision_before_latest_commit(path: Path, rev: str = "HEAD") -> dict:
    """Parse path as it was before the latest commit up to rev that touched it. {} when git cannot say."""
    if not path.parent.is_dir():
        return {}
    top = git(path.parent, "rev-parse", "--show-toplevel")
    if top is None:
        return {}
    root = Path(top.strip()).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return {}
    # Run from the work tree root: pathspecs are relative to the current directory.
    sha = (git(root, "log", "-1", "--format=%H", rev, "--", relative) or "").strip()
    shown = git(root, "show", f"{sha}^:{relative}") if sha else None
    if shown is None:
        return {}
    try:
        return tomllib.loads(shown)
    except tomllib.TOMLDecodeError:
        return {}


class Local:
    """The local config as loaded: parsed contents, raw bytes, mode, and whether it was a legacy link."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.fingerprint = fingerprint(target)
        self.is_link = target.is_symlink()
        self.raw: bytes | None = None
        self.mode = 0o644
        self.data: dict = {}  # The contents plus any keys recovered from git history.
        self.file_data: dict = {}  # The contents alone, to tell whether a write is needed.
        self.legacy_record = Path(f"{target}{LEGACY_LINK_SUFFIX}")
        if self.is_link:
            print(f"  Found legacy {display(target)} symlink -> converting to real file")
            if not target.is_file():  # A dangling link has no contents to keep.
                return
            resolved = target.resolve()
            self.raw = resolved.read_bytes()
            self.mode = resolved.stat().st_mode & 0o777
            self.file_data = parse(self.raw, resolved)
            self.data = fill_missing(self.file_data, revision_before_latest_commit(resolved))
        elif os.path.lexists(target):
            if not target.is_file():
                sys.exit(f"{PROG}: {target} exists but is not a regular file")
            self.raw = target.read_bytes()
            self.mode = target.stat().st_mode & 0o777
            self.file_data = self.data = parse(self.raw, target)
            if self.legacy_record.is_file():
                lines = self.legacy_record.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) >= 2 and re.fullmatch(r"[0-9a-f]{7,64}|HEAD", lines[1]):
                    self.data = fill_missing(self.data, revision_before_latest_commit(Path(lines[0]), lines[1]))

    def ensure_unchanged(self) -> None:
        if fingerprint(self.target) != self.fingerprint:
            sys.exit(f"{PROG}: Codex wrote the config during install; re-run ({self.target} was left untouched)")

    def replace(self, text: str) -> None:
        """Back up what is there, then atomically write text, unless the target changed since loading."""
        self.ensure_unchanged()
        if self.raw is not None:
            backup = backup_path(self.target)
            print(f"  Backing up existing {display(self.target)} -> {display(backup)}")
            write_atomic(backup, self.raw, self.mode)
        write_atomic(self.target, text.encode("utf-8"), self.mode, before_replace=self.ensure_unchanged)


def backup_path(target: Path) -> Path:
    """Mirror install.sh: <target>.bak, else <target>.bak.<timestamp>[.N]."""
    backup = Path(f"{target}.bak")
    if not os.path.lexists(backup):
        return backup
    base = f"{target}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    backup, suffix = Path(base), 1
    while os.path.lexists(backup):
        backup, suffix = Path(f"{base}.{suffix}"), suffix + 1
    print(f"  WARNING: {display(target)}.bak already exists — backing up to {display(backup)} instead")
    return backup


def write_atomic(target: Path, data: bytes, mode: int, before_replace=None) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        if before_replace is not None:
            before_replace()
        os.replace(tmp, target)  # Replaces a symlink itself, never the file it points to.
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


# --- command -----------------------------------------------------------------


def merge_into(base_path: Path, target: Path, overlay_path: Path | None = None) -> int:
    base_raw = base_path.read_bytes()
    base = parse(base_raw, base_path)
    if overlay_path is not None:
        if not overlay_path.is_file():
            sys.exit(f"{PROG}: overlay {overlay_path} is not a file")
        base, _ = merge(base, parse(overlay_path.read_bytes(), overlay_path))
        # The state file must parse back to the combined base. Drop the header: it describes the local file.
        base_raw = dumps(base)[len(HEADER) :].encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    local = Local(target)

    state = Path(f"{target}{BASE_STATE_SUFFIX}")
    kept = local.data
    if state.is_file():
        try:
            previous_base = tomllib.loads(state.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            print(f"  Codex config note: cannot parse {display(state)}; no keys removed")
        else:
            kept = remove_dropped(local.data, previous_base, base)

    merged, drift = merge(kept, base)
    for key, old, new in drift:
        print(f"  Codex config drift: {key}: {format_value(old)} -> {format_value(new)} (tracked value wins)")

    if not local.is_link and local.raw is not None and same(merged, local.file_data):
        local.ensure_unchanged()  # A write since loading may have undone a tracked value.
        print(f"  {display(target)} already current")
    else:
        local.replace(dumps(merged))
        print(f"  Merged {display(base_path)} into {display(target)}")

    if not state.is_file() or state.read_bytes() != base_raw:
        write_atomic(state, base_raw, 0o644)
    if local.legacy_record.is_file():  # Its history recovery is now in the merged file.
        local.legacy_record.unlink()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and not argv[1].startswith("-"):
        return merge_into(Path(argv[1]), Path(argv[2]))
    if len(argv) == 5 and argv[1] == "--overlay" and not argv[3].startswith("-"):
        return merge_into(Path(argv[3]), Path(argv[4]), Path(argv[2]))
    print((__doc__ or "").strip().splitlines()[3], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
