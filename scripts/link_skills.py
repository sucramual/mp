#!/usr/bin/env python3
"""Link the skills in this repository into ~/.agents/skills and ~/.claude/skills.

`npx skills add` installs a snapshot copy, so a merged edit to a skill never goes live.
This script replaces those copies with symlinks to the live checkout:

  ~/.agents/skills/<name>  ->  <repo>/skills/<name>        (Codex and Cursor read this folder)
  ~/.claude/skills/<name>  ->  ~/.agents/skills/<name>      (absolute; Claude Code reads only this folder)

A name is MANAGED when <repo>/skills/<name>/SKILL.md exists in the working tree.
The script handles only managed names, plus the retired links described below.

Managed name, in ~/.agents/skills:
  - Our link (its written target is <repo>/skills/<name>) stays, or is replaced when it dangles.
  - Any other link is left alone, with a warning (a conflict).
  - A real file or directory is moved aside, then the link is created. The script does not compare it.
Managed name, in ~/.claude/skills (only when the script owns the agents entry):
  - A live link to the agents entry or to the skill stays. Our dangling link is replaced.
  - A real entry is moved aside, then the link is created. Any other link is a conflict.
Retired name (not managed): a link at ~/.agents/skills/<name> whose written target is the same name's
missing <repo>/skills/<name> is removed, with the matching Claude link. A real directory is never touched.

Moved entries go to <backup>/agents/<name>.<UTC timestamp> and <backup>/claude/<name>.<UTC timestamp>.
Each run deletes backups older than 30 days. It ignores any entry that does not match that name pattern.
The backup folder is $XDG_STATE_HOME/dotfiles/skill-backups, or ~/.local/state/dotfiles/skill-backups.
Exit status: 0 when done, 1 when a conflict needs a manual fix, 2 for a usage or git error.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAMP = "%Y%m%dT%H%M%SZ"
KEEP_DAYS = 30
BACKUP_NAME = re.compile(r"^.+\.(\d{8}T\d{6}Z)(\.\d+)?$")


def written_target(link: Path) -> Path:
    """Return the absolute path that the link names, without following further links."""
    return Path(os.path.abspath(link.parent / os.readlink(link)))


class Linker:
    def __init__(self, dry_run: bool) -> None:
        state = os.environ.get("XDG_STATE_HOME")
        self.skills_dir = REPO_ROOT / "skills"
        self.agents = Path.home() / ".agents" / "skills"
        self.claude = Path.home() / ".claude" / "skills"
        self.backup = (Path(state) if state else Path.home() / ".local" / "state") / "dotfiles" / "skill-backups"
        self.dry_run = dry_run
        self.conflicts = 0

    def say(self, text: str) -> None:
        print(("dry run: " if self.dry_run else "") + text, flush=True)

    def warn(self, text: str) -> None:
        self.conflicts += 1
        print(f"warning: {text}", file=sys.stderr, flush=True)

    def link(self, target: Path, entry: Path) -> None:
        if not self.dry_run:
            entry.symlink_to(target)

    def unlink(self, entry: Path) -> None:
        if not self.dry_run:
            entry.unlink()

    def owned_link(self, entry: Path, name: str, *also: Path) -> bool:
        """Return True when entry is a link whose written target is skills/<name> (or one of `also`)."""
        return entry.is_symlink() and written_target(entry) in (self.skills_dir / name, *also)

    def move_aside(self, entry: Path, kind: str) -> None:
        """Move a real entry to <backup>/<kind>/<name>.<timestamp>, adding .1, .2 on a collision."""
        base = self.backup / kind / f"{entry.name}.{datetime.now(UTC).strftime(STAMP)}"
        target, count = base, 0
        while os.path.lexists(target):
            count += 1
            target = Path(f"{base}.{count}")
        if not self.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target))
        self.say(f"moved {entry} to {target}")

    def place(self, target: Path, entry: Path, said: str) -> None:
        """Create the link at entry, then report it."""
        self.link(target, entry)
        self.say(said)

    def link_agents(self, name: str) -> bool:
        """Make the agents entry our link. Return True when it is now (or in a dry run, would be) that link."""
        entry = self.agents / name
        said = f"linked {name}"
        if entry.is_symlink():
            if not self.owned_link(entry, name):
                self.warn(f"{entry} points to {written_target(entry)}; remove it to link")
                return False
            if entry.exists():
                return True
            self.unlink(entry)
            said = f"replaced link for {name}"
        elif os.path.lexists(entry):
            self.move_aside(entry, "agents")
        self.place(self.skills_dir / name, entry, said)
        return True

    def link_claude(self, name: str) -> None:
        agents_entry = self.agents / name
        entry = self.claude / name
        said = f"linked {name} (claude)"
        if entry.is_symlink():
            if entry.exists() and entry.resolve() in {agents_entry.resolve(), (self.skills_dir / name).resolve()}:
                return
            if not self.owned_link(entry, name, agents_entry):
                self.warn(f"{entry} points to {written_target(entry)}; remove it to link")
                return
            self.unlink(entry)
            said = f"replaced link for {name} (claude)"
        elif os.path.lexists(entry):
            self.move_aside(entry, "claude")
        self.place(agents_entry, entry, said)

    def prune(self, current: set[str]) -> None:
        """Remove links of retired skills: a link to the same name's missing skills/<name>."""
        for entry in sorted(self.agents.iterdir()) if self.agents.is_dir() else []:
            name = entry.name
            if name in current or entry.exists() or not self.owned_link(entry, name):
                continue
            self.unlink(entry)
            self.say(f"removed link for {name}")
            claude_entry = self.claude / name
            if self.owned_link(claude_entry, name, entry):
                self.unlink(claude_entry)
                self.say(f"removed link for {name} (claude)")

    def sweep(self) -> None:
        """Delete backups older than KEEP_DAYS. Entries that do not match the backup name pattern stay."""
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=KEEP_DAYS)
        for kind in ("agents", "claude"):
            folder = self.backup / kind
            for entry in sorted(folder.iterdir()) if folder.is_dir() else []:
                match = BACKUP_NAME.match(entry.name)
                if not match or datetime.strptime(match.group(1), STAMP) >= cutoff:
                    continue
                if not self.dry_run:
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                self.say(f"removed backup {entry}")

    def run(self) -> int:
        if not self.dry_run:
            self.agents.mkdir(parents=True, exist_ok=True)
            self.claude.mkdir(parents=True, exist_ok=True)
        current = (
            sorted(p.name for p in self.skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
            if self.skills_dir.is_dir()
            else []
        )
        for name in current:
            if self.link_agents(name):
                self.link_claude(name)
        self.prune(set(current))
        self.sweep()
        return 1 if self.conflicts else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Link this repository's skills into ~/.agents/skills and ~/.claude/skills."
    )
    parser.add_argument("--dry-run", action="store_true", help="print the changes, and change nothing")
    dry_run = parser.parse_args(argv).dry_run
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if out.returncode != 0:
        print(f"link_skills.py: {REPO_ROOT} is not a usable git repository", file=sys.stderr)
        return 2
    git_dir, common_dir = out.stdout.split()
    # Links into a scratch worktree dangle once the worktree is pruned, so link only the main checkout.
    if Path(git_dir).resolve() != Path(common_dir).resolve():
        print(
            f"link_skills.py: {REPO_ROOT} is a linked worktree; run the main checkout's copy instead", file=sys.stderr
        )
        return 2
    return Linker(dry_run).run()


if __name__ == "__main__":
    sys.exit(main())
