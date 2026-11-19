#!/usr/bin/env python3
"""Rebuild a file from a Claude Code transcript by replaying its Write and Edit calls.

A run's plan file usually lives in a session scratchpad under /tmp, which the OS clears.
The transcript keeps every Write and Edit call, so this script rebuilds the last version.

Usage: replay_file.py <transcript.jsonl> <path suffix> [--out <file>]
Prints the rebuilt text, or writes it to --out. It applies only calls whose tool_result exists and
is not an error. Reports on stderr how many calls applied, how many had a failed or missing result
(unconfirmed), and how many Edit calls did not match. An Edit that does not match means that some
change came from another tool, such as a shell command, so the result can differ from the real file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Replay:
    text: str | None
    applied: int
    unmatched: int
    unconfirmed: int = 0


def tool_calls(lines: Iterable[str]) -> Iterator[dict]:
    """Yield each tool_use block of the assistant messages, in transcript order."""
    yield from (block for block in blocks(lines) if block.get("type") == "tool_use")


def confirmed_ids(lines: Iterable[str]) -> set[str]:
    """Return the IDs of tool calls whose tool_result exists and is not an error."""
    return {
        str(block.get("tool_use_id"))
        for block in blocks(lines)
        if block.get("type") == "tool_result" and not block.get("is_error")
    }


def blocks(lines: Iterable[str]) -> Iterator[dict]:
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                yield block


def replay(lines: Iterable[str], suffix: str) -> Replay:
    lines = list(lines)
    confirmed = confirmed_ids(lines)
    text: str | None = None
    applied = 0
    unmatched = 0
    unconfirmed = 0
    for call in tool_calls(lines):
        args = call.get("input") or {}
        if not str(args.get("file_path", "")).endswith(suffix):
            continue
        if str(call.get("id")) not in confirmed:
            unconfirmed += 1
            continue
        if call.get("name") == "Write":
            text = args.get("content", "")
            applied += 1
        elif call.get("name") == "Edit" and text is not None:
            old, new = args.get("old_string", ""), args.get("new_string", "")
            if old and old in text:
                text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
                applied += 1
            else:
                unmatched += 1
    return Replay(text, applied, unmatched, unconfirmed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("suffix", help="end of the file path, such as PLAN-1-plan.md")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    with args.transcript.open(encoding="utf-8") as handle:
        result = replay(handle, args.suffix)
    if result.text is None:
        print(f"no Write call for a path ending in {args.suffix}", file=sys.stderr)
        return 1
    print(
        f"applied={result.applied} unmatched_edits={result.unmatched} unconfirmed_calls={result.unconfirmed}",
        file=sys.stderr,
    )
    if args.out:
        args.out.write_text(result.text, encoding="utf-8")
    else:
        sys.stdout.write(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
