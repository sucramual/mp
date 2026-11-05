#!/usr/bin/env python3
"""Fail when a tracked Markdown file has more lines than its limit in scripts/md_budgets.json.

Agent instructions grow when each fix adds a line and no fix removes one. A limit stops that:
below its limit a file can grow, and at its limit each added line must replace or delete a line.

- `files` gives a fixed limit for one file. It holds the files that load in every session,
  frozen at their size, and the files that were over their default limit when the check started.
- `defaults` gives the limit for every other file: the first glob that matches the path wins.
  A `null` limit means no cap. Skills use it, so only the skills listed in `files` are capped:
  the agent-run skills that load every run. Experimental skills can grow freely.
  A glob `*` matches inside one path segment only, so `skills/*/SKILL.md` does not match references.

The check reads files from `git ls-files`, so untracked and ignored files are not checked.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BUDGETS = Path(__file__).with_name("md_budgets.json")


def glob_pattern(glob: str) -> re.Pattern[str]:
    """Convert a glob to a regex where `*` matches inside one path segment, and `*.md` matches any path."""
    if "/" not in glob:
        return re.compile("(?:.*/)?" + re.escape(glob).replace(r"\*", "[^/]*") + r"\Z")
    return re.compile(re.escape(glob).replace(r"\*", "[^/]*") + r"\Z")


def limit_for(path: str, budgets: dict) -> int | None:
    if path in budgets["files"]:
        return budgets["files"][path]
    for glob, limit in budgets["defaults"].items():
        if glob_pattern(glob).match(path):
            return limit
    return None


def tracked_markdown(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"], check=True, capture_output=True, text=True
    ).stdout
    return sorted(path for path in output.split("\0") if path)


def check(root: Path, budgets: dict) -> list[str]:
    errors = []
    tracked = tracked_markdown(root)
    for path in budgets["files"]:
        if path not in tracked:
            errors.append(f"{BUDGETS.name}: {path} is not a tracked Markdown file. Remove its entry.")
    for path in tracked:
        file = root / path
        if not file.is_file():
            continue
        limit = limit_for(path, budgets)
        if limit is None:
            continue
        lines = len(file.read_text(encoding="utf-8", errors="replace").splitlines())
        if lines > limit:
            errors.append(
                f"{path}: {lines} lines, limit {limit}. Replace or delete lines for the ones you add, "
                "or move detail to a references/ file."
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--budgets", type=Path, default=BUDGETS)
    args = parser.parse_args(argv)
    budgets = json.loads(args.budgets.read_text(encoding="utf-8"))
    errors = check(args.root, budgets)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
