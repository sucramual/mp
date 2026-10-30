#!/usr/bin/env python3
"""Link the tool entry points in this repository into ~/bin, or into the directory of --bin-dir.

install.sh and `dotfiles-pr sync` both run this script. So a tool that a merged PR adds is on PATH
after the next sync, and the two cannot link differently.

  <bin>/<name>  ->  <repo>/tools/<tool>/bin/<name>      (absolute; <bin> is ~/bin unless --bin-dir DIR names another)

<repo> is the checkout that holds this script. An ENTRY POINT is a file, or a link to a file, at
<repo>/tools/<tool>/bin/<name>, where neither <tool> nor <name> starts with a dot. When two tools have
an entry point with the same name, the tool that sorts last wins. "Points into" below uses the link's
written target, made absolute.

The script creates the bin directory first. Then, for each entry point name:
  - A link to the entry point stays as it is.
  - A link that points into <repo> but to another target is replaced. Examples: the tool moved to a
    new folder, or the link names an old repository layout such as <repo>/bin/<name>.
  - Anything else stays as it is, with a warning: a real file or folder, or a link that points
    outside <repo>. Remove it, then run the script again.
For each other name in the bin directory:
  - A link that points into <repo>/tools/ and whose target no longer exists is STALE and is removed.
    This is the link of a deleted or renamed entry point.
  - Everything else stays: real files, links that point outside <repo>/tools/ (also dangling links
    into <repo> outside tools/), and links into tools/ whose target still exists (an alias).

Only the main checkout links, the same rule as link_skills.py. A link into a linked worktree, such as one
that `dotfiles-pr start` makes, dangles once the worktree is pruned. So in a linked worktree the script
changes nothing: it names the main checkout's copy and exits 2.

It prints one line for each change, and nothing when the bin directory is already current.
Usage: link_tools.py [--bin-dir DIR]
Exit status: 0 when done, 1 when an entry needs a manual fix, 2 for a usage or git error, in a linked
worktree, or when the bin directory cannot be created.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def written_target(link: Path) -> Path:
    """Return the absolute path that the link names, without following further links."""
    return Path(os.path.abspath(link.parent / os.readlink(link)))


def comparable(path: Path) -> Path:
    """Resolve the folders of path but not its last part, so a dangling or linked entry point still compares."""
    return Path(os.path.realpath(path.parent)) / path.name


def entry_points(tools: Path) -> dict[str, Path]:
    """Map each entry point name to its path. Same selection as the old install.sh glob tools/*/bin/*."""
    found: dict[str, Path] = {}
    for tool in sorted(tools.iterdir()) if tools.is_dir() else []:
        bin_dir = tool / "bin"
        if tool.name.startswith(".") or not bin_dir.is_dir():
            continue
        for script in sorted(bin_dir.iterdir()):
            if not script.name.startswith(".") and script.is_file():
                found[script.name] = script
    return found


class Linker:
    def __init__(self, root: Path, bin_dir: Path) -> None:
        self.tools = root / "tools"
        self.real_root = Path(os.path.realpath(root))
        self.real_tools = self.real_root / "tools"
        self.bin = bin_dir
        self.problems = 0

    def say(self, text: str) -> None:
        print(text, flush=True)

    def warn(self, text: str) -> None:
        self.problems += 1
        print(f"warning: {text}", file=sys.stderr, flush=True)

    def show(self, path: Path) -> str:
        """Name a path in the checkout relative to the repository root, for short report lines."""
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)

    def points_into(self, entry: Path, folder: Path) -> bool:
        """True when entry is a link whose written target is inside folder."""
        return entry.is_symlink() and folder in comparable(written_target(entry)).parents

    def link(self, name: str, script: Path) -> None:
        entry = self.bin / name
        said = f"linked {entry} -> {self.show(script)}"
        try:
            if entry.is_symlink():
                if comparable(written_target(entry)) == comparable(script):
                    return
                old = written_target(entry)
                if not self.points_into(entry, self.real_root):
                    self.warn(f"{entry} points to {old}; remove it to link {self.show(script)}")
                    return
                entry.unlink()
                said = f"relinked {entry} -> {self.show(script)} (was {self.show(old)})"
            elif os.path.lexists(entry):
                self.warn(f"{entry} is a real file or folder, not a link; remove it to link {self.show(script)}")
                return
            entry.symlink_to(script)
        except OSError as error:
            self.warn(f"cannot link {entry}: {error}")
            return
        self.say(said)

    def prune(self, managed: set[str]) -> None:
        """Remove stale links: into tools/, target gone, and the name is not an entry point."""
        for entry in sorted(self.bin.iterdir()):
            if entry.name in managed or not self.points_into(entry, self.real_tools) or entry.exists():
                continue
            target = written_target(entry)
            try:
                entry.unlink()
            except OSError as error:
                self.warn(f"cannot remove stale link {entry}: {error}")
                continue
            self.say(f"removed {entry} (its target {self.show(target)} no longer exists)")

    def run(self) -> int:
        try:
            self.bin.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            print(f"link_tools.py: cannot create {self.bin}: {error}", file=sys.stderr)
            return 2
        managed = entry_points(self.tools)
        for name, script in managed.items():
            self.link(name, script)
        self.prune(set(managed))
        return 1 if self.problems else 0


def git_lines(*args: str) -> list[str] | None:
    """Run git in the checkout. Return its output lines, or None when it fails."""
    out = subprocess.run(["git", *args], cwd=REPO_ROOT, text=True, capture_output=True)
    return out.stdout.splitlines() if out.returncode == 0 else None


def main() -> int:
    args = sys.argv[1:]
    bin_dir = Path.home() / "bin"
    if len(args) == 2 and args[0] == "--bin-dir" and args[1]:
        bin_dir = Path(args[1]).expanduser()
    elif args:
        print("usage: link_tools.py [--bin-dir DIR]", file=sys.stderr)
        return 2
    dirs = git_lines("rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    if dirs is None or len(dirs) != 2:
        print(f"link_tools.py: {REPO_ROOT} is not a usable git repository", file=sys.stderr)
        return 2
    git_dir, common_dir = (Path(line).resolve() for line in dirs)
    # Links into a scratch worktree dangle once the worktree is pruned, so link only the main checkout.
    if git_dir != common_dir:
        # The first worktree that git lists is the main checkout.
        listing = git_lines("worktree", "list", "--porcelain") or []
        roots = [line[len("worktree ") :] for line in listing if line.startswith("worktree ")]
        main_copy = shlex.join(["python3", str(Path(roots[0]) / "scripts" / "link_tools.py")]) if roots else None
        print(
            f"link_tools.py: {REPO_ROOT} is a linked worktree; run {main_copy or 'the main checkout copy'} instead",
            file=sys.stderr,
        )
        return 2
    return Linker(REPO_ROOT, bin_dir).run()


if __name__ == "__main__":
    sys.exit(main())
