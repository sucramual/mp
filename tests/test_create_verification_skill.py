"""Checks that skills/create-verification-skill keeps its files, platform profiles, and key phrases."""

from __future__ import annotations

import pytest
from conftest import REPO_ROOT
from skill_text import assert_contains, assert_not_contains

SKILL_DIR = REPO_ROOT / "skills" / "create-verification-skill"
SKILL = "SKILL.md"
PLATFORMS = "references/platforms.yaml"
METADATA = "agents/openai.yaml"
LICENSE = "LICENSE"


@pytest.mark.parametrize(
    ("relative_path", "message"),
    [
        pytest.param(SKILL, "create-verification-skill should exist", id=SKILL),
        pytest.param(LICENSE, "the upstream MIT license should be retained", id=LICENSE),
        pytest.param(METADATA, "Codex invocation policy should be declared", id=METADATA),
        pytest.param(PLATFORMS, "platform profiles should exist", id=PLATFORMS),
        pytest.param(
            "references/feature-map-example/README.md",
            "the feature-map example should be retained",
            id="feature-map-example/README.md",
        ),
        pytest.param(
            "references/feature-map-example/create-note.md",
            "the create-note example should be retained",
            id="feature-map-example/create-note.md",
        ),
        pytest.param(
            "references/feature-map-example/search.md",
            "the search example should be retained",
            id="feature-map-example/search.md",
        ),
    ],
)
def test_file_exists(relative_path: str, message: str) -> None:
    assert (SKILL_DIR / relative_path).is_file(), message


@pytest.mark.parametrize(
    ("relative_path", "needle", "message"),
    [
        (SKILL, "name: create-verification-skill", "skill name should match its directory"),
        (SKILL, "references/platforms.yaml", "the workflow should load platform profiles"),
        (SKILL, "default to the `codex` profile", "Codex should be the fallback platform"),
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
        (".cursor/skills/verify-<app>", "the main workflow should not hard-code Cursor output"),
        ("/maintain-verification-skill", "the main workflow should not hard-code slash invocation"),
    ],
)
def test_skill_does_not_contain(needle: str, message: str) -> None:
    assert_not_contains(SKILL_DIR / SKILL, needle, message)
