"""Black-box tests for scripts/link_skills.py.

Each test copies the script into a temp git repo and runs it there with the isolated HOME,
so the real ~/.agents, ~/.claude, and state folders stay untouched.
Set DOTFILES_PR_PYTHON (e.g. /opt/homebrew/bin/python3.13) to pick the interpreter.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

RunTool = Callable[..., subprocess.CompletedProcess[str]]
OLD_BACKUP = "20200101T000000Z"


class Setup:
    def __init__(self, iso: IsolatedEnv, run_tool: RunTool) -> None:
        self.iso, self.run_tool = iso, run_tool
        self.repo = iso.root / "repo"
        self.agents = iso.home / ".agents" / "skills"
        self.claude = iso.home / ".claude" / "skills"
        self.backups = iso.home / ".local" / "state" / "dotfiles" / "skill-backups"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "scripts" / "link_skills.py", self.repo / "scripts")
        iso.git(self.repo, "init", "-q")

    def skill(self, name: str, body: str = "v1\n") -> None:
        (self.repo / "skills" / name).mkdir(parents=True, exist_ok=True)
        (self.repo / "skills" / name / "SKILL.md").write_text(body)

    def delete(self, name: str) -> None:
        shutil.rmtree(self.repo / "skills" / name)

    def real(self, root: Path, name: str, body: str = "v1\n") -> Path:
        """Create a real directory <root>/<name> that stands for a snapshot copy."""
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text(body)
        return root / name

    def run(self, *extra: str, repo: Path | None = None, python: str | None = None, **env: str):
        interpreter = python or os.environ.get("DOTFILES_PR_PYTHON") or sys.executable
        script = (repo or self.repo) / "scripts" / "link_skills.py"
        return self.run_tool([interpreter, script, *extra], cwd=self.iso.root, **env)


@pytest.fixture
def setup(isolated_env: IsolatedEnv, run_tool: RunTool) -> Setup:
    return Setup(isolated_env, run_tool)


def test_first_run_links_with_an_absolute_claude_link_and_a_second_run_is_silent(setup: Setup) -> None:
    setup.skill("zoom-out")
    first = setup.run()
    assert (first.returncode, first.stdout.splitlines()) == (0, ["linked zoom-out", "linked zoom-out (claude)"])
    assert os.readlink(setup.agents / "zoom-out") == str(setup.repo / "skills" / "zoom-out")
    assert os.readlink(setup.claude / "zoom-out") == str(setup.agents / "zoom-out")
    assert (setup.claude / "zoom-out" / "SKILL.md").read_text() == "v1\n"
    again = setup.run()
    assert (again.returncode, again.stdout, again.stderr) == (0, "", "")


# (where the foreign entry sits, how to make it)
FOREIGN = {
    "live link elsewhere": ("agents", lambda s: s.iso.root),
    "dangling link outside the repo": ("agents", lambda s: s.iso.root / "missing"),
    "link to another skill": ("agents", lambda s: s.repo / "skills" / "other"),
    "claude dangling link elsewhere": ("claude", lambda s: s.iso.root / "missing"),
    "claude link to another skill": ("claude", lambda s: s.repo / "skills" / "other"),
}


@pytest.mark.parametrize("case", FOREIGN)
def test_a_foreign_link_at_a_managed_name_stays_warns_and_exits_1(setup: Setup, case: str) -> None:
    side, target = FOREIGN[case]
    setup.skill("zoom-out")
    setup.skill("other")
    folder = setup.agents if side == "agents" else setup.claude
    folder.mkdir(parents=True)
    (folder / "zoom-out").symlink_to(target(setup))
    result = setup.run()
    assert result.returncode == 1
    assert "remove it to link" in result.stderr
    assert os.readlink(folder / "zoom-out") == str(target(setup))
    if side == "agents":
        assert not os.path.lexists(setup.claude / "zoom-out")


@pytest.mark.parametrize("where", ["agents-identical", "agents-edited", "agents-file", "claude-real"])
def test_a_real_entry_at_a_managed_name_is_moved_aside_with_its_bytes_then_linked(setup: Setup, where: str) -> None:
    setup.skill("zoom-out")
    kind = where.split("-")[0]
    folder = setup.agents if kind == "agents" else setup.claude
    if where == "agents-file":
        folder.mkdir(parents=True)
        (folder / "zoom-out").write_text("file\n")
    else:
        setup.real(folder, "zoom-out", "my edit\n" if where != "agents-identical" else "v1\n")
    result = setup.run()
    assert result.returncode == 0, result.stderr
    (backup,) = (setup.backups / kind).iterdir()
    assert backup.name.startswith("zoom-out.") and f"moved {folder / 'zoom-out'} to {backup}" in result.stdout
    original = {"agents-identical": "v1\n", "agents-edited": "my edit\n", "agents-file": "file\n"}.get(
        where, "my edit\n"
    )
    assert (backup if backup.is_file() else backup / "SKILL.md").read_text() == original
    assert (setup.claude / "zoom-out" / "SKILL.md").read_text() == "v1\n"
    assert setup.run().stdout == ""  # The second run moves nothing more.


def test_the_sweep_removes_old_backups_and_keeps_new_and_unmatched_entries(setup: Setup) -> None:
    setup.skill("zoom-out")
    new = f"new.{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    for path in (
        setup.backups / "agents" / f"old.{OLD_BACKUP}",
        setup.backups / "agents" / f"old.{OLD_BACKUP}.1",
        setup.backups / "claude" / f"old.{OLD_BACKUP}",
        setup.backups / "agents" / new,
        setup.backups / "agents" / "notes",
        setup.backups / "agents" / "x.20200101",
    ):
        path.mkdir(parents=True)
    result = setup.run()
    assert result.stdout.count("removed backup") == 3
    left = sorted(p.name for p in (setup.backups / "agents").iterdir()) + [
        p.name for p in (setup.backups / "claude").iterdir()
    ]
    assert left == sorted([new, "notes", "x.20200101"])


def test_a_dry_run_changes_nothing(setup: Setup) -> None:
    setup.skill("zoom-out")
    setup.skill("handoff")
    copy = setup.real(setup.agents, "zoom-out")
    (setup.backups / "agents" / f"old.{OLD_BACKUP}").mkdir(parents=True)
    result = setup.run("--dry-run")
    lines = result.stdout.splitlines()
    assert result.returncode == 0 and lines and all(line.startswith("dry run: ") for line in lines)
    assert (
        sum(line.startswith("dry run: moved ") for line in lines) == 1
        and sum("removed backup" in line for line in lines) == 1
    )
    assert not copy.is_symlink() and not os.path.lexists(setup.agents / "handoff") and not setup.claude.exists()
    assert (setup.backups / "agents" / f"old.{OLD_BACKUP}").is_dir()


@pytest.mark.parametrize("xdg", [False, True])
def test_xdg_state_home_picks_the_backup_dir(setup: Setup, isolated_env: IsolatedEnv, xdg: bool) -> None:
    setup.skill("zoom-out")
    setup.real(setup.agents, "zoom-out")
    state = isolated_env.root / "state"
    result = setup.run(**({"XDG_STATE_HOME": str(state)} if xdg else {}))
    assert result.returncode == 0, result.stderr
    root = state / "dotfiles" / "skill-backups" if xdg else setup.backups
    assert len(list((root / "agents").iterdir())) == 1


# (setup of the entry, what the second line of output must or must not hold)
@pytest.mark.parametrize(
    "case",
    ["live alias", "dangling other skill", "dangling external alias", "retired real dir", "retired claude elsewhere"],
)
def test_prune_leaves_these_alone(setup: Setup, isolated_env: IsolatedEnv, case: str) -> None:
    setup.skill("zoom-out")
    setup.agents.mkdir(parents=True)
    external = isolated_env.root / "aliases"
    external.symlink_to(setup.repo / "skills")
    if case == "live alias":
        (setup.agents / "my-alias").symlink_to(setup.repo / "skills" / "zoom-out")
    elif case == "dangling other skill":
        (setup.agents / "my-alias").symlink_to(setup.repo / "skills" / "missing")
    elif case == "dangling external alias":
        (setup.agents / "my-alias").symlink_to(external / "my-alias")
    elif case == "retired real dir":
        setup.real(setup.agents, "my-alias")
    else:
        (setup.agents / "my-alias").symlink_to(setup.repo / "skills" / "my-alias")
        setup.claude.mkdir(parents=True)
        (setup.claude / "my-alias").symlink_to(isolated_env.root / "elsewhere")
    result = setup.run()
    assert (result.returncode, result.stderr) == (0, "")
    assert os.path.lexists(setup.agents / "my-alias") == (case != "retired claude elsewhere")
    assert ("my-alias" in result.stdout) == (case == "retired claude elsewhere")
    if case == "retired claude elsewhere":
        assert os.readlink(setup.claude / "my-alias") == str(isolated_env.root / "elsewhere")
        assert "(claude)" not in result.stdout.replace("zoom-out (claude)", "")


def test_a_retired_owned_dangling_link_is_removed_with_its_claude_link_and_a_rename_links_the_new_name(
    setup: Setup,
) -> None:
    setup.skill("drive-meeting-summaries")
    assert setup.run().returncode == 0
    setup.delete("drive-meeting-summaries")
    setup.skill("write-project-updates")
    result = setup.run()
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "linked write-project-updates",
        "linked write-project-updates (claude)",
        "removed link for drive-meeting-summaries",
        "removed link for drive-meeting-summaries (claude)",
    ]
    assert not os.path.lexists(setup.agents / "drive-meeting-summaries")
    assert not os.path.lexists(setup.claude / "drive-meeting-summaries")


def test_a_claude_dir_that_is_itself_a_symlink_gets_a_working_link(setup: Setup, isolated_env: IsolatedEnv) -> None:
    setup.skill("zoom-out")
    real = isolated_env.root / "real-claude-skills"
    real.mkdir()
    setup.claude.parent.mkdir(parents=True)
    setup.claude.symlink_to(real)
    assert setup.run().returncode == 0
    assert (real / "zoom-out" / "SKILL.md").read_text() == "v1\n"


def test_a_linked_worktree_exits_2(setup: Setup, isolated_env: IsolatedEnv) -> None:
    setup.skill("zoom-out")
    isolated_env.git(setup.repo, "add", "-A")
    isolated_env.git(setup.repo, "commit", "-qm", "init")
    worktree = isolated_env.root / "scratch"
    isolated_env.git(setup.repo, "worktree", "add", "-q", "--detach", str(worktree))
    result = setup.run(repo=worktree)
    assert result.returncode == 2 and "linked worktree" in result.stderr
    assert not setup.agents.exists()
