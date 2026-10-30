"""Claude Code @-imports in the global rules, agents/global.md, must resolve to files under agents/.

Claude Code skips an import whose target is missing and reports nothing,
so a renamed guidance file stops loading without a visible failure.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_RULES = REPO_ROOT / "agents" / "global.md"
# ~/.agent-guidance is the installed symlink to agents/.
IMPORT = re.compile(r"^@~/\.agent-guidance/(?P<path>\S+)\s*$", re.M)


def guidance_imports() -> list[str]:
    return IMPORT.findall(GLOBAL_RULES.read_text(encoding="utf-8"))


def test_global_rules_import_the_pinned_vocabulary() -> None:
    assert "vocabulary.md" in guidance_imports(), "agents/global.md should import agents/vocabulary.md for Claude Code"


def test_every_guidance_import_resolves_to_a_file() -> None:
    imports = guidance_imports()
    assert imports, "agents/global.md should contain at least one @~/.agent-guidance import"
    missing = [path for path in imports if not (REPO_ROOT / "agents" / path).is_file()]
    assert not missing, f"imports with no file under agents/: {missing}"
