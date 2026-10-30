"""Checks the /retro skill's machine-read fields and its report-only rule.

Loaders read the frontmatter. The evals in skills/retro/evals cover what the skill makes an agent find and report.
"""

from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT
from skill_text import assert_contains, read_lines

SKILL_DIR = REPO_ROOT / "skills" / "retro"
SKILL = SKILL_DIR / "SKILL.md"


def frontmatter(path: Path) -> dict[str, str]:
    """Parse the leading ``---`` block of single-line ``key: value`` fields, as skill loaders read it."""
    lines = read_lines(path)
    assert lines[0] == "---", f"{path.name} should start with a frontmatter fence"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        assert separator, f"frontmatter line should be 'key: value': {line!r}"
        fields[key.strip()] = value.strip()
    return fields


def test_name_matches_the_directory() -> None:
    """Bug: a renamed folder or a typo in name, so /retro loads nothing."""
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /retro to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    """Bug: an empty, over-long, or angle-bracketed description, which loaders drop or reject."""
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"


def test_description_names_its_triggers_and_its_neighbours() -> None:
    """Bug: an edit drops a trigger phrase, or the pointers that keep diff and PR reviews with age and review-pr."""
    description = frontmatter(SKILL).get("description", "")

    for phrase in ("retro", "review these runs", "why did the agent get stuck", "which calls keep failing"):
        assert phrase in description, f"the description should name the trigger {phrase!r}"
    assert "(age)" in description and "(review-pr)" in description, "the description should route reviews away"


def test_skill_stays_report_only() -> None:
    """Bug: an edit drops the rule, and a retro run edits skills or opens PRs that Marcus did not decide on."""
    assert_contains(
        SKILL, "Report only: never edit a skill or a setting, and never open a PR.", "retro must only report"
    )
