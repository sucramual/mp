"""Checks the /rootcause skill's machine-read fields and the integrity of its eval fixtures.

Loaders read the frontmatter. The paired eval cases only mean something while each case's
change.diff still applies to its fixture repository, so a fixture edit that breaks a diff fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv
from skill_text import read_lines

SKILL_DIR = REPO_ROOT / "skills" / "rootcause"
SKILL = SKILL_DIR / "SKILL.md"
DIFF_CASES = sorted(
    path.parent.parent.name for path in (SKILL_DIR / "evals" / "behaviour").glob("*/inputs/change.diff")
)


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
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /rootcause to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"


def test_the_paired_cases_have_diffs() -> None:
    assert {"masks-symptom", "fixes-cause", "no-reproduction"} <= set(DIFF_CASES), "a behaviour case lost its diff"


@pytest.mark.parametrize("case", DIFF_CASES)
def test_change_diff_applies_to_the_scaffolded_fixture(case: str, isolated_env: IsolatedEnv, run_tool) -> None:
    workspace = isolated_env.root / "workspace"
    workspace.mkdir()
    scaffold = SKILL_DIR / "evals" / "behaviour" / case / "scaffold.sh"

    scaffolded = run_tool(["bash", scaffold], cwd=workspace)
    assert scaffolded.returncode == 0, f"scaffold.sh failed for {case}: {scaffolded.stderr}"
    assert (workspace / "change.diff").is_file(), "the scaffold should copy the case's change.diff"

    applied = run_tool(["git", "apply", "--check", "change.diff"], cwd=workspace)
    assert applied.returncode == 0, f"change.diff no longer applies to the {case} fixture: {applied.stderr}"
