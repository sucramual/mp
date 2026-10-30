#!/usr/bin/env python3
"""Compare two Spacelift change lists, as `spacectl stack changes --id <stack> --run <run-id>` prints them.

Usage: plan_diff.py <reviewed.json> <tracked.json>

Exit 0 and print "identical" and the lines when the sorted `<action> <resource address>` lists match.
Exit 1 and print a diff when they differ. Exit 2 when an input cannot be read, has an entry without an
action or an address, or has no changes: the comparison stops, and no confirm link goes to Marcus.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path


class BadPlan(Exception):
    pass


def change_lines(path: Path) -> list[str]:
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BadPlan(f"{path}: cannot read: {error}") from error
    if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
        raise BadPlan(f"{path}: not a spacectl change list")
    lines = []
    for group in groups:
        for resource in group.get("Resources") or []:
            action = (resource.get("Metadata") or {}).get("Type") or ""
            address = resource.get("Address") or ""
            if not action or not address:
                raise BadPlan(f"{path}: entry without an action or an address: {json.dumps(resource)}")
            lines.append(f"{action} {address}")
    if not lines:
        raise BadPlan(f"{path}: no changes")
    return sorted(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        reviewed, tracked = change_lines(Path(argv[1])), change_lines(Path(argv[2]))
    except BadPlan as error:
        print(error, file=sys.stderr)
        return 2
    if reviewed == tracked:
        print("identical", *reviewed, sep="\n")
        return 0
    diff = difflib.unified_diff(reviewed, tracked, "reviewed", "tracked", lineterm="")
    print(*diff, sep="\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
