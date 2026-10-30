#!/usr/bin/env python3
"""Register the guard_irreversible PreToolUse hook in Claude Code and Codex settings.

Usage:
  install_hooks.py <json-file>...

Each file is ~/.claude/settings.json or ~/.codex/hooks.json; both keep hooks under a top-level "hooks" object.
The script adds one PreToolUse group that runs guard_irreversible.py beside this script on the Bash tool.
It updates an existing entry whose command ends with guard_irreversible.py in place, and keeps every other key
and hook. It creates a missing file, refuses a file that is not a JSON object, and writes atomically, only on a change.
install.sh, scripts/cloud-bootstrap, and `dotfiles-pr sync` run it. Standard library only.
"""

from __future__ import annotations

import copy
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "guard_irreversible.py"
ENTRY = {"type": "command", "command": f"python3 {shlex.quote(str(GUARD))}", "timeout": 10}


def is_guard(hook: object) -> bool:
    return isinstance(hook, dict) and str(hook.get("command", "")).rstrip("'\" ").endswith("guard_irreversible.py")


def with_guard(settings: dict) -> dict:
    """Return a copy of settings with exactly one guard entry in hooks.PreToolUse."""
    merged = copy.deepcopy(settings)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not a JSON object')
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list):
        raise ValueError('"hooks.PreToolUse" is not a JSON list')
    found = False
    kept_groups = []
    for group in groups:
        entries = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(entries, list) or not any(is_guard(hook) for hook in entries):
            kept_groups.append(group)
            continue
        kept = []
        for hook in entries:
            if not is_guard(hook):
                kept.append(hook)
            elif not found:  # Update the first entry in place; drop any later copy.
                kept.append(dict(ENTRY))
                found = True
        if kept:
            kept_groups.append({**group, "hooks": kept})
    if not found:
        kept_groups.append({"matcher": "Bash", "hooks": [dict(ENTRY)]})
    hooks["PreToolUse"] = kept_groups
    return merged


def install(path: Path) -> str:
    raw = path.read_text() if path.exists() else ""
    try:
        settings = json.loads(raw) if raw.strip() else {}
    except ValueError as error:
        raise ValueError(f"{path} is not valid JSON ({error}); file left untouched") from None
    if not isinstance(settings, dict):
        raise ValueError(f"{path} is not a JSON object; file left untouched")
    merged = with_guard(settings)
    if merged == settings and path.exists():
        return "already current"
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return "installed" if raw else "created"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: install_hooks.py <json-file>...", file=sys.stderr)
        return 2
    status = 0
    for target in argv:
        path = Path(target).expanduser()
        try:
            print(f"  {path}: guard_irreversible hook {install(path)}")
        except (OSError, ValueError) as error:
            print(f"install_hooks.py: {error}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
