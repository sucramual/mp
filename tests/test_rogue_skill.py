"""Checks the /rogue skill's machine-read fields and the lines whose loss allows an unsafe unattended action.

/rogue runs without Marcus watching and may merge, revert, and message. Each phrase below guards one
such action. The tests do not check workflow wording that an agent can rephrase safely.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, assert_not_contains, read_lines

SKILL_DIR = REPO_ROOT / "skills" / "rogue"
SKILL = SKILL_DIR / "SKILL.md"
RESERVED_LINE = "Always reserved for Marcus"


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
    assert frontmatter(SKILL).get("name") == SKILL_DIR.name, "loaders map /rogue to the skill through its name"


def test_description_is_a_valid_trigger() -> None:
    description = frontmatter(SKILL).get("description", "")

    assert description, "a skill without a description never triggers"
    assert len(description) <= 1024, "loaders reject a description over 1024 characters"
    assert "<" not in description and ">" not in description, "loaders reject angle brackets in a description"
    for phrase in ("/rogue", "go rogue", "end to end"):
        assert phrase in description.lower(), f"the description should trigger on {phrase!r}"


def test_every_local_link_resolves() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_guidance_links", REPO_ROOT / "scripts" / "check_guidance_links.py"
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    assert checker.check_document(SKILL, REPO_ROOT) == [], "a dangling link hides the proof gates from the agent"


def test_the_skill_is_one_file() -> None:
    # Bug caught: a leftover reference folder holds rules that SKILL.md no longer loads, so they look live but are not.
    assert not (SKILL_DIR / "references").exists(), "/rogue keeps every rule in SKILL.md"


@pytest.mark.parametrize(
    "item",
    [
        "outside Marcus's team",
        "production data",
        "money",
        "shared infrastructure applies",
        "auth, IAM, secrets, CI workflow, or infra paths",
    ],
)
def test_reserved_line_names_each_reserved_item(item: str) -> None:
    lines = [line for line in read_lines(SKILL) if RESERVED_LINE in line]

    assert len(lines) == 1, f"SKILL.md should have exactly one '{RESERVED_LINE}' line"
    assert item in lines[0], f"the reserved line should keep {item!r}, so no grant can cover it"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        (
            "Silence, a timeout, or a missing check is never proof.",
            "a timeout, a missing check, or no reply must not unlock the next step",
        ),
        (
            "If one fails, stop and list each fix.",
            "a run must not start unattended work without gh, the ticket, or a clean feature branch",
        ),
        (
            "before any work. If the write fails, stop.",
            "a resumed run must read its grants from the ticket, because chat approvals do not survive a resume",
        ),
        (
            "re-read it and run the preflight again before you act",
            "a woken run must not act on a chat approval or an expired credential from before the park",
        ),
        (
            "Never weaken, skip, delete, or edit a test, CI check, or evaluator to make a step pass.",
            "a run must not make a step pass by changing what judges it",
        ),
        (
            "Remove a test only when the contract's declared test removals list it.",
            "only Marcus's intake approval may remove a test (#245)",
        ),
        ("Revert only merges that this run made.", "the revert grant must not cover other people's merges"),
        (
            "High tier or a reserved path: do not merge; park the PR.",
            "a high-risk or reserved change must wait for Marcus",
        ),
        (
            "Merge only on `ready`. Park `ready with gaps` and `not ready`",
            "a PR without reviewer coverage or CI on its head must not merge unattended",
        ),
        (
            "If the head differs from the step 3 SHA, run step 3 again on the current head",
            "a merge must not rely on review proof from an older head",
        ),
        ("--match-head-commit <reviewed SHA>", "a merge must be pinned to the commit that the review covered"),
        ("-f sha=<reviewed SHA>", "the REST merge must carry the same pin"),
        ("`expectedHeadOid` set to the reviewed SHA", "a queued merge must be pinned to the reviewed commit"),
        ("Never pass `--admin` or `--auto`.", "a merge must not bypass branch protection"),
        (
            "Never resolve review threads yourself to unblock a merge.",
            "a merge must not skip open review feedback",
        ),
        (
            "If `headRefOid` differs from the reviewed SHA, the merge is not covered by review",
            "a merge on a head that nobody reviewed must not count as reviewed",
        ),
        (
            'A "merged" report from Marcus or from chat is not proof.',
            "only the GitHub receipt proves a merge (ENG-2655)",
        ),
        ("Never use `gh stack merge`.", "gh stack merge has no head pin"),
        (
            "A layer whose head moved after a rebase needs step 3 and step 4 again on its new head.",
            "a rebased layer must not merge on proof for its old head",
        ),
        (
            "A high-tier layer or a reserved path parks that layer and every layer above it.",
            "a risky layer must not let the layers above it merge",
        ),
        (
            "Never confirm, apply, or discard a Spacelift run.",
            "infrastructure applies stay with Marcus",
        ),
        (
            "If the plans differ, or the run is for another SHA, stop loud and send no confirm link.",
            "Marcus's one-click confirm must only ever apply the plan that the review covered",
        ),
        (
            "Queue a Spacelift PR only through `open-pr`'s merge-queue rule for Marcus's Spacelift PRs",
            "an infra PR may merge only through the pinned queue path that Marcus authorized",
        ),
        (
            "every affected stack waits for a confirm before it applies",
            "a stack that applies on merge would apply without Marcus's confirm",
        ),
        (
            "Every other change in the PR keeps the tier gate and the reserved paths.",
            "high-tier application code in a Terraform PR must not merge under the Spacelift exception",
        ),
        ("Marcus still confirms every apply.", "queuing an infra PR must never let the run apply infrastructure"),
        (
            "A ticket that the GitHub integration closed is not proof.",
            "a merge-closed ticket must not stand in for the done-checks",
        ),
    ],
)
def test_safety_line(needle: str, message: str) -> None:
    assert_contains(SKILL, needle, message)


@pytest.mark.parametrize("command", ["ro round", "ro test-integrity", "ro record", "ro auth", "ro run"])
def test_the_skill_calls_no_ro_command(command: str) -> None:
    # Bug caught: a leftover ro call stops the run on a host where ro is no longer installed.
    assert_not_contains(SKILL, command, f"/rogue should use gh and git, not `{command}`")
