#!/usr/bin/env python3
"""Merge the portable template keys and the cloud-only settings into a cloud session's settings.

Usage:
  merge_cloud_settings.py <settings.template.json> <settings.cloud.json> <~/.claude/settings.json>

scripts/cloud-bootstrap runs this. On a laptop, install.sh copies the whole template once instead.
The script copies only PORTABLE_KEYS, because the other keys need the laptop:
a status line script, a model alias, or a permission prompt that the laptop turns off.

  - It drops LOCAL_ONLY_PLUGINS, and each marketplace that no kept plugin comes from.
    It also removes a LOCAL_ONLY_PLUGINS entry that the target already has, such as one from an earlier run.
  - For a table key (env, enabledPlugins, extraKnownMarketplaces), it keeps the entries that only
    the target has. The template wins for each entry it sets.
  - It adds each permissions.allow rule from settings.cloud.json that the target does not have yet.
    It keeps the target's own rules first, and every other permissions key.
  - It keeps every other key in the target, such as hooks that the cloud harness writes.
  - It writes atomically, and only when the result differs from the target.

Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PORTABLE_KEYS = ("env", "effortLevel", "autoCompactWindow", "enabledPlugins", "extraKnownMarketplaces")
# Each template key is in PORTABLE_KEYS or here; tests/test_cloud_bootstrap.py fails on a key in neither.
# model: a laptop model alias. statusLine: a laptop script. theme: the app picks its own.
# attribution: the cloud harness sets its own commit trailers. skipDangerousModePermissionPrompt: a safety prompt.
LOCAL_ONLY_KEYS = ("model", "statusLine", "theme", "attribution", "skipDangerousModePermissionPrompt")
# These plugins start a program that a cloud container does not have:
# the local Codex CLI and its login, or the hallouminate binary.
LOCAL_ONLY_PLUGINS = frozenset({"codex@openai-codex", "hallouminate@hallouminate"})


def portable_settings(template: dict) -> dict:
    settings = {key: template[key] for key in PORTABLE_KEYS if key in template}
    plugins = {name: on for name, on in settings.get("enabledPlugins", {}).items() if name not in LOCAL_ONLY_PLUGINS}
    if "enabledPlugins" in settings:
        settings["enabledPlugins"] = plugins
    if "extraKnownMarketplaces" in settings:
        used = {name.rpartition("@")[2] for name in plugins}
        settings["extraKnownMarketplaces"] = {
            name: market for name, market in settings["extraKnownMarketplaces"].items() if name in used
        }
    return settings


def merge(target: dict, portable: dict) -> dict:
    merged = dict(target)
    for key, value in portable.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    # An earlier bootstrap may have enabled a plugin that is now local-only.
    if isinstance(merged.get("enabledPlugins"), dict):
        merged["enabledPlugins"] = {
            name: on for name, on in merged["enabledPlugins"].items() if name not in LOCAL_ONLY_PLUGINS
        }
    return merged


def add_allow_rules(target: dict, rules: list[str]) -> dict:
    permissions = dict(target.get("permissions") or {})
    allow = list(permissions.get("allow") or [])
    allow += [rule for rule in rules if rule not in allow]
    permissions["allow"] = allow
    return {**target, "permissions": permissions}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    template_path, cloud_path, target_path = Path(argv[0]), Path(argv[1]), Path(argv[2])
    template = json.loads(template_path.read_text(encoding="utf-8"))
    cloud_rules = json.loads(cloud_path.read_text(encoding="utf-8"))["permissions"]["allow"]
    current = json.loads(target_path.read_text(encoding="utf-8")) if target_path.exists() else {}
    if not isinstance(current, dict):
        print(f"merge_cloud_settings.py: {target_path} does not hold a JSON object", file=sys.stderr)
        return 1
    merged = add_allow_rules(merge(current, portable_settings(template)), cloud_rules)
    if merged == current and target_path.exists():
        print(f"  {target_path} already current")
        return 0
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=target_path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    os.replace(handle.name, target_path)
    print(f"  Merged portable settings into {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
