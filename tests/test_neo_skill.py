"""Checks the /neo skill's machine-read fields and the lines whose loss allows an unsafe unattended action.

/neo runs without Marcus watching and may merge. Each phrase below guards one such action.
The tests do not check workflow wording that an agent can rephrase safely.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, read_lines

SKILL_DIR = REPO_ROOT / "skills" / "neo"
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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def test_name_matches_the_directory() -> None:
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /neo to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"
    for phrase in ("/neo", "neo this ticket", "run this ticket end to end without me"):
        assert phrase in description.lower(), f"the description should trigger on {phrase!r}"


def test_every_local_link_resolves() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_guidance_links", REPO_ROOT / "scripts" / "check_guidance_links.py"
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    assert checker.check_document(SKILL, REPO_ROOT) == [], "a dangling link hides the merge-rule files from the agent"


GUARDED_LINE = "Irreversible or guarded changes wait for Marcus"


@pytest.mark.parametrize(
    "item",
    [
        "data",
        "migrations",
        "infra applies",
        "auth, IAM, secrets",
        "CI workflows",
        "agent settings",
        "outside his team",
        "[Merge-rule files](https://github.com/sucramual/mp/blob/main/agents/guides/pr-review.md#merge-rule-files)",
    ],
)
def test_guarded_line_names_each_guarded_item(item: str) -> None:
    lines = [line for line in read_lines(SKILL) if GUARDED_LINE in line]

    assert len(lines) == 1, f"SKILL.md should have exactly one '{GUARDED_LINE}' line"
    assert item in lines[0], f"the guarded line should keep {item!r}, so the run waits for Marcus on it"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("Never confirm, apply, or discard a Spacelift run.", "infrastructure applies stay with Marcus"),
        ("--match-head-commit <reviewed SHA>", "a merge must be pinned to the commit that the review covered"),
        ("`expectedHeadOid` set to the reviewed SHA", "a queued merge must be pinned to the reviewed commit"),
        ("Never pass `--admin`.", "a merge must not bypass branch protection"),
        ("Never use `gh stack merge`", "gh stack merge has no head pin"),
        (
            "A removed or weakened test is intended only when the ticket or the intake approved it.",
            "a run must not delete or weaken a test to pass a check (ENG-2246)",
        ),
        ('a "merged" message is not proof', "only the GitHub receipt proves a merge (ENG-2655)"),
        (
            "Done means every ticket check passes on the merged result, not that the PR merged.",
            "a merged PR must not stand in for the ticket's checks",
        ),
        (
            "[Risk tiers](https://github.com/sucramual/mp/blob/main/skills/review-pr/references/risk-tiers.md)",
            "a relative link breaks in a neo-only install, so the run cannot classify a PR's tier",
        ),
        (
            "Do not start the loop until Marcus installs them.",
            "a neo-only install must stop at intake, not improvise open-pr, review-pr, and verify",
        ),
    ],
)
def test_safety_line(needle: str, message: str) -> None:
    assert_contains(SKILL, needle, message)
