"""Black-box tests for the tool links in ~/bin, which `dotfiles-pr sync` and install.sh both make.

Each test builds a bare origin, a seed clone that plays GitHub merging PRs, and a clone that stands
in for ~/dotfiles. It runs the real dotfiles-pr (and, in the parity test, the checkout's install.sh)
with HOME set to a temp dir, so the real ~/bin and ~/dotfiles stay untouched.
Set DOTFILES_PR_PYTHON (e.g. /opt/homebrew/bin/python3.13) to pick the interpreter for dotfiles-pr.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv, copy_working_tree

TOOL = REPO_ROOT / "tools" / "dotfiles-pr" / "bin" / "dotfiles-pr"
RunTool = Callable[..., subprocess.CompletedProcess[str]]


def tool_cmd() -> list[str]:
    python = os.environ.get("DOTFILES_PR_PYTHON")
    return [python, str(TOOL)] if python else [str(TOOL)]


def entry_point_body(name: str) -> str:
    return f"#!/bin/sh\necho 'ran {name}'\n"


def bin_state(directory: Path, *, identity: bool = False) -> dict[str, tuple[object, ...]]:
    """Describe each entry of directory: a link by its written target, a file by its bytes and mode.

    With identity, a link also carries its inode and times, so a link that was removed and made again differs.
    """
    state: dict[str, tuple[object, ...]] = {}
    for entry in sorted(directory.iterdir()) if directory.is_dir() else []:
        info = entry.lstat()
        if entry.is_symlink():
            extra = (info.st_ino, info.st_mtime_ns, info.st_ctime_ns) if identity else ()
            state[entry.name] = ("link", os.readlink(entry), *extra)
        elif entry.is_file():
            state[entry.name] = ("file", entry.read_bytes(), stat.S_IMODE(info.st_mode))
        else:
            state[entry.name] = ("other",)
    return state


def warnings_about(stderr: str, entry: Path) -> list[str]:
    return [line for line in stderr.splitlines() if "warning" in line and str(entry) in line]


class Dotfiles:
    """A bare origin, a seed clone that plays GitHub merging PRs, and a clone that stands in for ~/dotfiles.

    By default the seed holds this repository's scripts/ and one entry point for each name in ``tools``.
    With ``full_copy``, it holds the whole working tree of this repository instead.
    """

    def __init__(
        self, iso: IsolatedEnv, run_tool: RunTool, tools: Iterable[str] = (), *, full_copy: bool = False
    ) -> None:
        self.iso, self._run_tool = iso, run_tool
        root = iso.root
        self.origin, self.seed, self.checkout = root / "origin.git", root / "seed", root / "dotfiles"
        self.bin = iso.home / "bin"
        iso.git(root, "init", "-q", "--bare", str(self.origin))
        iso.git(root, "clone", "-q", str(self.origin), str(self.seed))
        if full_copy:
            copy_working_tree(REPO_ROOT, self.seed)
        else:
            shutil.copytree(REPO_ROOT / "scripts", self.seed / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            for name in tools:
                self._write(f"tools/{name}/bin/{name}")
        iso.git(self.seed, "add", "-A")
        iso.git(self.seed, "commit", "-qm", "chore: initial")
        iso.git(self.seed, "push", "-q", "origin", "main")
        iso.git(root, "clone", "-q", str(self.origin), str(self.checkout))

    def _write(self, relative: str) -> None:
        path = self.seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry_point_body(path.name))
        path.chmod(0o755)

    def merge(self, message: str, *, add: Iterable[str] = (), remove: Iterable[str] = ()) -> None:
        """Commit on origin/main, as a merged PR would. Paths are relative to the repository root."""
        for relative in remove:
            self.iso.git(self.seed, "rm", "-q", relative)
        for relative in add:
            self._write(relative)
        self.iso.git(self.seed, "add", "-A")
        self.iso.git(self.seed, "commit", "-qm", message)
        self.iso.git(self.seed, "push", "-q", "origin", "main")

    def path(self, relative: str) -> Path:
        """An absolute path in the checkout, as the ~/bin links name it."""
        return self.checkout / relative

    def sync(self, home: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run `dotfiles-pr sync --no-prune` on the checkout, as the launchd job does."""
        extra = {"DOTFILES_DIR": str(self.checkout)}
        if home is not None:
            extra["HOME"] = str(home)
        return self._run_tool([*tool_cmd(), "sync", "--no-prune"], cwd=self.iso.root, **extra)

    def link(self, name: str, target: Path | str) -> Path:
        """Make ~/bin/<name> a link to target, as an earlier install.sh or a person would have."""
        self.bin.mkdir(exist_ok=True)
        (self.bin / name).symlink_to(target)
        return self.bin / name


