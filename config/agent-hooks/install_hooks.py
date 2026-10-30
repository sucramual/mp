#!/usr/bin/env python3
"""Register the dotfiles agent hooks in Claude Code and Codex settings, and the Claude Code telemetry env.

Usage:
  install_hooks.py <json-file>...

Each file is ~/.claude/settings.json or ~/.codex/hooks.json; both keep hooks under a top-level "hooks" object.
The script adds two groups that match the Bash tool:
  - PreToolUse: guard_irreversible.py beside this script. An entry whose command ends with guard_irreversible.py
    is ours.
  - PostToolUse: `agent-trace hook` from tools/agent-trace, which records PR creates and merges in the run trace.
    An entry whose command ends with `agent-trace hook` is ours.
It updates our existing entry in place, drops a second copy, and keeps every other key and hook.
For a file named settings.json (Claude Code) it also adds each TELEMETRY_ENV key that "env" lacks, so Claude Code
exports its native spans to `agent-trace collect`. A value that is already set stays, so a machine can opt out.
It creates a missing file, refuses a file that is not a JSON object, and writes atomically, only on a change.
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

HERE = Path(__file__).resolve().parent
GUARD = HERE / "guard_irreversible.py"
TRACE = HERE.parent.parent / "tools" / "agent-trace" / "bin" / "agent-trace"
ENTRY = {"type": "command", "command": f"python3 {shlex.quote(str(GUARD))}", "timeout": 10}
TRACE_ENTRY = {"type": "command", "command": f"python3 {shlex.quote(str(TRACE))} hook", "timeout": 5}
# (event, our entry, how to recognise our entry from its command with quotes and spaces stripped at the end)
HOOKS = (("PreToolUse", ENTRY, "guard_irreversible.py"), ("PostToolUse", TRACE_ENTRY, "agent-trace hook"))
# Claude Code exports OTLP traces with these. config/claude/settings.template.json holds the same keys.
TELEMETRY_ENV = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
}


def is_ours(hook: object, suffix: str) -> bool:
    if not isinstance(hook, dict):
        return False
    return str(hook.get("command", "")).replace("'", "").replace('"', "").rstrip().endswith(suffix)


def with_hook(hooks: dict, event: str, entry: dict, suffix: str) -> None:
    """Leave exactly one copy of entry in hooks[event], updating our first entry in place."""
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise ValueError(f'"hooks.{event}" is not a JSON list')
    found = False
    kept_groups = []
    for group in groups:
        entries = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(entries, list) or not any(is_ours(hook, suffix) for hook in entries):
            kept_groups.append(group)
            continue
        kept = []
        for hook in entries:
            if not is_ours(hook, suffix):
                kept.append(hook)
            elif not found:  # Update the first entry in place; drop any later copy.
                kept.append(dict(entry))
                found = True
        if kept:
            kept_groups.append({**group, "hooks": kept})
    if not found:
        kept_groups.append({"matcher": "Bash", "hooks": [dict(entry)]})
    hooks[event] = kept_groups


def with_agent_hooks(settings: dict, claude: bool = False) -> dict:
    """Return a copy of settings with exactly one entry of each of our hooks, plus the telemetry env for Claude."""
    merged = copy.deepcopy(settings)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not a JSON object')
    for event, entry, suffix in HOOKS:
        with_hook(hooks, event, entry, suffix)
    if claude:
        env = merged.setdefault("env", {})
        if not isinstance(env, dict):
            raise ValueError('"env" is not a JSON object')
        for key, value in TELEMETRY_ENV.items():
            env.setdefault(key, value)
    return merged


def install(path: Path) -> str:
    raw = path.read_text() if path.exists() else ""
    try:
        settings = json.loads(raw) if raw.strip() else {}
    except ValueError as error:
        raise ValueError(f"{path} is not valid JSON ({error}); file left untouched") from None
    if not isinstance(settings, dict):
        raise ValueError(f"{path} is not a JSON object; file left untouched")
    merged = with_agent_hooks(settings, claude=path.name == "settings.json")
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
            print(f"  {path}: agent hooks {install(path)}")
        except (OSError, ValueError) as error:
            print(f"install_hooks.py: {error}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
