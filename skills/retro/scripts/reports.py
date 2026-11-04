#!/usr/bin/env python3
"""Save retro reports to the report store, and find patterns across the newest ones.

Usage:
  python3 reports.py [--dir DIR] check <file>
  python3 reports.py [--dir DIR] save <file>
  python3 reports.py [--dir DIR] patterns [--last N] [--json]

The store is `--dir`, else `$RETRO_DIR`, else `.retro/` in the dotfiles main checkout (gitignored).
references/report-format.md gives the format. Exits 1 on a malformed report and names it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

FRONTMATTER_KEYS = ("created", "topic", "skills", "tickets", "sessions")
LIST_KEYS = {"skills", "tickets", "sessions"}
MAY_BE_EMPTY = {"tickets"}
FINDING_KEYS = ("target", "kind", "cost", "evidence", "fix")
TARGET_TYPES = ("skill", "tool", "guide", "intake", "harness", "brief", "repo")
KINDS = (
    "failure",
    "stall",
    "loop",
    "permission-wait",
    "no-action",
    "unproven-check",
    "rework",
    "unpassable-check",
)
TARGET = re.compile(rf"^({'|'.join(TARGET_TYPES)}):[a-z0-9][a-z0-9._/-]*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FINDING_HEADING = re.compile(r"^### (\d+)\. (.+)$")
FIELD = re.compile(r"^- ([a-z]+): (.*)$")
DEFAULT_LAST = 10


def parse_report(text: str) -> dict[str, Any]:
    """Return the frontmatter fields and findings of one report. Raise ValueError when it breaks the format."""
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("report must start with a --- frontmatter block")
    end = lines.index("---", 1)

    report: dict[str, Any] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not separator or key not in FRONTMATTER_KEYS:
            raise ValueError(f"unknown frontmatter line: {line!r}")
        report[key] = [item.strip() for item in value.split(",") if item.strip()] if key in LIST_KEYS else value
    for key in FRONTMATTER_KEYS:
        if key not in report:
            raise ValueError(f"missing frontmatter key: {key}")
        if not report[key] and key not in MAY_BE_EMPTY:
            raise ValueError(f"empty frontmatter key: {key}")
    if not DATE.match(report["created"]):
        raise ValueError("created must be YYYY-MM-DD")

    sections = _sections(lines[end + 1 :])
    table = [row for row in sections.get("Sessions", []) if row.startswith("|")]
    # The first two table lines are the header and the --- separator.
    if len(table) < 3:
        raise ValueError("Sessions table has no rows")
    report["findings"] = _findings(sections.get("Findings", []))
    if not report["findings"]:
        raise ValueError("report has no findings")
    return report


def _sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            current = sections.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return sections


def _findings(lines: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line in lines:
        if heading := FINDING_HEADING.match(line):
            findings.append({"number": int(heading.group(1)), "title": heading.group(2).strip()})
        elif findings and (field := FIELD.match(line)) and field.group(1) in FINDING_KEYS:
            findings[-1][field.group(1)] = field.group(2).strip()
    for finding in findings:
        label = f"finding {finding['number']}"
        for key in FINDING_KEYS:
            if not finding.get(key):
                raise ValueError(f"{label}: missing key: {key}")
        if not TARGET.match(finding["target"]):
            raise ValueError(f"{label}: target must be <type>:<name>, type one of {', '.join(TARGET_TYPES)}")
        if finding["kind"] not in KINDS:
            raise ValueError(f"{label}: unknown kind: {finding['kind']}")
    return findings


def store_dir(override: str | None) -> Path:
    """Return the report store: the override, else $RETRO_DIR, else .retro/ in the main checkout."""
    if override:
        return Path(override).expanduser()
    if env := os.environ.get("RETRO_DIR"):
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent
    # The common dir is the main checkout's .git, so a run from a linked worktree still writes to one store.
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=here,
        capture_output=True,
        text=True,
        check=False,
    )
    root = Path(common.stdout.strip()).parent if common.returncode == 0 else here.parents[2]
    return root / ".retro"


def save(source: Path, store: Path) -> Path:
    text = source.read_text(encoding="utf-8")
    report = parse_report(text)
    slug = re.sub(r"[^a-z0-9]+", "-", report["topic"].lower()).strip("-")
    store.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        suffix = "" if number == 1 else f"-{number}"
        target = store / f"{report['created']}-{slug}{suffix}.md"
        try:
            # Exclusive create reserves the name, so two concurrent saves cannot share a path.
            with target.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            number += 1
            continue
        break
    return target


def patterns(store: Path, last: int) -> list[dict[str, Any]]:
    """Group the findings of the newest `last` reports by target and kind, most-repeated first."""
    loaded = []
    for path in sorted(store.glob("*.md")) if store.is_dir() else []:
        try:
            loaded.append((path, parse_report(path.read_text(encoding="utf-8"))))
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
    loaded.sort(key=lambda item: (item[1]["created"], item[0].name), reverse=True)

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for path, report in loaded[:last]:
        for finding in report["findings"]:
            key = (finding["target"], finding["kind"])
            group = groups.setdefault(key, {"target": key[0], "kind": key[1], "reports": [], "findings": []})
            if path.name not in group["reports"]:
                group["reports"].append(path.name)
            group["findings"].append({"report": path.name, "created": report["created"], **finding})
    result = []
    for group in groups.values():
        group["runs"] = len(group["reports"])
        group["seen_once"] = group["runs"] == 1
        result.append(group)
    result.sort(key=lambda g: (-g["runs"], -len(g["findings"]), g["target"], g["kind"]))
    return result


def _table(groups: list[dict[str, Any]]) -> str:
    rows = ["| Target | Kind | Runs | Findings |", "| --- | --- | --- | --- |"]
    for group in groups:
        runs = f"{group['runs']} (seen once)" if group["seen_once"] else str(group["runs"])
        titles = "; ".join(f"{f['title']} ({f['report']})" for f in group["findings"])
        rows.append(f"| {group['target']} | {group['kind']} | {runs} | {titles} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", help="report store (default: $RETRO_DIR or .retro/ in the dotfiles checkout)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("file", type=Path)
    commands.add_parser("save").add_argument("file", type=Path)
    find = commands.add_parser("patterns")
    find.add_argument("--last", type=int, default=DEFAULT_LAST)
    find.add_argument("--json", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    store = store_dir(args.dir)

    try:
        if args.command == "check":
            parse_report(args.file.read_text(encoding="utf-8"))
            print(f"ok: {args.file}")
        elif args.command == "save":
            print(save(args.file, store))
        else:
            groups = patterns(store, args.last)
            if args.json:
                print(json.dumps(groups, indent=2))
            elif not groups:
                print(f"no retro reports in {store}")
            else:
                print(_table(groups))
    except ValueError as exc:
        name = args.file if args.command != "patterns" else store
        print(f"error: {name}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
