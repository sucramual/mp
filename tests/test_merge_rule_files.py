"""Checks that an agent cannot merge an edit to the rules that decide when an agent may merge.

The controller may merge its own all-edges dotfiles PR, and /rogue may merge low and medium tiers.
Both exceptions must exclude a PR that changes a merge-rule file, or an agent could widen its own
merge authority and then merge that change. pr-review.md and the /rogue reserved paths each list the
files. A file missing from one list, or a listed path that no longer exists, lets such a PR merge.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, read_lines

CONTROLLER_GUIDE = REPO_ROOT / "agents" / "guides" / "pr-review.md"
ROGUE_SKILL = REPO_ROOT / "skills" / "rogue" / "SKILL.md"
NEO_SKILL = REPO_ROOT / "skills" / "neo" / "SKILL.md"
GLOBAL_RULES = REPO_ROOT / "AGENTS.md"
GIT_GUIDE = REPO_ROOT / "agents" / "guides" / "git-and-worktrees.md"

CONTROLLER_HEADING = "### Merge-rule files"
ROGUE_ITEM = "- Merge and authority rules in `sucramual/mp`"
PATH_BULLET = re.compile(r"^\s*- `([^`]+)`")


def listed_paths(path: Path, start: str) -> list[str]:
    """Return the backticked path of each bullet in the block that starts at the line holding ``start``.

    Lines before the first path bullet are skipped. The block ends at the next line that is not a path bullet.
    """
    lines = read_lines(path)
    starts = [number for number, line in enumerate(lines) if start in line]
    assert len(starts) == 1, f"{path.name} should have exactly one line with {start!r}"
    paths: list[str] = []
    for line in lines[starts[0] + 1 :]:
        match = PATH_BULLET.match(line)
        if match:
            paths.append(match.group(1))
        elif paths:
            break
    return paths


def controller_list() -> list[str]:
    return listed_paths(CONTROLLER_GUIDE, CONTROLLER_HEADING)


def rogue_list() -> list[str]:
    return listed_paths(ROGUE_SKILL, ROGUE_ITEM)


@pytest.mark.parametrize("paths", [controller_list, rogue_list], ids=["pr-review", "rogue"])
def test_each_list_names_existing_files_and_itself(paths: Callable[[], list[str]]) -> None:
    listed = paths()
    assert listed, "an empty list reserves nothing"
    for path in listed:
        assert (REPO_ROOT / path).is_file(), f"{path} does not exist, so the file it was renamed to is not reserved"
    for path in (
        "AGENTS.md",
        "agents/global.md",
        "agents/guides/pr-review.md",
        "skills/rogue/SKILL.md",
        "skills/neo/SKILL.md",
        "skills/review-pr/references/risk-tiers.md",
        "agents/guides/self-repair.md",
    ):
        assert path in listed, f"the list should reserve {path}, or an agent can edit the rule and merge the edit"


def test_both_lists_name_the_same_files() -> None:
    assert sorted(controller_list()) == sorted(rogue_list()), "a file on one list only can merge under the other rule"


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        (CONTROLLER_GUIDE, "The PR changes no file in [Merge-rule files](#merge-rule-files)."),
        (
            GLOBAL_RULES,
            "unless the PR changes a file that [PR review](agents/guides/pr-review.md#merge-rule-files) lists",
        ),
        (GIT_GUIDE, "unless the PR changes a file that [PR review](pr-review.md#merge-rule-files) lists"),
        (ROGUE_SKILL, "and the merge and authority rules that [Repository specifics]"),
        (
            NEO_SKILL,
            "each file that [Merge-rule files]"
            "(https://github.com/sucramual/mp/blob/main/agents/guides/pr-review.md#merge-rule-files) lists",
        ),
    ],
)
def test_self_merge_exception_excludes_merge_rule_files(path: Path, needle: str) -> None:
    assert_contains(path, needle, f"{path.name} should keep merge-rule changes out of agent merges")
