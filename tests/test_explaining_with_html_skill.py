"""Checks that skills/explaining-with-html writes pages outside git worktrees.

Worktrees are deleted on merge, along with ignored files, so a page kept under `.cheese/notes/`
is lost. The skill must name the persistent folder and must not name the old worktree path.
"""

from __future__ import annotations

from conftest import REPO_ROOT
from skill_text import assert_contains, assert_not_contains

SKILL = REPO_ROOT / "skills" / "explaining-with-html" / "SKILL.md"


def test_pages_go_to_the_persistent_folder() -> None:
    assert_contains(
        SKILL,
        "~/Documents/html-pages/<repo>/<YYYY-MM-DD>-<slug>.html",
        "the skill should write pages to the persistent folder outside every worktree",
    )


def test_pages_never_overwrite_or_use_the_worktree() -> None:
    assert_contains(SKILL, "Never overwrite", "the skill should forbid overwriting an existing page")
    assert_contains(SKILL, "never into a worktree", "the skill should forbid writing into a worktree")


def test_old_worktree_output_rule_is_gone() -> None:
    assert_not_contains(SKILL, ".cheese/notes/", "the skill should not write pages under .cheese/notes/")
    assert_not_contains(SKILL, "check-ignore", "the git check-ignore step should be removed")
    assert_not_contains(SKILL, "info/exclude", "the info/exclude step should be removed")
