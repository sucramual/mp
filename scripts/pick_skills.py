#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["questionary==2.1.1"]
# ///
"""Choose the skills that link_skills.py links on this machine, in a questionary checklist.

`link_skills.py --pick` runs this file through `uv run --script`, so link_skills.py itself stays stdlib-only.
The checklist starts from the selection file, or from every skill when the file is missing.
Keys (questionary's, with its search filter on): up and down move, space toggles, ctrl-a toggles all,
ctrl-i (tab) inverts, typing filters by name, backspace edits the filter, enter saves.
Enter writes the selection file, then runs the normal link. Ctrl-C cancels and changes nothing.
With --dry-run, it writes no file and prints what the link would change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import questionary  # noqa: E402
from link_skills import (  # noqa: E402
    REPO_ROOT,
    Linker,
    checkout_error,
    description,
    managed_skills,
    read_selection,
    selection_path,
    write_selection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose the skills to link on this machine, then link them.")
    parser.add_argument("--dry-run", action="store_true", help="write no file, and print what would change")
    dry_run = parser.parse_args().dry_run
    error = checkout_error()
    if error:
        print(f"pick_skills.py: {error}", file=sys.stderr)
        return 2
    skills_dir = REPO_ROOT / "skills"
    names = managed_skills(skills_dir)
    source = selection_path()
    selection = read_selection(source)
    choices = [
        questionary.Choice(
            name,
            checked=selection is None or name in selection,
            description=description(skills_dir / name / "SKILL.md") or None,
        )
        for name in names
    ]
    chosen = questionary.checkbox(
        "Select skills to link", choices=choices, use_search_filter=True, use_jk_keys=False
    ).ask()
    if chosen is None:
        print("cancelled, nothing changed")
        return 0
    if not dry_run:
        write_selection(source, chosen)
        print(f"saved {len(chosen)} of {len(names)} skills to {source}")
    return Linker(dry_run, chosen, source).run()


if __name__ == "__main__":
    sys.exit(main())
