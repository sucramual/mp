#!/usr/bin/env python3
"""Play Glass on completion and preserve the existing Codex callback."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

USAGE = "Usage: acs on|off|status"


def disabled_marker() -> Path:
    return Path.home() / ".config/agent-completion-sound/disabled"


def is_disabled() -> bool:
    try:
        disabled_marker().lstat()
    except FileNotFoundError:
        return False
    return True


def control(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in {"on", "off", "status"}:
        print(f"acs: invalid arguments\n{USAGE}", file=sys.stderr)
        return 2
    command = argv[0]
    try:
        marker = disabled_marker()
        if command == "off":
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch(exist_ok=True)
        elif command == "on":
            marker.unlink(missing_ok=True)
        print("off" if is_disabled() else "on")
    except OSError as error:
        print(f"acs: {command}: {error}", file=sys.stderr)
        return 1
    return 0


def is_completion(payload: str, key: str, expected: str) -> bool:
    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        return False
    return isinstance(event, dict) and event.get(key) == expected


def start_sound() -> subprocess.Popen | None:
    try:
        if is_disabled():
            return None
    except OSError:
        pass
    try:
        return subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Glass.aiff"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return None


def finish_sound(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if not argv or argv in [["--help"], ["-h"]]:
        print(f"{USAGE}\nControl completion sounds for Codex and Claude Code.")
        return 0
    if argv[0] not in {"--claude", "--codex"}:
        return control(argv)
    if argv == ["--claude"]:
        try:
            payload = sys.stdin.read()
        except (OSError, UnicodeError):
            return 0
        if is_completion(payload, "hook_event_name", "Stop"):
            finish_sound(start_sound())
        return 0
    if not argv or argv[0] != "--codex" or len(argv) < 2:
        return 0
    forward = argv[2:] if argv[1] == "--forward" else []
    sound = start_sound() if is_completion(argv[-1], "type", "agent-turn-complete") else None
    status = 0
    try:
        if forward:
            # No shell: callback arguments, output, and exit status remain intact.
            status = subprocess.run(forward, check=False).returncode
    except (OSError, ValueError):
        status = 127
    finally:
        finish_sound(sound)
    return status if status >= 0 else 128 - status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
