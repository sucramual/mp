"""Command-boundary tests for personal guidance links."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "check_guidance_links.py"


def run_checker(root: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)], cwd=cwd, text=True, capture_output=True, check=False
    )


@pytest.fixture(autouse=True)
def global_rules(tmp_path: Path) -> Path:
    """Each checked root has agents/global.md, the global rules that the checker always reads."""
    path = tmp_path / "agents" / "global.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Global.")
    return path


def test_checks_root_and_guides_with_document_relative_paths(tmp_path: Path) -> None:
    guides = tmp_path / "agents" / "guides"
    guides.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("[Guide](agents/guides/work.md)\n[Tags](agents/project-tags.json)\n")
    (tmp_path / "agents" / "project-tags.json").write_text("{}")
    (guides / "work.md").write_text("[Tags](../project-tags.json#projects)\n[Next](next.md)\n")
    (guides / "next.md").write_text("Done.")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "4 documents" in result.stdout


@pytest.mark.parametrize("source", ["AGENTS.md", "agents/global.md", "agents/guides/unlinked.md"])
def test_reports_dangling_link_in_root_or_any_guide(tmp_path: Path, source: str) -> None:
    (tmp_path / "AGENTS.md").write_text("Root.")
    document = tmp_path / source
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("Heading\n[Missing](missing.md)\n")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert f"{source}:2:" in result.stderr
    assert "missing.md" in result.stderr


def test_requires_root_document(tmp_path: Path) -> None:
    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "AGENTS.md" in result.stderr


def test_requires_global_rules(tmp_path: Path, global_rules: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Root.")
    global_rules.unlink()

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "agents/global.md: cannot read document" in result.stderr


def test_rejects_directory_as_guide_target(tmp_path: Path) -> None:
    (tmp_path / "agents" / "guides").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("[Guide](agents/guides)\n")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "agents/guides" in result.stderr


def test_ignores_external_urls_and_fragment_only_links(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "[Web](https://example.com/missing.md)\n[Mail](mailto:someone@example.com)\n"
        "[Host](//example.com/missing.md)\n[Here](#heading)\n"
    )

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr


def test_handles_angle_targets_url_encoding_and_link_titles(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text('[Space](<a file.md>)\n[Encoded](a%20file.md "Title")\n')
    (tmp_path / "a file.md").write_text("Target.")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr


def test_ignores_code_examples_and_historical_work_guides(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("`[Example](missing.md)`\n```markdown\n[Example](missing.md)\n```\n")
    historical = tmp_path / "agents" / "work" / "local.md"
    historical.parent.mkdir(parents=True)
    historical.write_text("[Old](missing.md)")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr


def test_default_root_uses_script_location_from_unrelated_cwd(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    copied = scripts / SCRIPT.name
    shutil.copyfile(SCRIPT, copied)
    (root / "AGENTS.md").write_text("[Target](target.md)\n")
    (root / "target.md").write_text("Target.")
    (root / "agents").mkdir()
    (root / "agents" / "global.md").write_text("Global.")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "AGENTS.md").write_text("[Wrong root](missing.md)")

    result = subprocess.run([sys.executable, str(copied)], cwd=elsewhere, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr


RAW = "https://raw.githubusercontent.com/sucramual/mp/main"
BLOB = "https://github.com/sucramual/mp/blob/main"


def write_skill_file(root: Path, path: str, text: str) -> Path:
    """Write one file under skills/ in a checked root that also has its required root document."""
    (root / "AGENTS.md").write_text("Root.")
    document = root / "skills" / path
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(text)
    return document


def test_reports_skill_link_that_leaves_its_own_folder(tmp_path: Path) -> None:
    write_skill_file(tmp_path, "other/SKILL.md", "Other.")
    write_skill_file(tmp_path, "one/SKILL.md", "Heading\n[Other](../other/SKILL.md)\n")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "skills/one/SKILL.md:2:" in result.stderr
    assert "outside skills/one/" in result.stderr


def test_accepts_skill_links_inside_its_own_folder(tmp_path: Path) -> None:
    write_skill_file(tmp_path, "one/SKILL.md", "[Ref](references/a.md)\n")
    write_skill_file(tmp_path, "one/references/a.md", "[Back](../SKILL.md)\n[Next](b.md#part)\n")
    write_skill_file(tmp_path, "one/references/b.md", "B.")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "3 skill documents" in result.stdout


def test_reports_repository_url_to_missing_file_in_links_and_code(tmp_path: Path) -> None:
    write_skill_file(
        tmp_path,
        "one/SKILL.md",
        f"Heading\n[Rule]({RAW}/agents/missing.md)\nRun `curl -fsSL {BLOB}/agents/gone.md`.\n",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "skills/one/SKILL.md:2:" in result.stderr
    assert "agents/missing.md" in result.stderr
    assert "skills/one/SKILL.md:3:" in result.stderr
    assert "agents/gone.md" in result.stderr


def test_accepts_repository_url_to_existing_file_after_stripping_fragment(tmp_path: Path) -> None:
    guide = tmp_path / "agents" / "guides" / "pr-review.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("Guide.")
    write_skill_file(
        tmp_path,
        "one/SKILL.md",
        f"[Rule]({RAW}/agents/guides/pr-review.md#merge-rule-files)\n"
        f"```bash\ncurl -fsSL {RAW}/agents/guides/pr-review.md\n```\n"
        f"See <{BLOB}/agents/guides/pr-review.md>.\n",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", ["~/dotfiles/agents/global.md", "~/.agent-guidance/guides/design.md"])
def test_reports_dotfiles_checkout_path_that_a_skill_reads(tmp_path: Path, path: str) -> None:
    write_skill_file(tmp_path, "one/SKILL.md", f"Heading\nRead `{path}` first.\n")

    result = run_checker(tmp_path)

    assert result.returncode == 1
    assert "skills/one/SKILL.md:2:" in result.stderr
    assert path in result.stderr


def test_ignores_skill_dependencies_in_node_modules(tmp_path: Path) -> None:
    write_skill_file(tmp_path, "one/SKILL.md", "One.")
    write_skill_file(tmp_path, "one/node_modules/pkg/README.md", "[Up](../../../other.md)\n~/dotfiles/x\n")

    result = run_checker(tmp_path)

    assert result.returncode == 0, result.stderr
