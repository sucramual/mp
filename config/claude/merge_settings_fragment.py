#!/usr/bin/env python3
"""Merge a settings fragment from the private work overlay into a Claude Code settings file.

Usage:
  merge_settings_fragment.py <fragment.json> <~/.claude/settings.json>

install.sh runs this once, right after it seeds settings.json from config/claude/settings.template.json,
when the overlay has config/claude/settings.template.json. The overlay file holds only the work keys, such
as a work plugin in enabledPlugins, so the public template holds no employer values.

  - For a key whose value is an object in both files (env, enabledPlugins, extraKnownMarketplaces),
    it keeps the target's entries and adds or replaces the fragment's entries.
  - For any other key, the fragment's value wins.
  - It writes atomically, and only when the result differs from the target.

Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def merge(target: dict, fragment: dict) -> dict:
    merged = dict(target)
    for key, value in fragment.items():
        current = merged.get(key)
        merged[key] = {**current, **value} if isinstance(value, dict) and isinstance(current, dict) else value
    return merged


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[3], file=sys.stderr)
        return 2
    fragment_path, target_path = Path(argv[0]), Path(argv[1])
    try:
        fragment = read_object(fragment_path)
        current = read_object(target_path)
    except (OSError, ValueError) as error:
        print(f"merge_settings_fragment.py: {error}", file=sys.stderr)
        return 1
    merged = merge(current, fragment)
    if merged == current:
        print(f"  {target_path} already has the work settings")
        return 0
    with tempfile.NamedTemporaryFile("w", dir=target_path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    os.replace(handle.name, target_path)
    print(f"  Merged the work settings from {fragment_path} into {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
