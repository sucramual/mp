"""Checks the /bro skill's machine-read fields.

Loaders read the frontmatter. The tests do not check the brief's wording, which the skill's evals cover.
"""

from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT
from skill_text import read_lines

SKILL_DIR = REPO_ROOT / "skills" / "bro"
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
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /bro to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"
