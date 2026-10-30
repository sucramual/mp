"""Tests for the worktree cleanup rules in agents/guides/git-and-worktrees.md.

`bu prune` is the only worktree remover. The guide must name it and forbid forced removal.
"""

from __future__ import annotations

from conftest import REPO_ROOT
from skill_text import assert_contains

GIT_GUIDE = REPO_ROOT / "agents" / "guides" / "git-and-worktrees.md"


def test_git_guide_names_bu_prune_and_forbids_forced_removal():
    assert_contains(
        GIT_GUIDE,
        "Never `rm -rf` a worktree or use `git worktree remove --force` for cleanup.",
        "the Git guide should forbid rm -rf and git worktree remove --force for worktree cleanup",
    )
    assert_contains(
        GIT_GUIDE,
        "Clean up worktrees with `bu prune --dry-run`, then `bu prune`.",
        "the Git guide should name bu prune --dry-run as the way to clean up worktrees",
    )