def assert_synced(result: subprocess.CompletedProcess[str], what: str) -> None:
    assert result.returncode == 0, f"{what}: sync should succeed\n{result.stderr}"
    assert "main is at" in result.stdout, f"{what}: sync should print its summary\n{result.stdout}"


@pytest.fixture
def make_dotfiles(isolated_env: IsolatedEnv, run_tool: RunTool) -> Callable[..., Dotfiles]:
    def make(*tools: str, full_copy: bool = False) -> Dotfiles:
        return Dotfiles(isolated_env, run_tool, tools, full_copy=full_copy)

    return make


# --- sync links a new tool ------------------------------------------------------------


def test_sync_puts_a_tool_from_a_merged_pr_on_path(make_dotfiles: Callable[..., Dotfiles], run_tool: RunTool) -> None:
    dotfiles = make_dotfiles("sample-tool")
    assert not dotfiles.bin.exists()
    assert_synced(dotfiles.sync(), "first sync")
    assert bin_state(dotfiles.bin) == {
        "sample-tool": ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool")))
    }, "sync should create ~/bin and link the tool's entry point to the checkout"

    dotfiles.merge("feat(tools): add rogue-auth", add=["tools/rogue-auth/bin/rogue-auth"])
    assert_synced(dotfiles.sync(), "sync after the merge")
    assert bin_state(dotfiles.bin) == {
        "rogue-auth": ("link", str(dotfiles.path("tools/rogue-auth/bin/rogue-auth"))),
        "sample-tool": ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool"))),
    }, "sync should link the tool that the merged PR added"
    # Only the temp ~/bin is on PATH, so a real rogue-auth cannot answer.
    ran = run_tool(["rogue-auth"], cwd=dotfiles.iso.root, PATH=f"{dotfiles.bin}{os.pathsep}/usr/bin{os.pathsep}/bin")
    assert (ran.returncode, ran.stdout) == (0, "ran rogue-auth\n"), f"rogue-auth should run from PATH\n{ran.stderr}"


# --- sync leaves other ~/bin entries alone ----------------------------------------------


def test_sync_leaves_unrelated_bin_entries_untouched(make_dotfiles: Callable[..., Dotfiles]) -> None:
    dotfiles = make_dotfiles("sample-tool")
    elsewhere = dotfiles.iso.root / "Applications" / "obsidian-cli"
    elsewhere.parent.mkdir()
    elsewhere.write_text("#!/bin/sh\n")
    dotfiles.bin.mkdir()
    (dotfiles.bin / "my-script").write_text("#!/bin/sh\necho mine\n")
    (dotfiles.bin / "my-script").chmod(0o750)
    dotfiles.link("obsidian", elsewhere)  # A live link that points elsewhere.
    dotfiles.link("gone", dotfiles.iso.root / "nowhere" / "gone")  # A dangling link that points elsewhere.
    dotfiles.link("relative", "../nowhere/relative")  # A dangling relative link.
    # A dangling link into the checkout, outside tools/, such as a link to a file that an old layout kept in bin/.
    dotfiles.link("sample-tool.md", dotfiles.path("bin/sample-tool.md"))
    # A live link into tools/ under another name: a person's alias, not a link that sync made.
    dotfiles.link("wt", dotfiles.path("tools/sample-tool/bin/sample-tool"))
    before = bin_state(dotfiles.bin, identity=True)

    assert_synced(dotfiles.sync(), "sync")
    after = bin_state(dotfiles.bin, identity=True)
    assert after.pop("sample-tool", ())[:2] == ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool"))), (
        "sync should link the tool"
    )
    assert after == before, "sync should not change, move, or remove any entry that is not a tool link it owns"


def test_sync_keeps_and_reports_a_foreign_entry_at_a_tool_name(make_dotfiles: Callable[..., Dotfiles]) -> None:
    dotfiles = make_dotfiles("sample-tool", "git-unlock", "mmd-ascii")
    other = dotfiles.iso.root / "other" / "mmd-ascii"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\n")
    dotfiles.bin.mkdir()
    own_script = dotfiles.bin / "git-unlock"
    own_script.write_text("#!/bin/sh\necho my own git-unlock\n")
    own_script.chmod(0o755)
    foreign_link = dotfiles.link("mmd-ascii", other)
    before = bin_state(dotfiles.bin, identity=True)

    result = dotfiles.sync()
    assert_synced(result, "sync with foreign entries at tool names")
    after = bin_state(dotfiles.bin, identity=True)
    assert {name: after[name] for name in before} == before, (
        "sync should not replace a real file or a link that points outside the checkout"
    )
    assert after.get("sample-tool", ())[:2] == ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool"))), (
        "sync should still link the tools whose names are free"
    )
    for entry in (own_script, foreign_link):
        assert warnings_about(result.stderr, entry), f"sync should warn that {entry} blocks a link\n{result.stderr}"


