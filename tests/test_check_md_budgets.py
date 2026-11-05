"""Command-boundary tests for the Markdown line limits."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "check_md_budgets.py"
BUDGETS = {"defaults": {"skills/*/SKILL.md": 3, "*.md": 5}, "files": {}}


def make_repo(root: Path, files: dict[str, int], budgets: dict | None = None) -> Path:
    """Write each Markdown file with the given line count, track it in git, and write the limits file."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for path, lines in files.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("".join(f"line {number}\n" for number in range(lines)))
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    limits = root.parent / "budgets.json"
    limits.write_text(json.dumps(budgets or BUDGETS))
    return limits


def run(root: Path, limits: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--budgets", str(limits)], text=True, capture_output=True, check=False
    )


def test_passes_at_the_limit_and_fails_one_line_over(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    limits = make_repo(root, {"skills/a/SKILL.md": 3, "skills/b/SKILL.md": 4})

    result = run(root, limits)

    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "skills/b/SKILL.md: 4 lines, limit 3. Replace or delete lines for the ones you add, "
        "or move detail to a references/ file."
    ]


def test_references_and_nested_files_get_the_general_limit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    limits = make_repo(root, {"skills/a/references/long.md": 5, "README.md": 5, "docs/deep/big.md": 6})

    result = run(root, limits)

    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "docs/deep/big.md: 6 lines, limit 5. Replace or delete lines for the ones you add, "
        "or move detail to a references/ file."
    ]


def test_file_entry_overrides_the_default(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    budgets = {**BUDGETS, "files": {"agents/global.md": 2, "skills/big/SKILL.md": 9}}
    limits = make_repo(root, {"agents/global.md": 3, "skills/big/SKILL.md": 9}, budgets)

    result = run(root, limits)

    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "agents/global.md: 3 lines, limit 2. Replace or delete lines for the ones you add, "
        "or move detail to a references/ file."
    ]


def test_untracked_files_are_not_checked(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    limits = make_repo(root, {"README.md": 1})
    (root / "notes.md").write_text("x\n" * 50)

    result = run(root, limits)

    assert result.returncode == 0, result.stderr


def test_entry_for_a_missing_file_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    limits = make_repo(root, {"README.md": 1}, {**BUDGETS, "files": {"gone.md": 10}})

    result = run(root, limits)

    assert result.returncode == 1
    assert "gone.md is not a tracked Markdown file" in result.stderr


def test_repository_is_within_its_limits() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr


def test_only_the_listed_skills_are_capped(tmp_path: Path) -> None:
    """Experimental skills grow freely; the agent-run skills listed in md_budgets.json stay capped."""
    budgets = json.loads((REPO_ROOT / "scripts" / "md_budgets.json").read_text())
    files = {path: 1 for path in budgets["files"]}
    files |= {"skills/experiment/SKILL.md": 400, "skills/neo/SKILL.md": 121}
    root = tmp_path / "repo"
    limits = make_repo(root, files, budgets)

    result = run(root, limits)

    assert result.returncode == 1
    assert [line.split(":")[0] for line in result.stderr.splitlines()] == ["skills/neo/SKILL.md"]
