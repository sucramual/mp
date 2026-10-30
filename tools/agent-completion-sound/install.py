#!/usr/bin/env python3
"""Install targeted completion adapters. install.sh calls this only on macOS (Python 3.11+)."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
import tomllib
from pathlib import Path


class Target:
    def __init__(self, path: Path):
        self.path = path
        self.raw = path.read_bytes() if path.exists() else None
        self.mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        self.mark = path.lstat() if path.is_symlink() or path.exists() else None

    def ensure_unchanged(self) -> None:
        current = self.path.lstat() if self.path.exists() or self.path.is_symlink() else None
        raw = self.path.read_bytes() if self.path.exists() else None
        if current != self.mark or raw != self.raw:
            raise ValueError(f"{self.path} changed during install; re-run")

    def write(self, text: str) -> None:
        self.ensure_unchanged()
        data = text.encode("utf-8")
        if data == self.raw and not self.path.is_symlink():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.raw is not None:
            backup, suffix = Path(f"{self.path}.bak"), 0
            while backup.exists() or backup.is_symlink():
                suffix += 1
                backup = Path(f"{self.path}.bak.{suffix}")
            backup.write_bytes(self.raw)
            backup.chmod(self.mode)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(temporary, self.mode)
            self.ensure_unchanged()
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def owned_tail(argv: list[str], paths: set[str]) -> list[str] | None:
    if argv and argv[0] in paths:
        return argv[1:]
    if len(argv) > 1 and argv[1] in paths and re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(argv[0]).name):
        return argv[2:]
    return None


def replace_notify(text: str, data: dict, callback: list[str]) -> str:
    assignment = f"notify = {json.dumps(callback, ensure_ascii=False)}\n"
    if "notify" not in data:
        return assignment + text
    lines = text.splitlines(keepends=True)
    for start, line in enumerate(lines):
        if re.match(r"""\s*(?:notify|"notify"|'notify')\s*=""", line):
            for end in range(start + 1, len(lines) + 1):
                try:
                    parsed = tomllib.loads("".join(lines[start:end]))
                except ValueError:
                    continue
                if parsed == {"notify": data["notify"]}:
                    result = "".join(lines[:start]) + assignment + "".join(lines[end:])
                    if tomllib.loads(result) == {**data, "notify": callback}:
                        return result
                    break
    raise ValueError("Cannot safely locate the root notify assignment; config left untouched")


def install() -> None:
    home = Path.home()
    helper = str(home / "bin/agent-completion-sound.py")
    paths = {helper, str(home / ".local/bin/agent-completion-sound.py")}
    prefix = [helper]
    codex, claude = Target(home / ".codex/config.toml"), Target(home / ".claude/settings.json")
    text = (codex.raw or b"").decode("utf-8")
    data = tomllib.loads(text)
    original = data.get("notify", [])
    if not isinstance(original, list) or not all(isinstance(arg, str) for arg in original):
        raise ValueError("Codex notify must be a list of strings; config left untouched")
    callback = original
    while (tail := owned_tail(callback, paths)) is not None:
        if tail == ["--codex"]:
            callback = []
        elif tail[:2] == ["--codex", "--forward"]:
            callback = tail[2:]
        else:
            break
    notify = [*prefix, "--codex", *(["--forward", *callback] if callback else [])]
    codex_text = text if original == notify else replace_notify(text, data, notify)
    settings = json.loads(claude.raw or b"{}")
    command = shlex.join([*prefix, "--claude"])
    groups = settings.setdefault("hooks", {}).setdefault("Stop", [])
    found = False
    for group in groups:
        kept = []
        for hook in group["hooks"]:
            try:
                argv = shlex.split(hook.get("command", ""))
            except ValueError:
                argv = []
            if hook.get("type") == "command" and owned_tail(argv, paths) == ["--claude"]:
                if found:
                    continue
                hook["command"], hook["async"], found = command, True, True
            kept.append(hook)
        group["hooks"] = kept
    if not found:
        groups.append({"hooks": [{"type": "command", "command": command, "async": True}]})
    claude_text = (claude.raw or b"{}").decode("utf-8")
    if settings != json.loads(claude.raw or b"{}"):
        claude_text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    codex.write(codex_text)
    claude.write(claude_text)
    print("  Completion sound adapters installed for Codex and Claude Code")


if __name__ == "__main__":
    try:
        install()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        sys.exit(f"agent-completion-sound: {error}")
