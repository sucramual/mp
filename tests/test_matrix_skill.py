"""Checks the /matrix skill's machine-read fields and the lines whose loss allows an unsafe action.

/matrix starts unattended /neo workers. Each phrase below guards one such action.
The tests do not check workflow wording that an agent can rephrase safely.
"""

from __future__ import annotations

import importlib.util

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains
from test_neo_skill import frontmatter

SKILL_DIR = REPO_ROOT / "skills" / "matrix"
SKILL = SKILL_DIR / "SKILL.md"
NEO = REPO_ROOT / "skills" / "neo" / "SKILL.md"


def test_name_matches_the_directory() -> None:
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /matrix to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"
    for phrase in ("/matrix", "matrix this goal"):
        assert phrase in description.lower(), f"the description should trigger on {phrase!r}"


def test_every_local_link_resolves() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_guidance_links", REPO_ROOT / "scripts" / "check_guidance_links.py"
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    assert checker.check_document(SKILL, REPO_ROOT) == [], "a dangling link sends the router to a missing section"


def test_the_triage_script_exists() -> None:
    assert (SKILL_DIR / "scripts" / "triage.py").is_file(), "the review gate runs this script"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("Never write code", "the router must not write code, so one PR keeps one writer"),
        ("Never merge without the merge rules", "a merge must follow the rules that the neo intake reads"),
        ("Every `/neo` hard limit applies to every worker.", "workers keep the guarded-change and pinned-merge limits"),
        (
            "Never send secrets, keys, routing-key values, or code.",
            "the triage input goes to an external API",
        ),
        ("Do not start a worker until Marcus fixes it.", "workers must not start without access"),
        ("Never split a chain between two workers.", "one PR has one /neo for its whole life"),
    ],
)
def test_safety_line(needle: str, message: str) -> None:
    assert_contains(SKILL, needle, message)


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("Never start another `/neo`.", "only /matrix starts workers"),
        ("Never ask Marcus.", "a worker under /matrix sends decisions to the router"),
        ("Still read the merge rules", "a worker under /matrix must not merge without the merge rules"),
    ],
)
def test_neo_keeps_the_matrix_rules(needle: str, message: str) -> None:
    assert_contains(NEO, needle, message)


def test_llm_triage_is_the_default() -> None:
    assert_contains(SKILL, "**LLM triage** is the default.", "Marcus asked for LLM triage unless TypeSafe is opted in")
    assert_contains(SKILL, "use LLM triage. This is not an error.", "a missing TypeSafe key must not stop the gate")


# Protects: a ticket stays open until the whole goal passes. Bug caught: on 2026-11-02 a worker branch named
# after its ticket made Linear close the ticket on merge while two goal checks were still open.
@pytest.mark.parametrize(
    ("needle", "message"),
    [
        (
            "Put no ticket ID in a worker's branch name or PR title. Only you close the ticket",
            "Linear closes a ticket when a merged PR's branch name or title holds its ID",
        ),
        ("Close the ticket only when every goal check passes", "the router must not close a ticket early"),
    ],
)
def test_ticket_closes_only_with_the_goal(needle: str, message: str) -> None:
    assert_contains(SKILL, needle, message)


def test_work_orders_require_red_first_tests() -> None:
    assert_contains(
        SKILL,
        "The worker writes each test first and sees it fail before it changes the code.",
        "workers skipped red-first TDD until the brief stated it (spikes 1 and 2)",
    )
