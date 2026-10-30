"""Checks the shared risk-tier definition and the files that rely on it to decide an agent merge.

/rogue, /neo, and the self-repair guide let an agent merge a Low or Medium PR without Marcus.
Each phrase below guards one rule whose loss lets a risky PR merge unattended.
The tests do not check wording that an agent can rephrase safely.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains

RISK_TIERS = REPO_ROOT / "skills" / "review-pr" / "references" / "risk-tiers.md"
SELF_REPAIR = REPO_ROOT / "agents" / "guides" / "self-repair.md"
ROGUE_SKILL = REPO_ROOT / "skills" / "rogue" / "SKILL.md"
NEO_SKILL = REPO_ROOT / "skills" / "neo" / "SKILL.md"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("When you are not sure, the tier is High.", "an unclear PR must not count as Low or Medium"),
        (
            "Agent instructions are High at every size",
            "a one-line prose change to agent rules must not merge unattended",
        ),
        (
            "each file that [Merge-rule files](../../../agents/guides/pr-review.md#merge-rule-files) lists",
            "a PR that changes a merge rule must park, or an agent can widen its own merge authority",
        ),
        ("When you are not sure that a path is reserved, treat it as reserved.", "an unclear path must park"),
        ("Never pass `--admin` or `--auto`.", "a merge must not bypass branch protection or skip the pin"),
        (
            "[Ready to merge](ready-to-merge.md) reports `ready` on the head",
            "a Low or Medium PR must still pass the ready check",
        ),
    ],
)
def test_risk_tiers_rule(needle: str, message: str) -> None:
    assert_contains(RISK_TIERS, needle, message)


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        (ROGUE_SKILL, "[Risk tiers](../review-pr/references/risk-tiers.md)"),
        (ROGUE_SKILL, "[Reserved paths](../review-pr/references/risk-tiers.md#reserved-paths)"),
        (NEO_SKILL, "[Risk tiers](../review-pr/references/risk-tiers.md)"),
        (SELF_REPAIR, "[Risk tiers](../../skills/review-pr/references/risk-tiers.md)"),
    ],
)
def test_merging_files_link_the_tier_definition(path: Path, needle: str) -> None:
    assert_contains(path, needle, f"{path.name} should classify the tier with the shared definition before a merge")


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        (
            "Never put the fix in the task's PR or worktree.",
            "a tooling fix must not ride in the task PR past its review",
        ),
        ("Never change it to get past it.", "an agent must not disable a guard that stopped it"),
        ("Skill and guide prose is High, so a prose fix always parks.", "a prose fix must not merge unattended"),
        ("Never weaken, skip, or delete a test.", "a fix must not pass by weakening a test"),
        ("Never pass `--auto` or `--admin`.", "a fix merge must not bypass branch protection"),
    ],
)
def test_self_repair_rule(needle: str, message: str) -> None:
    assert_contains(SELF_REPAIR, needle, message)