# --- sync is idempotent ------------------------------------------------------------------


def test_a_second_sync_changes_nothing(make_dotfiles: Callable[..., Dotfiles]) -> None:
    dotfiles = make_dotfiles("sample-tool", "git-unlock")
    # A link that an earlier install.sh made is already correct.
    dotfiles.link("git-unlock", dotfiles.path("tools/git-unlock/bin/git-unlock"))
    first = dotfiles.sync()
    assert_synced(first, "first sync")
    linked = bin_state(dotfiles.bin, identity=True)
    assert {name: value[:2] for name, value in linked.items()} == {
        "git-unlock": ("link", str(dotfiles.path("tools/git-unlock/bin/git-unlock"))),
        "sample-tool": ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool"))),
    }, "the first sync should link every tool"

    second = dotfiles.sync()
    assert_synced(second, "second sync")
    assert bin_state(dotfiles.bin, identity=True) == linked, "a second sync should leave every correct link as it is"
    for result in (first, second):
        problems = [line for line in result.stderr.splitlines() if line.startswith("dotfiles-pr: warning")]
        assert problems == [], f"sync should not warn about current links\n{result.stderr}"


# --- sync removes stale dotfiles links -------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "remove", "add", "expected"),
    [
        ("retire", ["tools/old-tool/bin/old-tool"], [], {}),
        (
            "rename",
            ["tools/old-tool/bin/old-tool"],
            ["tools/old-tool/bin/new-tool"],
            {"new-tool": "tools/old-tool/bin/new-tool"},
        ),
        (
            "move",
            ["tools/old-tool/bin/old-tool"],
            ["tools/new-home/bin/old-tool"],
            {"old-tool": "tools/new-home/bin/old-tool"},
        ),
    ],
)
def test_sync_drops_or_repoints_a_link_whose_tool_target_is_gone(
    make_dotfiles: Callable[..., Dotfiles], change: str, remove: list[str], add: list[str], expected: dict[str, str]
) -> None:
    dotfiles = make_dotfiles("sample-tool", "old-tool")
    # The links an earlier install.sh made.
    dotfiles.link("sample-tool", dotfiles.path("tools/sample-tool/bin/sample-tool"))
    dotfiles.link("old-tool", dotfiles.path("tools/old-tool/bin/old-tool"))
    # Dangling links that are not tool links: they stay.
    dotfiles.link("sample-tool.md", dotfiles.path("bin/sample-tool.md"))
    dotfiles.link("gone", dotfiles.iso.root / "nowhere" / "gone")
    kept = {name: bin_state(dotfiles.bin, identity=True)[name] for name in ("sample-tool", "sample-tool.md", "gone")}

    dotfiles.merge(f"refactor(tools): {change} old-tool", remove=remove, add=add)
    assert_synced(dotfiles.sync(), f"sync after the {change}")
    after = bin_state(dotfiles.bin, identity=True)
    assert {name: after.get(name) for name in kept} == kept, (
        "sync should keep the current tool link and every dangling link outside the checkout's tools/"
    )
    tool_links = {name: value[1] for name, value in after.items() if name not in kept}
    assert tool_links == {name: str(dotfiles.path(target)) for name, target in expected.items()}, (
        f"after the {change}, ~/bin should drop the stale old-tool link and link the new entry point"
    )


# --- only the main checkout links ------------------------------------------------------------


def test_bin_dir_option_links_into_that_directory_and_leaves_home_bin_alone(
    make_dotfiles: Callable[..., Dotfiles], run_tool: RunTool
) -> None:
    dotfiles = make_dotfiles("sample-tool")
    target_dir = dotfiles.iso.home / ".local" / "bin"
    # A stale link in the chosen directory is pruned like one in ~/bin.
    target_dir.mkdir(parents=True)
    (target_dir / "gone").symlink_to(dotfiles.path("tools/gone/bin/gone"))
    dotfiles.bin.mkdir()
    (dotfiles.bin / "mine").write_text("keep\n")
    before = bin_state(dotfiles.bin, identity=True)

    result = run_tool(
        ["python3", str(dotfiles.path("scripts/link_tools.py")), "--bin-dir", str(target_dir)], cwd=dotfiles.iso.root
    )

    assert result.returncode == 0, result.stderr
    assert bin_state(target_dir) == {"sample-tool": ("link", str(dotfiles.path("tools/sample-tool/bin/sample-tool")))}
    assert bin_state(dotfiles.bin, identity=True) == before, "the option must leave ~/bin alone"


