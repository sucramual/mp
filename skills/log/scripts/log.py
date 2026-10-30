#!/usr/bin/env python3
"""Parse the tagged `LOG` lines that the log skill writes into agent output.

Usage: python3 log.py [file ...]   (reads stdin when no file is given)
Prints a JSON array of entries. Exits 1 on a malformed `LOG` line.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

KEYS = {
    "run": ("ticket", "sessions", "prs"),
    "friction": ("category", "what", "fix", "at"),
}
LIST_KEYS = {"sessions", "prs"}
MAY_BE_EMPTY = {"prs"}
# A field starts after " | " only when the next text is "<key>=", so a "|" inside a value is kept.
FIELD_SPLIT = re.compile(r" \| (?=[a-z]+=)")


def parse_line(line: str) -> dict[str, str | list[str]] | None:
    """Return the entry for one `LOG` line, or None for any other line."""
    text = line.strip()
    if not text.startswith("LOG "):
        return None
    head, *fields = FIELD_SPLIT.split(text[len("LOG ") :])
    kind = head.strip()
    if kind not in KEYS:
        raise ValueError(f"unknown kind: {kind}")

    values: dict[str, str] = {}
    for field in fields:
        key, value = field.split("=", 1)
        if key not in KEYS[kind]:
            raise ValueError(f"unknown key for {kind}: {key}")
        values[key] = value.strip()

    entry: dict[str, str | list[str]] = {"kind": kind}
    for key in KEYS[kind]:
        if key not in values:
            raise ValueError(f"missing key for {kind}: {key}")
        if not values[key] and key not in MAY_BE_EMPTY:
            raise ValueError(f"empty value for {kind}: {key}")
        if key in LIST_KEYS:
            entry[key] = [item.strip() for item in values[key].split(",") if item.strip()]
        else:
            entry[key] = values[key]
    return entry


def parse_lines(lines: Iterable[str]) -> list[dict[str, str | list[str]]]:
    """Return the entries of every `LOG` line, in order."""
    return [entry for line in lines if (entry := parse_line(line)) is not None]


def main(argv: list[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    lines: list[str] = []
    if paths:
        for path in paths:
            lines.extend(Path(path).read_text(encoding="utf-8").splitlines())
    else:
        lines = sys.stdin.read().splitlines()

    entries = []
    for number, line in enumerate(lines, start=1):
        try:
            entry = parse_line(line)
        except ValueError as exc:
            print(f"error: line {number}: {exc}", file=sys.stderr)
            return 1
        if entry is not None:
            entries.append(entry)
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
