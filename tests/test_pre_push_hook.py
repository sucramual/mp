"""Black-box tests for config/git-hooks/pre-push and the installer step that turns it on.

Hook tests push from a scratch clone to a scratch bare remote. The clone holds copies of the hook and
scripts/check_leaks.py, and its core.hooksPath is the relative path that the installers set.
The terms here are made up. The real terms are private and never appear in this repository.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

RunTool = Callable[..., subprocess.CompletedProcess[str]]
TERM = "zorblaxcorp"
HOOKS_PATH = "config/git-hooks"
BLOCKED = "the leak check blocked the push"


class Clone:
    """A clone with the tracked hook turned on, and its bare remote."""

    def __init__(self, env: IsolatedEnv, run_tool: RunTool) -> None:
        self.env = env
        self.run_tool = run_tool
        self.remote = env.root / "remote.git"
        self.path = env.root / "clone"
        env.git(env.root, "init", "-q", "--bare", str(self.remote))
        env.git(env.root, "init", "-q", str(self.path))
        for relative in ("scripts/check_leaks.py", f"{HOOKS_PATH}/pre-push"):
            (self.path / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / relative, self.path / relative)
        env.git(self.path, "config", "core.hooksPath", HOOKS_PATH)
        env.git(self.path, "remote", "add", "origin", str(self.remote))
        self.commit("notes.md", "clean\n")

    def commit(self, name: str, text: str) -> str:
        (self.path / name).write_text(text)
        self.env.git(self.path, "add", "-A")
        self.env.git(self.path, "commit", "-q", "-m", f"change {name}")
        return self.env.git(self.path, "rev-parse", "HEAD")

    def push(self, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        return self.run_tool(["git", "push", "origin", *args], cwd=self.path, **extra_env)

    def remote_sha(self, branch: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(self.remote), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            env=self.env.env,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None


@pytest.fixture
def clone(isolated_env: IsolatedEnv, run_tool: RunTool) -> Clone:
    return Clone(isolated_env, run_tool)


def output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


# Bug caught: a hook that does not run the leak check, or does not block on a match, so a plain `git push`
# publishes a term at once.
def test_blocks_a_commit_with_a_term_and_never_prints_it(clone: Clone) -> None:
    clean = clone.env.git(clone.path, "rev-parse", "HEAD")
    allowed = clone.push("main", DOTFILES_LEAK_TERMS=TERM)
    assert allowed.returncode == 0, output(allowed)
    assert clone.remote_sha("main") == clean

    clone.commit("notes.md", f"We work at {TERM.upper()} today.\n")
    blocked = clone.push("main", DOTFILES_LEAK_TERMS=TERM)

    assert blocked.returncode != 0, output(blocked)
    assert clone.remote_sha("main") == clean, "the blocked push must not update the remote"
    lines = output(blocked).splitlines()
    leaked = clone.env.git(clone.path, "rev-parse", "HEAD")
    assert f"commit {leaked[:12]}: notes.md:1: matches leak term #1" in lines
    assert any(BLOCKED in line for line in lines), output(blocked)
    assert TERM not in output(blocked).casefold() and "today" not in output(blocked)


# Bug caught: a hook that checks only the tip of each pushed ref, so a term added in one commit and removed
# in a later one is published in the earlier commit.
def test_blocks_a_term_that_a_later_commit_removed(clone: Clone) -> None:
    clean = clone.env.git(clone.path, "rev-parse", "HEAD")
    assert clone.push("main", DOTFILES_LEAK_TERMS=TERM).returncode == 0
    leaky = clone.commit("notes.md", f"{TERM}\n")
    clone.commit("notes.md", "clean again\n")  # The tip is clean.

    result = clone.push("main", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode != 0, output(result)
    assert clone.remote_sha("main") == clean, "the blocked push must not update the remote"
    assert f"commit {leaky[:12]}: notes.md:1: matches leak term #1" in output(result).splitlines()
    assert BLOCKED in output(result)
    assert TERM not in output(result).casefold()


# Bug caught: the same hole on a new branch, whose ancestors are not on the remote and so must all be checked.
def test_blocks_a_removed_term_in_the_ancestors_of_a_new_branch(clone: Clone) -> None:
    clone.env.git(clone.path, "switch", "-q", "-c", "feature")
    leaky = clone.commit("notes.md", f"{TERM}\n")
    clone.commit("notes.md", "clean again\n")

    result = clone.push("feature", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode != 0, output(result)
    assert clone.remote_sha("feature") is None
    assert f"commit {leaky[:12]}: notes.md:1: matches leak term #1" in output(result).splitlines()
    assert TERM not in output(result).casefold()


# Bug caught: a hook that rechecks the whole history, so a term that is already on the remote in an old
# commit blocks every later clean push.
def test_checks_only_the_new_commits_of_an_existing_branch(clone: Clone) -> None:
    clone.commit("notes.md", f"{TERM}\n")
    clone.commit("notes.md", "clean again\n")
    no_terms = {"DOTFILES_WORK_DIR": str(clone.env.root / "no-overlay")}
    assert clone.push("main", **no_terms).returncode == 0  # No terms were set, so the old term got onto the remote.
    new = clone.commit("other.md", "still clean\n")

    result = clone.push("main", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, output(result)
    assert clone.remote_sha("main") == new


# Bug caught: a hook that checks the working tree, so a clean commit with a dirty file is blocked, and a
# committed term is published after a later edit cleans the file on disk.
def test_checks_the_pushed_commit_not_the_working_tree(clone: Clone) -> None:
    (clone.path / "draft.md").write_text(f"{TERM}\n")  # Untracked, never committed.
    (clone.path / "notes.md").write_text(f"{TERM}\n")  # Modified, not committed.
    dirty = clone.push("main", DOTFILES_LEAK_TERMS=TERM)
    assert dirty.returncode == 0, output(dirty)

    (clone.path / "draft.md").unlink()
    clone.commit("notes.md", f"{TERM}\n")
    pushed = clone.remote_sha("main")
    (clone.path / "notes.md").write_text("clean\n")  # The working tree is clean again; the commit is not.
    committed = clone.push("main", DOTFILES_LEAK_TERMS=TERM)

    assert committed.returncode != 0, output(committed)
    assert BLOCKED in output(committed)
    assert clone.remote_sha("main") == pushed


# Bug caught: a check that inherits the hook's stdin and reads the remaining ref lines, so a push of two
# refs checks only the first one and publishes a term on the second.
def test_checks_every_ref_of_a_multi_ref_push(clone: Clone) -> None:
    clone.env.git(clone.path, "branch", "first")
    clone.env.git(clone.path, "switch", "-q", "-c", "second")
    clone.commit("notes.md", f"{TERM}\n")

    result = clone.push("first", "second", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode != 0, output(result)
    assert any(BLOCKED in line and "refs/heads/second" in line for line in output(result).splitlines())
    assert clone.remote_sha("second") is None


# Bug caught: a hook that tries to check the all-zero ID of a deleted branch, or checks HEAD instead, and
# so blocks a branch deletion.
def test_allows_a_branch_deletion(clone: Clone) -> None:
    clone.env.git(clone.path, "branch", "old")
    assert clone.push("old", DOTFILES_LEAK_TERMS=TERM).returncode == 0
    clone.commit("notes.md", f"{TERM}\n")  # HEAD holds a term, but the deletion publishes nothing.

    result = clone.push("--delete", "old", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, output(result)
    assert clone.remote_sha("old") is None


# Bug caught: a hook that blocks every push in a cloud session or on a laptop without the private term list.
def test_allows_a_push_without_terms_and_warns(clone: Clone) -> None:
    sha = clone.commit("notes.md", f"{TERM}\n")

    result = clone.push("main", DOTFILES_WORK_DIR=str(clone.env.root / "no-overlay"))

    assert result.returncode == 0, output(result)
    assert clone.remote_sha("main") == sha
    assert "no leak terms found" in result.stderr


# Bug caught: a hook that blocks every push in a CI=true shell, such as a cloud session, without the term list.
def test_allows_a_push_without_terms_when_ci_is_set(clone: Clone) -> None:
    sha = clone.commit("notes.md", f"{TERM}\n")

    result = clone.push("main", CI="true", DOTFILES_WORK_DIR=str(clone.env.root / "no-overlay"))

    assert result.returncode == 0, output(result)
    assert clone.remote_sha("main") == sha
    assert "no leak terms found" in result.stderr


# Bug caught: a hook that treats a set but unreadable term source as "no terms" and lets the push through.
def test_blocks_a_push_when_the_terms_file_cannot_be_read(clone: Clone) -> None:
    pushed = clone.remote_sha("main")
    clone.commit("notes.md", "still clean\n")

    result = clone.push("main", CI="true", DOTFILES_LEAK_TERMS_FILE=str(clone.env.root / "missing.txt"))

    assert result.returncode != 0, output(result)
    assert "cannot read $DOTFILES_LEAK_TERMS_FILE" in result.stderr
    assert BLOCKED in result.stderr
    assert clone.remote_sha("main") == pushed


# install.sh needs a full laptop setup, and cloud-bootstrap needs only a fake npx.
INSTALLERS = ["install.sh", "scripts/cloud-bootstrap"]


def run_installer(
    script: str, checkout: Path, isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
) -> subprocess.CompletedProcess[str]:
    """Run one installer with the isolated HOME. Fakes keep it away from Homebrew and downloads."""
    fake_exe("brew", "exit 0\n")
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    # install.sh writes ~/.gitconfig, so it gets the temp HOME's global Git config, not the test one.
    env = {key: value for key, value in isolated_env.env.items() if key != "GIT_CONFIG_GLOBAL"}
    env["DOTFILES_WORK_DIR"] = str(isolated_env.root / "no-overlay")
    result = run_tool([checkout / script], cwd=isolated_env.root, env=env)
    assert result.returncode == 0, f"{script} should succeed\n{output(result)}"
    return result


def hooks_path(env: IsolatedEnv, checkout: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(checkout), "config", "--local", "--get", "core.hooksPath"],
        env=env.env,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


# Bug caught: an installer that never turns the hook on, or adds a second value on each run.
@pytest.mark.parametrize("script", INSTALLERS)
def test_installer_sets_the_hooks_path_once(
    script: str, main_checkout: Path, isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
) -> None:
    run_installer(script, main_checkout, isolated_env, fake_exe, run_tool)
    assert hooks_path(isolated_env, main_checkout) == HOOKS_PATH

    run_installer(script, main_checkout, isolated_env, fake_exe, run_tool)
    values = isolated_env.git(main_checkout, "config", "--local", "--get-all", "core.hooksPath")
    assert values.splitlines() == [HOOKS_PATH]


# Bug caught: an installer that silently replaces a hooks path that the machine set for another tool.
@pytest.mark.parametrize("script", INSTALLERS)
def test_installer_keeps_a_different_hooks_path_and_warns(
    script: str, main_checkout: Path, isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
) -> None:
    isolated_env.git(main_checkout, "config", "core.hooksPath", ".husky")

    result = run_installer(script, main_checkout, isolated_env, fake_exe, run_tool)

    assert hooks_path(isolated_env, main_checkout) == ".husky"
    warnings = [line for line in output(result).splitlines() if "WARNING" in line and "core.hooksPath" in line]
    assert warnings, output(result)


# Bug caught: an installer run from a linked worktree, such as a test run in a `dotfiles-pr` worktree,
# that writes the Git config that the main checkout and every other worktree share.
def test_install_from_a_linked_worktree_leaves_the_shared_config_alone(
    main_checkout: Path, isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
) -> None:
    isolated_env.git(main_checkout, "add", "-A")
    isolated_env.git(main_checkout, "commit", "-q", "-m", "copy")
    worktree = isolated_env.root / "linked"
    isolated_env.git(main_checkout, "worktree", "add", "-q", str(worktree))

    result = run_installer("install.sh", worktree, isolated_env, fake_exe, run_tool)

    assert hooks_path(isolated_env, main_checkout) is None
    assert any("core.hooksPath" in line and "linked worktree" in line for line in output(result).splitlines())