def test_link_tools_refuses_in_a_linked_worktree(make_dotfiles: Callable[..., Dotfiles], run_tool: RunTool) -> None:
    dotfiles = make_dotfiles("sample-tool", "git-unlock")
    root = dotfiles.iso.root
    worktree = root / "scratch"
    dotfiles.iso.git(dotfiles.checkout, "worktree", "add", "-q", "-b", "scratch", str(worktree))
    # Entries that a run in the worktree would change if it did not refuse. git-unlock is free, so it would be linked.
    dotfiles.link("sample-tool", worktree / "bin" / "sample-tool")  # Old layout in the worktree: relinked.
    dotfiles.link("retired-tool", worktree / "tools" / "retired-tool" / "bin" / "retired-tool")  # Stale: removed.
    before = bin_state(dotfiles.bin, identity=True)
    fresh_home = root / "fresh-home"
    fresh_home.mkdir()

    main_copy = str(dotfiles.path("scripts/link_tools.py"))
    for home in (dotfiles.iso.home, fresh_home):
        result = run_tool(["python3", worktree / "scripts" / "link_tools.py"], cwd=root, HOME=str(home))
        assert result.returncode == 2, (
            f"link_tools.py should refuse in a linked worktree with exit 2\n{result.stdout}\n{result.stderr}"
        )
        refusal = result.stderr.splitlines()
        assert len(refusal) == 1, f"the refusal should be one line\n{result.stderr}"
        assert "linked worktree" in refusal[0] and str(worktree) in refusal[0], (
            f"the refusal should say that this checkout is a linked worktree\n{result.stderr}"
        )
        assert main_copy in refusal[0], f"the refusal should name the main checkout's script\n{result.stderr}"
        assert result.stdout == "", f"a refused run should report no change\n{result.stdout}"
    assert bin_state(dotfiles.bin, identity=True) == before, "a refused run should not create, change, or remove links"
    assert not (fresh_home / "bin").exists(), "a refused run should not create ~/bin"


# --- install.sh and sync agree ---------------------------------------------------------------


def seed_bin(home: Path, root: Path, checkout: Path) -> None:
    """Fill home/bin with the entries the parity test expects both installers to treat the same way."""
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "my-script").write_text("#!/bin/sh\necho mine\n")
    (bin_dir / "git-unlock").write_text("#!/bin/sh\necho my own git-unlock\n")  # A real file at a tool name.
    (bin_dir / "obsidian").symlink_to(root / "Applications" / "obsidian-cli")
    (bin_dir / "sample-tool.md").symlink_to(checkout / "bin" / "sample-tool.md")
    (bin_dir / "retired-tool").symlink_to(checkout / "tools" / "retired-tool" / "bin" / "retired-tool")
    (bin_dir / "dotfiles-pr").symlink_to(
        checkout / "tools" / "dotfiles-pr" / "bin" / "dotfiles-pr"
    )  # A current tool link.
    (bin_dir / "mmd-ascii").symlink_to(checkout / "bin" / "mmd-ascii")  # An old repository layout: repointed.


def test_install_sh_and_sync_make_the_same_bin(
    make_dotfiles: Callable[..., Dotfiles], fake_exe: Callable[..., Path], run_tool: RunTool
) -> None:
    dotfiles = make_dotfiles(full_copy=True)
    root, checkout = dotfiles.iso.root, dotfiles.checkout
    # Fakes keep install.sh away from real Homebrew, package installs, and third-party skill installs.
    fake_exe("brew", "exit 0\n")
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    install_home, sync_home = root / "install-home", root / "sync-home"
    for home in (install_home, sync_home):
        seed_bin(home, root, checkout)

    # Without GIT_CONFIG_GLOBAL, `git config --global` writes the temp HOME's ~/.gitconfig, as install.sh expects.
    env = {key: value for key, value in dotfiles.iso.env.items() if key != "GIT_CONFIG_GLOBAL"}
    installed = run_tool([checkout / "install.sh"], cwd=root, env=env, HOME=str(install_home))
    assert installed.returncode == 0, f"install.sh should succeed\n{installed.stdout}\n{installed.stderr}"
    assert_synced(dotfiles.sync(home=sync_home), "sync")

    from_install, from_sync = bin_state(install_home / "bin"), bin_state(sync_home / "bin")
    assert from_install == from_sync, "install.sh and sync should leave ~/bin in the same state"
    entry_points = sorted(checkout.glob("tools/*/bin/*"))
    assert entry_points, "the copied checkout should have tool entry points"
    expected = {path.name: ("link", str(path)) for path in entry_points if path.name != "git-unlock"}
    assert {name: value for name, value in from_sync.items() if name in expected} == expected, (
        "every tool entry point should be linked"
    )
    assert "retired-tool" not in from_sync and "my-script" in from_sync, (
        "the stale tool link should go, and the unrelated file should stay"
    )
    assert from_sync["git-unlock"][0] == "file", "a real file at a tool name should stay"
