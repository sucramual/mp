"""Black-box tests for tools/git-unlock.

Each test leaves .git/index.lock in a temp repo and runs the real tool. It must remove the lock only
when lsof proves no process has it open. The tool merges its messages onto stdout and stderr, so the
tests search both, like the bash test's ``2>&1``.
"""

from __future__ import annotations

import fcntl
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

TOOL = REPO_ROOT / "tools" / "git-unlock" / "bin" / "git-unlock"
RunTool = Callable[..., subprocess.CompletedProcess[str]]

# One lock for every test run on this machine, so it lives in the shared temp dir, not tmp_path.
REAL_LSOF_LOCK = Path(tempfile.gettempdir()) / "dotfiles-tests-real-lsof.lock"


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    """stdout and stderr joined by a newline, so a line match in either counts, like grep over ``2>&1``."""
    return f"{result.stdout}\n{result.stderr}"


@pytest.fixture
def repo(isolated_env: IsolatedEnv) -> Path:
    """A repo with one commit and a leftover index.lock."""
    repo = isolated_env.root / "repo"
    repo.mkdir()
    isolated_env.git(repo, "init", "-q")
    (repo / "README.md").write_text("hello\n")
    isolated_env.git(repo, "add", "README.md")
    isolated_env.git(repo, "commit", "-qm", "initial")
    (repo / ".git" / "index.lock").touch()
    return repo


@pytest.fixture
def real_lsof_turn() -> Iterator[None]:
    """Hold a machine-wide lock, so only one test at a time runs git-unlock with the real lsof.

    lsof scans every process on the machine. When several suites run at once (agent sessions that
    each run scripts/check), all of them reach these tests together. A dozen overlapping scans on a
    busy machine run past lsof's own 15 s stat timeout ("status error on : ...") or past the
    120 s run_tool timeout. One scan at a time stays within a few seconds under the same load.
    """
    with REAL_LSOF_LOCK.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


@pytest.mark.usefixtures("real_lsof_turn")
def test_clears_an_unowned_lock(repo: Path, run_tool: RunTool):
    lock = repo / ".git" / "index.lock"

    result = run_tool([TOOL], cwd=repo)

    assert result.returncode == 0, f"git-unlock should clear an unowned lock\n{output_of(result)}"
    assert not lock.exists(), "git-unlock should remove an unowned lock"
    assert "git-unlock: cleared stale lock" in result.stdout, (
        f"git-unlock should report a cleared stale lock\n{result.stdout}"
    )


@pytest.mark.usefixtures("real_lsof_turn")
def test_refuses_an_active_lock(repo: Path, run_tool: RunTool):
    lock = repo / ".git" / "index.lock"

    # This test process holds the lock open, like the bash test's `exec 9>"$lock_path"`.
    with lock.open("w"):
        result = run_tool([TOOL], cwd=repo)

    output = output_of(result)
    assert result.returncode != 0, f"git-unlock should refuse an active lock\n{output}"
    assert lock.exists(), "git-unlock should preserve an active lock"
    assert "refusing to remove an active lock" in output, f"git-unlock should explain an active lock refusal\n{output}"


def test_refuses_when_lsof_is_unavailable(repo: Path, isolated_env: IsolatedEnv, run_tool: RunTool):
    lock = repo / ".git" / "index.lock"
    # PATH holds only bash and git, so lsof cannot be found.
    no_lsof_bin = isolated_env.root / "no-lsof-bin"
    no_lsof_bin.mkdir()
    for name in ("bash", "git"):
        found = shutil.which(name, path=isolated_env.env["PATH"])
        assert found, f"{name} must be on PATH to run this test"
        (no_lsof_bin / name).symlink_to(found)

    result = run_tool([TOOL], cwd=repo, PATH=str(no_lsof_bin))

    output = output_of(result)
    assert result.returncode != 0, f"git-unlock should refuse a lock when lsof is unavailable\n{output}"
    assert lock.exists(), "git-unlock should preserve a lock when lsof is unavailable"
    assert "cannot verify lock ownership because lsof is unavailable" in output, (
        f"git-unlock should explain an unavailable lsof command\n{output}"
    )


def test_refuses_when_lsof_fails(repo: Path, fake_exe: Callable[..., Path], run_tool: RunTool):
    lock = repo / ".git" / "index.lock"
    fake_exe("lsof", 'echo "lsof: test failure" >&2\nexit 2\n')

    result = run_tool([TOOL], cwd=repo)

    output = output_of(result)
    assert result.returncode != 0, f"git-unlock should refuse a lock when lsof fails\n{output}"
    assert lock.exists(), "git-unlock should preserve a lock when lsof fails"
    assert "cannot verify lock ownership; lsof failed" in output, (
        f"git-unlock should explain a failed lsof lookup\n{output}"
    )
