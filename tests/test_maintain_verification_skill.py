"""Checks that skills/maintain-verification-skill keeps its files, platform profiles, and key phrases."""

from __future__ import annotations

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, assert_not_contains

SKILL_DIR = REPO_ROOT / "skills" / "maintain-verification-skill"
SKILL = "SKILL.md"
PLATFORMS = "references/platforms.yaml"
METADATA = "agents/openai.yaml"
LICENSE = "LICENSE"


@pytest.mark.parametrize(
    ("relative_path", "message"),
    [
        pytest.param(SKILL, "maintain-verification-skill should exist", id=SKILL),
        pytest.param(LICENSE, "the upstream MIT license should be retained", id=LICENSE),
        pytest.param(METADATA, "Codex invocation policy should be declared", id=METADATA),
        pytest.param(PLATFORMS, "platform profiles should exist", id=PLATFORMS),
    ],
)
def test_file_exists(relative_path: str, message: str) -> None:
    assert (SKILL_DIR / relative_path).is_file(), message


@pytest.mark.parametrize(
    ("relative_path", "needle", "message"),
    [
        (SKILL, "name: maintain-verification-skill", "skill name should match its directory"),
        (
            SKILL,
            'upstream-commit: "6714489fa233263f00e419f6cfc4759b07c81056"',
            "upstream provenance should be pinned",
        ),
        (SKILL, "references/platforms.yaml", "the workflow should load platform profiles"),
        (SKILL, "default to Audit", "unclear authorization should remain read-only"),
        (SKILL, "Never edit application code", "the workflow should not repair product code"),
        (
            SKILL,
            "Exercise every feature file at least once",
            "live coverage should include every mapped feature",
        ),
        (
            SKILL,
            "dispatch one read-only source reader per feature file",
            "source coverage should be independent when agents are available",
        ),
        (PLATFORMS, "default: codex", "the platform config should default to Codex"),
        (
            PLATFORMS,
            "project_skills_dir: .agents/skills",
            "Codex should use the Agent Skills project directory",
        ),
        (PLATFORMS, 'invocation_prefix: "$"', "Codex should use dollar skill invocation"),
        (PLATFORMS, "project_skills_dir: .cursor/skills", "Cursor should use its project skill directory"),
        (PLATFORMS, 'invocation_prefix: "/"', "Cursor should use slash skill invocation"),
        (METADATA, "allow_implicit_invocation: false", "Codex should preserve explicit-only invocation"),
        (LICENSE, "Copyright (c) 2026 Lauren Tan", "the upstream copyright should be retained"),
    ],
)
def test_contains(relative_path: str, needle: str, message: str) -> None:
    assert_contains(SKILL_DIR / relative_path, needle, message)


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("disable-model-invocation", "Cursor-only frontmatter should not remain"),
        (".cursor/skills/verify-*", "the workflow should not hard-code Cursor target discovery"),
        ("/create-verification-skill", "the workflow should not hard-code slash invocation"),
    ],
)
def test_skill_does_not_contain(needle: str, message: str) -> None:
    assert_not_contains(SKILL_DIR / SKILL, needle, message)
