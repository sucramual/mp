#!/usr/bin/env python3
"""Record and reinstall third-party agent skills from skills/third-party.txt.

The `skills` CLI (`npx skills`) records global installs in a lock file.
The lock is $XDG_STATE_HOME/skills/.skill-lock.json when XDG_STATE_HOME is set, else ~/.agents/.skill-lock.json.
This script keeps a pointer list of those installs in the repository. It does not copy skill files.

  export   Rewrite the manifest from the lock.
  check    Exit 1 when the manifest and the lock disagree.
  install  Run `npx skills add` once for each manifest source. The CLI handles skills that are already installed.

Installs always get the latest version of each skill. The CLI has no way to pin a skill to a hash.
The manifest stores only owner/repo, which the CLI reads as a GitHub repository. So export accepts only GitHub sources.
Skills from this repository (sucramual/mp, or a local path) are not third-party, so the script ignores them.
Older lock files record this repository under its old name, sucramual/dotfiles, so the script also ignores that source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "skills" / "third-party.txt"
# This repository's own sources: the current name first, then the old name that older lock files record.
OWN_SOURCES = ("sucramual/mp", "sucramual/dotfiles")
# A sourceUrl that names one of OWN_SOURCES as a whole repository, such as https://github.com/sucramual/mp.git
# or .../sucramual/mp/tree/main. It does not match a longer name, such as sucramual/mp-private.
OWN_SOURCE_URL = re.compile(r"(?:^|[/:])(?:" + "|".join(map(re.escape, OWN_SOURCES)) + r")(?:\.git)?(?:[/#?]|$)")
AGENTS = ("claude-code", "codex", "cursor")
SCRIPT_COMMAND = "python3 scripts/third_party_skills.py"

HEADER = f"""\
# Third-party agent skills, installed with the `skills` CLI (npx skills).
# This file holds pointers only. The skill files stay in their source repositories.
# Format: <source>  <skill> <skill> ...   (one source per line, names sorted)
# After you install or remove a third-party skill, run: {SCRIPT_COMMAND} export
# On a new machine, run: {SCRIPT_COMMAND} install
# Install runs `npx skills add` for every line. The CLI handles skills that are already installed.
# Installs get the latest version of each skill. The CLI cannot pin a version.
"""

# source -> sorted skill names
Manifest = dict[str, list[str]]
Runner = Callable[[list[str]], int]


class ManifestError(ValueError):
    """The manifest or the lock has content that the script cannot use."""


def default_lock_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the global lock path. This mirrors getSkillLockPath() in the skills CLI (src/skill-lock.ts)."""
    environ = os.environ if environ is None else environ
    xdg_state_home = environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "skills" / ".skill-lock.json"
    return Path.home() / ".agents" / ".skill-lock.json"


def is_local_source(source: str, entry: dict | None = None) -> bool:
    """Return True for skills from this repository or from a local path."""
    entry = entry or {}
    if source.lower() in OWN_SOURCES or entry.get("sourceType") == "local":
        return True
    if source.startswith(("/", "~", ".")):
        return True
    return OWN_SOURCE_URL.search(str(entry.get("sourceUrl", "")).strip().lower()) is not None


