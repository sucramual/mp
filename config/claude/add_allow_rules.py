#!/usr/bin/env python3
"""Add the tracked allow rules to a Claude Code settings file, and keep every rule and key it already has.

Usage:
  add_allow_rules.py <settings.allow.json> <~/.claude/settings.json>

install.sh seeds settings.json from the template only once, so a later template change never reaches a machine.
install.sh and `dotfiles-pr sync` run this script on every run, so a rule merged into settings.allow.json
goes live on each machine. It only adds rules. To remove a rule, delete it from settings.json by hand as well.

  - It leaves a missing settings file missing, so install.sh can still seed it from the template.
  - It writes atomically, and only when a rule is missing.

Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def add_allow_rules(target: dict, rules: list[str]) -> dict:
    permissions = dict(target.get("permissions") or {})
    allow = list(permissions.get("allow") or [])
    allow += [rule for rule in rules if rule not in allow]
    permissions["allow"] = allow
    return {**target, "permissions": permissions}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[3], file=sys.stderr)
        return 2
    rules_path, target_path = Path(argv[0]), Path(argv[1])
    if not target_path.exists():
        print(f"  {target_path} does not exist yet (allow rules not added)")
        return 0
    try:
        rules = read_object(rules_path)["permissions"]["allow"]
        current = read_object(target_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"add_allow_rules.py: {error}", file=sys.stderr)
        return 1
    merged = add_allow_rules(current, rules)
    if merged == current:
        print(f"  {target_path}: allow rules already current")
        return 0
    with tempfile.NamedTemporaryFile("w", dir=target_path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    os.replace(handle.name, target_path)
    print(f"  Added the allow rules from {rules_path} to {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
