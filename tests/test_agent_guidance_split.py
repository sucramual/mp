"""Checks that the global guidance and the dotfiles-only rules stay in separate files.

agents/global.md loads in every session, through ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md.
The root AGENTS.md holds the dotfiles-only rules and the Codex GitHub reviewer's guidelines.
Codex review reads only a "## Review guidelines" section in the root AGENTS.md and does not follow links,
so the section must stay there. A copy in agents/global.md would load into every session in other repositories.
"""

from __future__ import annotations

from conftest import REPO_ROOT
from skill_text import assert_contains, read_lines

GLOBAL = REPO_ROOT / "agents" / "global.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
REVIEW_HEADING = "## Review guidelines"


def section_bullets(lines: list[str], heading: str) -> list[str]:
    start = lines.index(heading)
    bullets: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            bullets.append(line)
    return bullets


def test_root_agents_keeps_the_codex_review_guidelines() -> None:
    lines = read_lines(ROOT_AGENTS)
    assert REVIEW_HEADING in lines, "Codex review reads only the root AGENTS.md; the section must stay there"
    bullets = section_bullets(lines, REVIEW_HEADING)
    assert len(bullets) >= 5, "the review guidelines lost their rules"
    assert any("Post only Important findings" in line for line in bullets), "the severity rule must stay"
    assert_contains(
        ROOT_AGENTS,
        "[Dotfiles review policy](agents/guides/dotfiles-review.md). Keep this section in step with it.",
        "the review guidelines should keep the in-step rule with the full policy",
    )


def test_global_rules_leave_the_review_guidelines_and_publish_rules_to_the_root() -> None:
    lines = read_lines(GLOBAL)
    assert any(line.startswith("## ") for line in lines), "agents/global.md should hold the global sections"
    assert "## Working style and authority" in lines, "agents/global.md should hold the global preferences"
    assert REVIEW_HEADING not in lines, "the review guidelines would load into every session from agents/global.md"
    assert not any("The one exception: the main agent may merge" in line for line in lines), (
        "the dotfiles merge exception belongs in the root AGENTS.md, which is a merge-rule file"
    )


def test_root_agents_points_to_the_global_rules() -> None:
    assert_contains(ROOT_AGENTS, "](agents/global.md)", "a dotfiles session should find the global rules")
