"""Checks the /verify skill's machine-read fields and the lines whose loss allows an unsafe action.

/verify runs after a merge, often without Marcus watching. Each phrase below guards one action that it must
never take. The tests do not check workflow wording, which the skill's evals cover.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, read_lines

SKILL_DIR = REPO_ROOT / "skills" / "verify"
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
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /verify to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("Never confirm, apply, or discard a Spacelift run.", "infrastructure applies stay with Marcus"),
        ("Never run `spacectl stack deploy`.", "a deploy from the agent would apply infrastructure without Marcus"),
        (
            "the check fails and you send no confirm link",
            "Marcus's confirm must only ever apply the plan that the review covered",
        ),
        (
            "Never type a password.",
            "an unattended run in the signed-in verify-browser Chrome must never enter Marcus's credentials",
        ),
    ],
)
def test_safety_line(needle: str, message: str) -> None:
    assert_contains(SKILL, needle, message)
