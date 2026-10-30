"""Shared fixtures for black-box tests that run repository tools as subprocesses."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# A fake executable is a bash script: this header plus the body the test supplies.
FAKE_HEADER = "#!/usr/bin/env bash\n"

# The default fake launchctl logs each call to $HOME/launchctl.log. It keeps one "loaded" flag:
# bootstrap sets it, bootout clears it, and print fails while it is clear.
FAKE_LAUNCHCTL = """printf '%s\\n' "$*" >>"$HOME/launchctl.log"
case "$1" in
  bootstrap) touch "$HOME/.launchctl-loaded" ;;
  bootout) rm -f "$HOME/.launchctl-loaded" ;;
  print) [ -e "$HOME/.launchctl-loaded" ] || exit 113 ;;
esac
exit 0
"""

# The default fake uv logs each call to $HOME/uv.log and exits with $UV_EXIT (default 0).
FAKE_UV = """printf '%s\\n' "$*" >>"$HOME/uv.log"
exit "${UV_EXIT:-0}"
"""

# The default fake ro logs each call to $HOME/ro.log. Nothing in dotfiles calls ro any more, so a test can
# check that the log stays absent.
FAKE_RO = """printf '%s\\n' "$*" >>"$HOME/ro.log"
exit 0
"""


@dataclass
class IsolatedEnv:
    """A minimal environment that keeps the user's HOME, Git config, and hooks out of tests.

    ``env`` holds only HOME, PATH, GIT_CONFIG_GLOBAL, and GIT_CONFIG_NOSYSTEM, like ``env -i``.
    So agent variables such as CLAUDECODE or CODEX_* do not leak in. PATH is ``bin`` followed
    by the caller's PATH, so fakes written to ``bin`` win over real commands.
    """

    root: Path
    home: Path
    bin: Path
    gitconfig: Path
    env: dict[str, str]

    def git(self, cwd: Path, *args: str) -> str:
        """Run git in cwd with this environment. Fails the test on a non-zero exit; returns stripped stdout."""
        result = subprocess.run(["git", *args], cwd=cwd, env=self.env, text=True, capture_output=True)
        if result.returncode != 0:
            pytest.fail(f"git {' '.join(args)} failed in {cwd} (exit {result.returncode}):\n{result.stderr}")
        return result.stdout.strip()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path of this repository's root."""
    return REPO_ROOT


@pytest.fixture
def isolated_env(tmp_path: Path) -> IsolatedEnv:
    """Temp HOME and global Git config (test identity, defaultBranch=main, no user hooks), plus a fakes dir on PATH.

    The fakes dir starts with a fake ``launchctl`` (see ``FAKE_LAUNCHCTL``), a fake ``uv`` (see ``FAKE_UV``), and a
    fake ``ro`` (see ``FAKE_RO``).

    ``root`` is tmp_path with symlinks resolved (macOS /var -> /private/var), so it matches paths that
    tools and ``pwd -P`` report.
    """
    root = tmp_path.resolve()
    home = root / "home"
    bin_dir = root / "bin"
    home.mkdir()
    bin_dir.mkdir()
    # Every test gets a fake launchctl, so a test that runs install.sh with a faked Darwin
    # never loads a launchd job into the real user session.
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(FAKE_HEADER + FAKE_LAUNCHCTL)
    launchctl.chmod(0o755)
    # A fake uv, so no test installs a uv tool from the network.
    uv = bin_dir / "uv"
    uv.write_text(FAKE_HEADER + FAKE_UV)
    uv.chmod(0o755)
    # A fake ro, so no test runs a real ro from PATH.
    ro = bin_dir / "ro"
    ro.write_text(FAKE_HEADER + FAKE_RO)
    ro.chmod(0o755)
    gitconfig = root / "gitconfig"
    gitconfig.write_text("[user]\n  email = test@example.com\n  name = Test\n[init]\n  defaultBranch = main\n")
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return IsolatedEnv(root=root, home=home, bin=bin_dir, gitconfig=gitconfig, env=env)


@pytest.fixture
def fake_exe(isolated_env: IsolatedEnv) -> Callable[..., Path]:
    """Return ``make(name, body, directory=None) -> Path``, which writes an executable bash script.

    The script is ``#!/usr/bin/env bash`` plus ``body``. It goes in ``isolated_env.bin`` (on PATH)
    unless ``directory`` is given; that directory is created if needed.
    """

    def make(name: str, body: str, directory: Path | None = None) -> Path:
        target_dir = directory or isolated_env.bin
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / name
        path.write_text(FAKE_HEADER + body)
        path.chmod(0o755)
        return path

    return make


@pytest.fixture
def run_tool(isolated_env: IsolatedEnv) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return ``run(args, *, cwd, env=None, input=None, **extra_env) -> CompletedProcess[str]``.

    Runs a command as a subprocess and captures stdout and stderr as text. It never raises on a
    non-zero exit; assert on ``returncode``. ``env`` replaces ``isolated_env.env`` as the base, and
    ``extra_env`` entries are added on top (they may override PATH or HOME).
    """

    def run(
        args: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        input: str | None = None,
        **extra_env: str,
    ) -> subprocess.CompletedProcess[str]:
        merged = {**(isolated_env.env if env is None else env), **extra_env}
        return subprocess.run(
            [os.fspath(arg) for arg in args],
            cwd=cwd,
            env=merged,
            input=input,
            text=True,
            capture_output=True,
            timeout=120,
        )

    return run


def copy_working_tree(source: Path, target: Path) -> None:
    """Copy the files that git tracks or would track (not ignored) from source, as they are on disk now."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=source,
        capture_output=True,
        check=True,
    )
    for relative in sorted({path for path in os.fsdecode(listing.stdout).split("\0") if path}):
        origin = source / relative
        if not os.path.lexists(origin):  # Deleted in the working tree but not yet staged.
            continue
        copy = target / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_symlink():
            os.symlink(os.readlink(origin), copy)
        else:
            shutil.copy2(origin, copy)


@pytest.fixture
def main_checkout(isolated_env: IsolatedEnv) -> Path:
    """A main checkout (a git repository, not a linked worktree) that holds a copy of this working tree.

    Run install.sh from it, not from REPO_ROOT, when a test checks the tool links in ~/bin.
    scripts/link_tools.py links only from a main checkout, and `dotfiles-pr ship` runs the tests in a linked worktree.
    """
    checkout = isolated_env.root / "main-checkout"
    checkout.mkdir()
    isolated_env.git(checkout, "init", "-q")
    copy_working_tree(REPO_ROOT, checkout)
    return checkout
