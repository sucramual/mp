#!/usr/bin/env python3
"""Link the skills in this repository into ~/.agents/skills and ~/.claude/skills.

`npx skills add` installs a snapshot copy, so a merged edit to a skill never goes live.
This script replaces those copies with symlinks to the live checkout:

  ~/.agents/skills/<name>  ->  <repo>/skills/<name>        (Codex and Cursor read this folder)
  ~/.claude/skills/<name>  ->  ~/.agents/skills/<name>      (absolute; Claude Code reads only this folder)

A name is MANAGED when <repo>/skills/<name>/SKILL.md exists in the working tree.
The script handles only managed names, plus the retired links described below.

A managed name is SELECTED when the selection file lists it, or when the selection file is missing.
The selection file is $XDG_CONFIG_HOME/dotfiles/skills.txt (when XDG_CONFIG_HOME is absolute), else
~/.config/dotfiles/skills.txt. It is untracked and per machine: one name per line, `#` starts a comment.
It is an allowlist: a skill that a later PR adds stays unlinked until you pick it. A file with no names links nothing.
A listed name that is not managed gets a warning (a conflict). The script still links the other names.

Managed name, in ~/.agents/skills:
  - Our link (its written target is <repo>/skills/<name>) stays, or is replaced when it dangles.
  - Any other link is left alone, with a warning (a conflict).
  - A real file or directory is moved aside, then the link is created. The script does not compare it.
Managed name, in ~/.claude/skills (only when the script owns the agents entry):
  - A live link to the agents entry or to the skill stays. Our dangling link is replaced.
  - A real entry is moved aside, then the link is created. Any other link is a conflict.
Managed name that is not selected: our agents link (written target <repo>/skills/<name>) is removed, and the
  Claude link when its written target is that agents entry or the skill. Real entries and other links stay, silently.
Retired name (not managed): a link at ~/.agents/skills/<name> whose written target is the same name's
missing <repo>/skills/<name> is removed, with the matching Claude link. A real directory is never touched.

Moved entries go to <backup>/agents/<name>.<UTC timestamp> and <backup>/claude/<name>.<UTC timestamp>.
Each run deletes backups older than 30 days. It ignores any entry that does not match that name pattern.
The backup folder is $XDG_STATE_HOME/dotfiles/skill-backups, or ~/.local/state/dotfiles/skill-backups.
A run that changes something ends with one summary line, such as "Linked 2 skills, unlinked 1 skill in 4ms".
A run with no change prints nothing.

--list prints each managed skill with ● (selected) or ○ and its SKILL.md description. It changes nothing.
--pick needs a terminal and uv. It runs scripts/pick_skills.py, a questionary checklist, through `uv run --script`.
Enter saves the selection file, then links. Ctrl-C cancels and changes nothing.
With --dry-run, --pick writes no file and prints what would change.
Every mode runs only in the main checkout, not in a linked worktree.
Exit status: 0 when done, 1 when a conflict needs a manual fix, 2 for a usage or git error.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAMP = "%Y%m%dT%H%M%SZ"
KEEP_DAYS = 30
BACKUP_NAME = re.compile(r"^.+\.(\d{8}T\d{6}Z)(\.\d+)?$")
SELECTION_HEADER = "# Skills that link_skills.py links on this machine. Edit it, or run link_skills.py --pick.\n"
GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def use_colour() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def managed_skills(skills_dir: Path) -> list[str]:
    """Return the sorted names of the folders in skills_dir that hold a SKILL.md."""
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def selection_path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(config) if os.path.isabs(config) else Path.home() / ".config"
    return base / "dotfiles" / "skills.txt"


def read_selection(path: Path) -> list[str] | None:
    """Return the names that the selection file lists, in file order, or None when the file is missing."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    names = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    return [name for name in names if name]