def parse_lock(text: str, require_github: bool = False) -> Manifest:
    """Group the third-party skills in a lock file by source.

    With require_github, raise for a third-party entry whose sourceType is not "github".
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ManifestError(f"lock is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError("lock is not a JSON object")
    skills = data.get("skills", {})
    if not isinstance(skills, dict):
        raise ManifestError("lock 'skills' is not a JSON object")
    grouped: dict[str, set[str]] = {}
    for name, entry in skills.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("source"), str) or not entry["source"]:
            raise ManifestError(f"lock entry {name!r} has no source")
        source = entry["source"]
        if is_local_source(source, entry):
            continue
        source_type = entry.get("sourceType")
        if require_github and source_type != "github":
            raise ManifestError(
                f"skill {name!r} from {source!r} has sourceType {source_type!r}. "
                "The manifest can only record GitHub owner/repo sources."
            )
        grouped.setdefault(source, set()).add(name)
    return {source: sorted(names) for source, names in sorted(grouped.items())}


def parse_manifest(text: str) -> Manifest:
    """Parse manifest lines. Ignore blank lines and `#` comments."""
    manifest: Manifest = {}
    owners: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        source, *names = line.split()
        if not names:
            raise ManifestError(f"line {number}: source {source!r} has no skill names")
        if source in manifest:
            raise ManifestError(f"line {number}: source {source!r} appears more than once")
        if is_local_source(source):
            raise ManifestError(f"line {number}: {source!r} is not a third-party source")
        for name in names:
            if name in owners:
                raise ManifestError(f"line {number}: skill {name!r} is already listed under {owners[name]!r}")
            owners[name] = source
        manifest[source] = sorted(names)
    return manifest


def format_manifest(manifest: Manifest) -> str:
    """Return deterministic manifest text: the header, then one sorted line per source."""
    lines = [f"{source}  {' '.join(sorted(names))}" for source, names in sorted(manifest.items())]
    return HEADER + "\n" + "\n".join(lines) + ("\n" if lines else "")


def pairs(manifest: Manifest) -> set[tuple[str, str]]:
    return {(source, name) for source, names in manifest.items() for name in names}


def diff(manifest: Manifest, lock: Manifest) -> list[str]:
    """Return one line per disagreement. `+` is only in the lock; `-` is only in the manifest."""
    wanted, installed = pairs(manifest), pairs(lock)
    lines = [f"+ {source} {name}   (installed, not in manifest)" for source, name in sorted(installed - wanted)]
    lines += [f"- {source} {name}   (in manifest, not installed)" for source, name in sorted(wanted - installed)]
    return lines


def install_command(source: str, names: Sequence[str]) -> list[str]:
    # --skill takes many names and reads until the next flag, so it goes last.
    return ["npx", "--yes", "skills@latest", "add", source, "-g", "-a", *AGENTS, "-y", "--skill", *names]


def run_command(command: list[str]) -> int:
    return subprocess.run(command, stdin=subprocess.DEVNULL, check=False).returncode


def read_lock(path: Path, require_github: bool = False) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"lock not found: {path}")
    return parse_lock(path.read_text(encoding="utf-8"), require_github=require_github)


def read_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    return parse_manifest(path.read_text(encoding="utf-8"))


def cmd_export(args: argparse.Namespace) -> int:
    lock = read_lock(args.lock, require_github=True)
    args.manifest.write_text(format_manifest(lock), encoding="utf-8")
    count = sum(len(names) for names in lock.values())
    print(f"Wrote {count} skills from {len(lock)} sources to {args.manifest}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    problems = diff(read_manifest(args.manifest), read_lock(args.lock))
    if problems:
        print(f"Third-party skills manifest and lock disagree ({args.manifest} vs {args.lock}):", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print(f"Fix: run `{SCRIPT_COMMAND} export` or `{SCRIPT_COMMAND} install`.", file=sys.stderr)
        return 1
    print(f"Third-party skills manifest matches the lock ({len(pairs(read_manifest(args.manifest)))} skills).")
    return 0


def cmd_install(args: argparse.Namespace, runner: Runner = run_command) -> int:
    manifest = read_manifest(args.manifest)
    failed: list[str] = []
    for source, names in sorted(manifest.items()):
        command = install_command(source, names)
        print(("[dry-run] " if args.dry_run else "+ ") + " ".join(command), flush=True)
        if not args.dry_run and runner(command) != 0:
            failed.append(source)
    verb = "would run" if args.dry_run else "ran"
    total = len(pairs(manifest))
    print(f"Third-party skills: {verb} {len(manifest)} install commands for {total} skills.")
    if failed:
        print(f"Install failed for: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--lock", type=Path, default=None, help=f"skills CLI lock for export and check (default: {default_lock_path()})"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="manifest (default: %(default)s)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("export", help="rewrite the manifest from the lock")
    commands.add_parser("check", help="exit 1 when the manifest and the lock disagree")
    install = commands.add_parser("install", help="run `npx skills add` for every manifest source")
    install.add_argument("--dry-run", action="store_true", help="print the commands; do not run them")
    return parser


def main(argv: Sequence[str] | None = None, runner: Runner = run_command) -> int:
    args = build_parser().parse_args(argv)
    if args.lock is None:
        args.lock = default_lock_path()
    try:
        if args.command == "export":
            return cmd_export(args)
        if args.command == "check":
            return cmd_check(args)
        return cmd_install(args, runner)
    except (ManifestError, OSError) as error:
        print(f"third_party_skills: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
