"""Checks that open-pr is the one way to publish a dotfiles PR, and that the guidance says so."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_before, assert_contains, assert_not_contains

SKILL = REPO_ROOT / "skills" / "open-pr" / "SKILL.md"
DOTFILES_REF = REPO_ROOT / "skills" / "open-pr" / "references" / "dotfiles.md"
# These phrases moved to the reference, which SKILL.md tells the agent to read before step 1.
_IN_SKILL = (
    "## Dotfiles repository",
    "Skip this section outside the dotfiles repository",
    'DOTFILES_PR="$(git rev-parse --show-toplevel)/tools/dotfiles-pr/bin/dotfiles-pr"',
    "read `references/dotfiles.md` before step 1",
)
GLOBAL_RULES = REPO_ROOT / "AGENTS.md"
GIT_GUIDE = REPO_ROOT / "agents" / "guides" / "git-and-worktrees.md"
TOOL_README = REPO_ROOT / "tools" / "dotfiles-pr" / "README.md"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("## Dotfiles repository", "open-pr should have a dotfiles section"),
        ("read `references/dotfiles.md` before step 1", "open-pr should point at the dotfiles reference"),
        ("Skip this section outside the dotfiles repository", "the dotfiles section should be conditional"),
        (
            'DOTFILES_PR="$(git rev-parse --show-toplevel)/tools/dotfiles-pr/bin/dotfiles-pr"',
            "open-pr should detect dotfiles from the tool in the repository root",
        ),
        (
            "Do not run your own `git commit`, `git push`, or `gh pr create` there",
            "open-pr should not duplicate the work of ship in dotfiles",
        ),
        ("do the inspection and build the intended file list, but do not stage or commit", "ship should commit"),
        (
            "stop and ask when any changed or untracked path is not in the intended list",
            "open-pr should stop before ship commits an unrelated path",
        ),
        ("a force-push, which `ship` never does", "open-pr should not rebase a pushed branch in dotfiles"),
        ("Save the description to a file outside the worktree", "ship must not commit the PR body file"),
        (
            '"$DOTFILES_PR" ship "<conventional commit message>" --body-file <file>',
            "open-pr should publish through ship in dotfiles",
        ),
        ("If `ship` fails", "open-pr should stop when ship fails"),
        ("**Step 9:** run it as written", "open-pr should start review-pr in dotfiles too"),
    ],
)
def test_skill_contains(needle: str, message: str) -> None:
    assert_contains(SKILL if needle in _IN_SKILL else DOTFILES_REF, needle, message)


def test_skill_dotfiles_section_comes_before_the_steps() -> None:
    assert_before(
        SKILL,
        "## Dotfiles repository",
        "1. **Resolve the target base and branch safety.**",
        "the dotfiles changes should be read before the steps",
    )


@pytest.mark.parametrize("path", [GLOBAL_RULES, GIT_GUIDE])
def test_guidance_publishes_with_open_pr(path: Path) -> None:
    assert_contains(path, "dotfiles-pr start", f"{path.name} should keep dotfiles-pr start as the first step")
    assert_contains(path, "with the `open-pr` skill from that worktree", f"{path.name} should publish with open-pr")
    assert_contains(path, "Do not run `dotfiles-pr ship` alone", f"{path.name} should forbid a bare ship")
    assert_not_contains(
        path, 'run `dotfiles-pr ship "<conventional commit message>"', f"{path.name} should not say to run ship"
    )
    assert_contains(
        path,
        "The one exception: the main agent may merge after an all-edges review round",
        f"{path.name} should keep the merge exception",
    )


def test_tool_readme_points_agents_to_open_pr() -> None:
    assert_contains(TOOL_README, "Agents publish through the `open-pr` skill", "the tool README should name open-pr")