def write_selection(path: Path, names: list[str]) -> None:
    """Write the selection file atomically: a temp file in the same folder, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".skills.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(SELECTION_HEADER + "".join(f"{name}\n" for name in sorted(names)))
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise


def description(skill_md: Path) -> str:
    """Return the first line of the `description:` value in the YAML frontmatter, or "" when there is none."""
    try:
        lines = skill_md.read_text().splitlines()
    except OSError:
        return ""
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            value = line.removeprefix("description:").strip()
            if value[:1] in (">", "|"):  # A block scalar: the text starts on the next line.
                value = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def written_target(link: Path) -> Path:
    """Return the absolute path that the link names, without following further links."""
    return Path(os.path.abspath(link.parent / os.readlink(link)))


class Linker:
    def __init__(self, dry_run: bool, selection: list[str] | None = None, source: Path | None = None) -> None:
        state = os.environ.get("XDG_STATE_HOME")
        self.skills_dir = REPO_ROOT / "skills"
        self.agents = Path.home() / ".agents" / "skills"
        self.claude = Path.home() / ".claude" / "skills"
        self.backup = (Path(state) if state else Path.home() / ".local" / "state") / "dotfiles" / "skill-backups"
        self.dry_run = dry_run
        self.selection = selection  # None means every managed skill.
        self.source = source  # The selection file, named in warnings.
        self.conflicts = 0
        self.colour = use_colour()
        self.linked: set[str] = set()
        self.unlinked: set[str] = set()
        self.moved = 0
        self.swept = 0

    def say(self, text: str, colour: str = "") -> None:
        if colour and self.colour:
            text = f"{colour}{text}{RESET}"
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
        self.moved += 1
        self.say(f"moved {entry} to {target}")

    def place(self, target: Path, entry: Path, said: str) -> None:
        """Create the link at entry, then report it."""
        self.link(target, entry)
        self.linked.add(entry.name)
        self.say(said, GREEN)

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

    def remove(self, entry: Path, said: str) -> None:
        self.unlink(entry)
        self.unlinked.add(entry.name)
        self.say(said, RED)

    def drop(self, name: str) -> None:
        """Remove our links for a managed skill that is not selected. Leave real entries and other links alone."""
        agents_entry = self.agents / name
        if self.owned_link(agents_entry, name):
            self.remove(agents_entry, f"removed link for {name}")
        claude_entry = self.claude / name
        if self.owned_link(claude_entry, name, agents_entry):
            self.remove(claude_entry, f"removed link for {name} (claude)")

    def prune(self, current: set[str]) -> None:
        """Remove links of retired skills: a link to the same name's missing skills/<name>."""
        for entry in sorted(self.agents.iterdir()) if self.agents.is_dir() else []:
            name = entry.name
            if name in current or entry.exists() or not self.owned_link(entry, name):
                continue
            self.remove(entry, f"removed link for {name}")
            claude_entry = self.claude / name
            if self.owned_link(claude_entry, name, entry):
                self.remove(claude_entry, f"removed link for {name} (claude)")

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
                self.swept += 1
                self.say(f"removed backup {entry}")

    def summary(self, started: float) -> None:
        """Print one line that counts the changes, or nothing when there were none."""
        counts = (
            (len(self.linked), "linked {}", "skill", "skills"),
            (len(self.unlinked), "unlinked {}", "skill", "skills"),
            (self.moved, "moved {} aside", "entry", "entries"),
            (self.swept, "deleted {}", "old backup", "old backups"),
        )
        parts = [form.format(f"{n} {one if n == 1 else many}") for n, form, one, many in counts if n]
        if not parts:
            return
        elapsed = time.perf_counter() - started
        took = f"{elapsed * 1000:.0f}ms" if elapsed < 1 else f"{elapsed:.2f}s"
        text = ", ".join(parts)
        self.say(f"{text[0].upper()}{text[1:]} in {took}")

    def run(self) -> int:
        started = time.perf_counter()
        if not self.dry_run:
            self.agents.mkdir(parents=True, exist_ok=True)
            self.claude.mkdir(parents=True, exist_ok=True)
        current = managed_skills(self.skills_dir)
        chosen = set(current if self.selection is None else self.selection)
        for name in sorted(chosen - set(current)):
            self.warn(f"{self.source} lists {name}, which is not a skill in {self.skills_dir}; remove it from the file")
        for name in current:
            if name not in chosen:
                self.drop(name)
            elif self.link_agents(name):
                self.link_claude(name)
        self.prune(set(current))
        self.sweep()
        self.summary(started)
        return 1 if self.conflicts else 0


def list_skills(names: list[str], selection: list[str] | None, skills_dir: Path) -> None:
    """Print one row per managed skill: ● or ○, the name, and the description, cut to the terminal width."""
    colour = use_colour()
    width = shutil.get_terminal_size().columns
    pad = max((len(name) for name in names), default=0)
    for name in names:
        on = selection is None or name in selection
        row = f"{'●' if on else '○'} {name:<{pad}}  {description(skills_dir / name / 'SKILL.md')}".rstrip()
        if len(row) > width:
            row = row[: max(width - 1, 0)] + "…"
        if colour:
            glyph, rest = row[:1], row[1:]
            row = f"{GREEN}{glyph}{RESET}{rest}" if on else f"{DIM}{row}{RESET}"
        print(row)


def checkout_error() -> str | None:
    """Return why this checkout must not link skills, or None when it is the main checkout."""
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if out.returncode != 0:
        return f"{REPO_ROOT} is not a usable git repository"
    git_dir, common_dir = out.stdout.split()
    # Links into a scratch worktree dangle once the worktree is pruned, so link only the main checkout.
    if Path(git_dir).resolve() != Path(common_dir).resolve():
        return f"{REPO_ROOT} is a linked worktree; run the main checkout's copy instead"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Link this repository's skills into ~/.agents/skills and ~/.claude/skills."
    )
    parser.add_argument("--dry-run", action="store_true", help="print the changes, and change nothing")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="list the skills and which ones are selected")
    mode.add_argument("--pick", action="store_true", help="choose the skills to link in a terminal checklist")
    args = parser.parse_args(argv)
    error = checkout_error()
    if error:
        print(f"link_skills.py: {error}", file=sys.stderr)
        return 2
    skills_dir = REPO_ROOT / "skills"
    if args.list:
        list_skills(managed_skills(skills_dir), read_selection(selection_path()), skills_dir)
        return 0
    if args.pick:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("link_skills.py: --pick needs a terminal on stdin and stdout", file=sys.stderr)
            return 2
        if not shutil.which("uv"):
            print("link_skills.py: --pick needs uv (brew install uv)", file=sys.stderr)
            return 2
        # The picker needs questionary, which uv installs from the script's PEP 723 block. This file stays stdlib-only.
        picker = str(Path(__file__).resolve().parent / "pick_skills.py")
        os.execvp("uv", ["uv", "run", "--quiet", "--script", picker, *(["--dry-run"] if args.dry_run else [])])
    return Linker(args.dry_run, read_selection(selection_path()), selection_path()).run()


if __name__ == "__main__":
    sys.exit(main())
