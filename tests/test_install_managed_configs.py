"""Black-box tests for install.sh's Brewfile step and managed Git, bu, macOS window-manager, Ghostty, and shell configs.

The installer runs twice with HOME set to a temp dir that already holds machine-owned files.
DOTFILES_WORK_DIR points at a fake work overlay that holds only a bu bench template.
The real HOME, ~/bin, ~/dotfiles, and ~/dotfiles-work are never touched.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

INSTALLER = REPO_ROOT / "install.sh"
SOURCE_LAPTOP_HOME = "/Users/marcus"
RunTool = Callable[..., subprocess.CompletedProcess[str]]
BU_PRUNE_KEEP = [".cheese/**", ".tmp/answers/**", ".handoff/**"]

# The fake work overlay's bu bench template. The real one is in the private overlay, not in this repo.
WORK_BU_TEMPLATE = """[repository]
path = "__HOME__/Documents/work"
remote = "origin"
main_branch = "main"

[[benches]]
path = "__HOME__/Documents/work-01"
standin_branch = "main-01"

[prune]
keep = [".cheese/**", ".tmp/answers/**", ".handoff/**"]
"""


def fake_work_overlay(root: Path) -> Path:
    """A work overlay with only config/bu/config.toml.template. It has no install.sh."""
    overlay = root / "work-overlay"
    (overlay / "config" / "bu").mkdir(parents=True)
    (overlay / "config" / "bu" / "config.toml.template").write_text(WORK_BU_TEMPLATE)
    return overlay


# Installed link (under HOME) -> the repo path it must point to.
MANAGED_LINKS = {
    ".config/git/dotfiles.inc": "config/git/config",
    ".config/git/ignore": "config/git/ignore",
    ".config/yabai/yabairc": "config/macos/yabai/yabairc",
    ".config/skhd/skhdrc": "config/macos/skhd/skhdrc",
    ".config/borders/bordersrc": "config/macos/borders/bordersrc",
    ".config/ghostty/themes": "config/ghostty/themes",
    ".config/review-pr/reviewers.json": "config/review-pr/reviewers.json",
}

# Rendered bu config (under ~/.config/bu) -> the machine content its first backup must keep.
BU_MACHINE_CONTENT = {
    "config.toml": "machine bu config\n",
    "dotfiles.toml": "machine bu dotfiles config\n",
}

# (backup that must exist under HOME after install, failure message)
EXPECTED_BACKUPS = [
    (".config/git/ignore.bak", "install should back up an existing global ignore"),
    (".config/bu/config.toml.bak", "install should back up an existing bu config"),
    (".config/bu/dotfiles.toml.bak", "install should back up an existing bu dotfiles config"),
    (".config/yabai/yabairc.bak", "install should back up an existing yabai config"),
    (".config/skhd/skhdrc.bak", "install should back up an existing skhd config"),
    (".config/borders/bordersrc.bak", "install should back up an existing borders config"),
    (".config/ghostty/themes.bak/machine-local", "install should back up an existing ghostty themes directory"),
]


SYNC_LABEL = "com.sucramual.dotfiles-pr-sync"
SYNC_PLIST = f"Library/LaunchAgents/{SYNC_LABEL}.plist"


LEGACY_SYNC_PLIST = "Library/LaunchAgents/com.sucramual.dotfiles-sync.plist"
COLLECT_LABEL = "com.sucramual.agent-trace-collect"
COLLECT_PLIST = f"Library/LaunchAgents/{COLLECT_LABEL}.plist"


BREWFILE = REPO_ROOT / "Brewfile"
BREWFILE_KINDS = ("tap", "brew", "cask", "cargo", "npm")

# Fake brew: log each call's arguments and HOMEBREW_NO_INSTALL_UPGRADE as one line in $HOME/brew.log,
# then exit by subcommand.
FAKE_BREW = """printf '%s HOMEBREW_NO_INSTALL_UPGRADE=%s\\n' "$*" "${{HOMEBREW_NO_INSTALL_UPGRADE-}}" >>"$HOME/brew.log"
case "$2" in
  check) exit {check_exit} ;;
  install) exit {install_exit} ;;
esac
exit 0
"""


def brew_calls(home: Path) -> list[str]:
    log = home / "brew.log"
    return log.read_text().splitlines() if log.exists() else []


def file_state(path: Path) -> tuple[str, int, int]:
    """(content, mtime in ns, inode): a rewrite changes it, even when the content stays the same."""
    stat = path.stat()
    return path.read_text(), stat.st_mtime_ns, stat.st_ino


class Installed:
    """A temp HOME seeded with machine-owned files, after install.sh ran twice in it."""

    def __init__(self, env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool) -> None:
        self.iso = env
        self.home = env.home
        # Without GIT_CONFIG_GLOBAL, `git config --global` uses the temp HOME's ~/.gitconfig, as install.sh expects.
        self.env = {key: value for key, value in env.env.items() if key != "GIT_CONFIG_GLOBAL"}
        self.overlay = fake_work_overlay(env.root)
        self.env["DOTFILES_WORK_DIR"] = str(self.overlay)
        self._run_tool = run_tool
        # A fake bun, so a checkout without tools/mmd-ascii/node_modules does not run a real network install.
        fake_exe("bun", "exit 0\n")
        # A fake npx that logs its arguments, so the third-party skills step does not run a real network install.
        fake_exe("npx", 'printf "%s\\n" "$*" >>"$HOME/npx.log"\n')
        # A faked Darwin and a fake brew, so the Brewfile step runs on every OS but never runs real Homebrew.
        # `bundle check` fails, so install.sh must fall through to `bundle install`.
        fake_exe("uname", "echo Darwin\n")
        fake_exe("brew", FAKE_BREW.format(check_exit=1, install_exit=0))
        self._seed()
        self._install("first")
        # The state of each rendered bu file and the sync plist, to show the second install left them alone.
        self.bu_after_first = {name: self.bu_state(name) for name in BU_MACHINE_CONTENT}
        self.sync_plist_after_first = file_state(self.home / SYNC_PLIST)
        self._install("second")

    def _seed(self) -> None:
        home = self.home
        for directory in (".config/git", ".config/bu", ".config/yabai", ".config/skhd", ".config/borders", ".agents"):
            (home / directory).mkdir(parents=True, exist_ok=True)
        gitconfig = str(home / ".gitconfig")
        self.iso.git(self.iso.root, "config", "--file", gitconfig, "credential.helper", "custom-machine-helper")
        self.iso.git(
            self.iso.root, "config", "--file", gitconfig, "include.path", str(home / ".config/git/company.inc")
        )
        (home / ".config/git/ignore").write_text("machine ignore\n")
        (home / ".config/bu/config.toml").write_text("machine bu config\n")
        (home / ".config/bu/dotfiles.toml").write_text("machine bu dotfiles config\n")
        (home / ".config/yabai/yabairc").write_text("machine yabai config\n")
        (home / ".config/skhd/skhdrc").write_text("machine skhd config\n")
        (home / ".config/borders/bordersrc").write_text("machine borders config\n")
        (home / ".config/ghostty/themes").mkdir(parents=True)
        (home / ".config/ghostty/themes/machine-local").write_text("machine theme\n")
        (home / ".agents/.skill-lock.json").write_text('{"token":"must-stay-local"}\n')
        (home / LEGACY_SYNC_PLIST).parent.mkdir(parents=True)
        (home / LEGACY_SYNC_PLIST).write_text("legacy job\n")

    def _install(self, label: str) -> None:
        result = self.run([INSTALLER], cwd=self.iso.root)
        assert result.returncode == 0, f"{label} install.sh run should succeed\n{result.stdout}\n{result.stderr}"

    def bu_state(self, name: str) -> tuple[str, int, int]:
        return file_state(self.home / ".config/bu" / name)

    def run(self, args: list[str | os.PathLike[str]], cwd: Path) -> subprocess.CompletedProcess[str]:
        return self._run_tool(args, cwd=cwd, env=self.env)


@pytest.fixture
def installed(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool) -> Installed:
    return Installed(isolated_env, fake_exe, run_tool)


def test_install_adds_every_third_party_skill_source(installed: Installed):
    manifest = (REPO_ROOT / "skills/third-party.txt").read_text()
    sources = {line.split()[0] for line in manifest.splitlines() if line.strip() and not line.startswith("#")}
    calls = (installed.home / "npx.log").read_text().splitlines()
    called_sources = {call.split()[3] for call in calls if call.startswith("--yes skills@latest add ")}
    assert sources, "skills/third-party.txt should list at least one source"
    assert called_sources == sources, "install should run `npx skills add` once for each manifest source"


def test_install_links_managed_configs(installed: Installed):
    for target, source in MANAGED_LINKS.items():
        link = installed.home / target
        assert link.is_symlink(), f"{link} should be a symlink"
        assert os.readlink(link) == str(REPO_ROOT / source), f"{link} points to the wrong source"


def test_install_keeps_machine_git_config_and_loads_managed_preferences(installed: Installed):
    home = installed.home
    gitconfig = str(home / ".gitconfig")
    managed_include = str(home / ".config/git/dotfiles.inc")

    helper = installed.run(["git", "config", "--file", gitconfig, "credential.helper"], cwd=installed.iso.root)
    assert helper.stdout.strip() == "custom-machine-helper", "install should preserve the machine credential helper"
    includes = installed.run(
        ["git", "config", "--file", gitconfig, "--get-all", "include.path"], cwd=installed.iso.root
    )
    assert includes.stdout.splitlines().count(managed_include) == 1, (
        "install should add the managed Git include exactly once"
    )
    user_name = installed.run(["git", "config", "--includes", "--global", "user.name"], cwd=installed.iso.root)
    assert user_name.stdout.strip() == "sucramual", "Git should load the managed global preferences"

    fixture = installed.iso.root / "git-ignore-fixture"
    installed.iso.git(installed.iso.root, "init", "-q", str(fixture))
    (fixture / ".cheese").mkdir()
    (fixture / ".cheese/state").write_text("generated state\n")
    ignored = installed.run(["git", "-C", fixture, "check-ignore", "-q", ".cheese/state"], cwd=installed.iso.root)
    assert ignored.returncode == 0, "Git should load the managed global ignore file"


def test_install_backs_up_existing_machine_configs(installed: Installed):
    for backup, message in EXPECTED_BACKUPS:
        assert (installed.home / backup).is_file(), message


def test_install_renders_bu_configs_for_the_current_home(installed: Installed):
    home = installed.home
    config = (home / ".config/bu/config.toml").read_text()
    dotfiles = (home / ".config/bu/dotfiles.toml").read_text()

    assert config == WORK_BU_TEMPLATE.replace("__HOME__", str(home)), (
        "bu config should render the work overlay's template for the current HOME"
    )
    assert f'path = "{home}/dotfiles"' in dotfiles, "bu dotfiles config should render the current HOME"
    assert SOURCE_LAPTOP_HOME not in config and SOURCE_LAPTOP_HOME not in dotfiles, (
        "rendered bu configs should not retain the source laptop's home path"
    )
    bu_dir = home / ".config/bu"
    for bu_file, machine_content in BU_MACHINE_CONTENT.items():
        assert installed.bu_state(bu_file) == installed.bu_after_first[bu_file], (
            f"a second install should not rewrite the rendered {bu_file} (content, mtime, inode)"
        )
        assert (bu_dir / f"{bu_file}.bak").read_text() == machine_content, (
            f"a second install should keep the machine {bu_file} in its first backup"
        )
        extra_backups = sorted(path.name for path in bu_dir.glob(f"{bu_file}.bak.*"))
        assert extra_backups == [], f"a second install should not back up the rendered {bu_file} again"


def test_rendered_bu_configs_keep_worktrees_with_ignored_agent_notes(installed: Installed):
    # git worktree remove deletes ignored files, so bu prune must skip worktrees that hold these notes.
    # A keep list inside the last [[benches]] table would parse, but bu would ignore it.
    for bu_file in ("config.toml", "dotfiles.toml"):
        config = tomllib.loads((installed.home / ".config/bu" / bu_file).read_text())
        assert config.get("prune", {}).get("keep") == BU_PRUNE_KEEP, (
            f"rendered {bu_file} should set a top-level [prune] keep list"
        )


def test_install_loads_the_sync_job_once_and_retires_the_legacy_job(installed: Installed):
    home = installed.home
    plist_path = home / SYNC_PLIST
    job = plistlib.loads(plist_path.read_bytes())

    assert job["Label"] == SYNC_LABEL
    assert job["StartInterval"] == 900, "the sync job should run every 15 minutes"
    assert job["ProcessType"] == "Background"
    assert job["ProgramArguments"] == ["/bin/bash", f"{home}/dotfiles/tools/dotfiles-pr/sync-job"]
    path = job["EnvironmentVariables"]["PATH"].split(":")
    for directory in (f"{home}/.local/bin", "/opt/homebrew/bin", "/usr/bin"):
        assert directory in path, f"the sync job PATH should include {directory} (uv, gh, git, python3)"
    assert job["StandardOutPath"] == job["StandardErrorPath"] == f"{home}/Library/Logs/dotfiles-pr/sync.log"
    assert (home / "Library/Logs/dotfiles-pr").is_dir(), "install should create the log directory for launchd"
    assert SOURCE_LAPTOP_HOME not in plist_path.read_text(), "the plist should render the current HOME"
    assert not (home / LEGACY_SYNC_PLIST).exists(), "install should remove the legacy sync job"

    domain = f"gui/{os.getuid()}"
    assert (home / "launchctl.log").read_text().splitlines() == [
        f"unload {home / LEGACY_SYNC_PLIST}",
        f"bootout {domain}/{SYNC_LABEL}",
        f"bootstrap {domain} {plist_path}",
        f"bootout {domain}/{COLLECT_LABEL}",
        f"bootstrap {domain} {home / COLLECT_PLIST}",
        f"print {domain}/{SYNC_LABEL}",
        f"print {domain}/{COLLECT_LABEL}",
    ], "the first install should load the jobs; the second should only check that they are loaded"
    assert file_state(plist_path) == installed.sync_plist_after_first, (
        "a second install should not rewrite the current sync plist (content, mtime, inode)"
    )


# Protects: launchd runs agent-trace collect from this checkout on the Mac, rendered for the current HOME.
# Bug caught: install.sh never loads the collect job, so Claude Code and Codex export spans to nothing.
def test_install_loads_the_agent_trace_collect_job(installed: Installed):
    home = installed.home
    job = plistlib.loads((home / COLLECT_PLIST).read_bytes())

    assert job["Label"] == COLLECT_LABEL
    assert job["ProgramArguments"][-2:] == [f"{home}/dotfiles/tools/agent-trace/bin/agent-trace", "collect"]
    assert job["StandardErrorPath"] == f"{home}/Library/Logs/agent-trace/collect.log"
    assert (home / "Library/Logs/agent-trace").is_dir(), "install should create the log directory for launchd"


# Protects: a machine without the work overlay gets no bench config, and keeps the config.toml it has.
# Bug caught: install.sh renders a bench template that the public repo no longer holds and stops, or
# replaces the machine's own bu config with nothing.
def test_install_without_a_work_overlay_skips_the_bench_bu_config(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    bu_dir = isolated_env.home / ".config/bu"
    bu_dir.mkdir(parents=True)
    (bu_dir / "config.toml").write_text("machine bu config\n")
    absent = isolated_env.root / "no-overlay"

    result = run_installer_once(
        isolated_env,
        fake_exe,
        run_tool,
        os_name="Darwin",
        brew=FAKE_BREW.format(check_exit=0, install_exit=0),
        DOTFILES_WORK_DIR=str(absent),
    )

    assert f"  No work bu config in {absent}; skipped ~/.config/bu/config.toml" in result.stdout.splitlines()
    assert (bu_dir / "config.toml").read_text() == "machine bu config\n", "install should keep the machine bu config"
    assert sorted(path.name for path in bu_dir.glob("config.toml.bak*")) == [], "nothing replaced, so no backup"
    dotfiles = tomllib.loads((bu_dir / "dotfiles.toml").read_text())
    assert dotfiles["repository"]["path"] == f"{isolated_env.home}/dotfiles", "the dotfiles bu config still renders"


def test_sync_job_runs_sync_without_prune():
    assert '"$dotfiles_pr" sync --no-prune' in (REPO_ROOT / "tools/dotfiles-pr/sync-job").read_text(), (
        "the sync job should skip the prune; only a manual sync prunes dotfiles, as bu-prune covers only work benches"
    )


def test_install_leaves_agent_package_state_alone(installed: Installed):
    assert "must-stay-local" in (installed.home / ".agents/.skill-lock.json").read_text(), (
        "install should not overwrite agent login or package-manager state"
    )


def test_shell_startup_files_do_not_hardcode_source_laptop_home():
    for name in ("zprofile", "zshrc"):
        assert SOURCE_LAPTOP_HOME not in (REPO_ROOT / "config" / "shell" / name).read_text(), (
            "shell startup files should not contain the source laptop's home path"
        )


def test_installed_zshrc_finds_adjacent_aliases_through_symlink(installed: Installed):
    oh_my_zsh = installed.home / ".oh-my-zsh"
    oh_my_zsh.mkdir()
    (oh_my_zsh / "oh-my-zsh.sh").touch()

    result = installed.run(["zsh", "-c", 'source "$HOME/.zshrc"; whence cdx-notes >/dev/null'], cwd=installed.iso.root)

    assert result.returncode == 0, (
        f"the installed zshrc should find its adjacent aliases through the managed symlink\n{result.stderr}"
    )


BREW_CHECK = f"bundle check --no-upgrade --file {BREWFILE} HOMEBREW_NO_INSTALL_UPGRADE="
# HOMEBREW_NO_INSTALL_UPGRADE=1 stops `brew install` from upgrading listed packages that are outdated.
BREW_INSTALL = f"bundle install --file {BREWFILE} --no-upgrade HOMEBREW_NO_INSTALL_UPGRADE=1"
BREW_RERUN = f'run: HOMEBREW_NO_INSTALL_UPGRADE=1 brew bundle install --file "{BREWFILE}" --no-upgrade'


def test_install_installs_missing_brewfile_packages_without_upgrades(installed: Installed):
    assert brew_calls(installed.home) == [BREW_CHECK, BREW_INSTALL] * 2, (
        "each run should check the repo Brewfile, then install missing packages without upgrades"
    )


def run_installer_once(
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    *,
    os_name: str,
    brew: str,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")  # no real third-party skills install
    fake_exe("uname", f"echo {os_name}\n")
    fake_exe("brew", brew)
    env = {key: value for key, value in isolated_env.env.items() if key != "GIT_CONFIG_GLOBAL"} | extra_env
    result = run_tool([INSTALLER], cwd=isolated_env.root, env=env)
    assert result.returncode == 0, f"install.sh should succeed\n{result.stdout}\n{result.stderr}"
    return result


def test_install_skips_brew_bundle_install_when_check_passes(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    brew = FAKE_BREW.format(check_exit=0, install_exit=0)
    result = run_installer_once(isolated_env, fake_exe, run_tool, os_name="Darwin", brew=brew)
    assert brew_calls(isolated_env.home) == [BREW_CHECK]
    assert "  Homebrew packages already installed (Brewfile)" in result.stdout.splitlines()


def test_install_warns_and_continues_when_brew_bundle_install_fails(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    brew = FAKE_BREW.format(check_exit=1, install_exit=1)
    result = run_installer_once(isolated_env, fake_exe, run_tool, os_name="Darwin", brew=brew)
    assert brew_calls(isolated_env.home) == [BREW_CHECK, BREW_INSTALL]
    assert "WARNING: brew bundle install failed" in result.stdout
    assert BREW_RERUN in result.stdout
    assert (isolated_env.home / ".zshrc").is_symlink(), "install.sh should finish the later steps after the warning"


def test_install_does_not_call_brew_on_linux(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    brew = FAKE_BREW.format(check_exit=1, install_exit=0)
    result = run_installer_once(isolated_env, fake_exe, run_tool, os_name="Linux", brew=brew)
    assert brew_calls(isolated_env.home) == [], "install.sh should not call brew on Linux"
    assert "  Homebrew packages skipped (macOS only)" in result.stdout.splitlines()
    assert "  launchd sync job skipped (macOS only)" in result.stdout.splitlines()
    assert not (isolated_env.home / "launchctl.log").exists(), "install.sh should not call launchctl on Linux"


def test_brewfile_lists_only_bundle_entries():
    entries = [line for line in BREWFILE.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert entries, "Brewfile should list packages"
    for line in entries:
        assert line.split(" ", 1)[0] in BREWFILE_KINDS, f"unexpected Brewfile line: {line!r}"
        assert line.count('"') % 2 == 0, f"unbalanced quotes in Brewfile line: {line!r}"


def copy_checkout_without_node_modules(destination: Path) -> Path:
    """Copy the checkout's tracked and untracked, not-ignored files, so tools/mmd-ascii/node_modules is absent.

    The real checkout may hold node_modules, which makes install.sh skip the mmd-ascii step.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode()
    for name in filter(None, listed.split("\0")):
        source = REPO_ROOT / name
        if not source.exists() and not source.is_symlink():
            continue  # deleted in the working tree but still in the index
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
    assert not (destination / "tools/mmd-ascii/node_modules").exists()
    return destination


def run_copied_installer(isolated_env: IsolatedEnv, run_tool: RunTool, path: str) -> tuple[Path, str]:
    checkout = copy_checkout_without_node_modules(isolated_env.root / "checkout")
    env = {key: value for key, value in isolated_env.env.items() if key != "GIT_CONFIG_GLOBAL"}
    env["PATH"] = path
    result = run_tool([checkout / "install.sh"], cwd=isolated_env.root, env=env)
    assert result.returncode == 0, f"install.sh should succeed\n{result.stdout}\n{result.stderr}"
    return checkout, result.stdout


def test_install_warns_and_continues_without_bun_npm_or_brew(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    # A fake on PATH still satisfies `command -v`, so the test removes the real PATH instead.
    # PATH is the fakes dir plus the base system dirs. python3 and git are linked into the fakes dir.
    bin_dir = isolated_env.bin
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "python3").symlink_to(os.path.realpath(sys.executable))
    git = shutil.which("git")
    assert git, "the test needs git"
    (bin_dir / "git").symlink_to(git)
    fake_exe("uname", "echo Darwin\n")
    path = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    for tool in ("bun", "npm", "npx", "brew"):
        assert shutil.which(tool, path=path) is None, f"precondition: {tool} must not be on the reduced PATH"

    checkout, output = run_copied_installer(isolated_env, run_tool, path)

    lines = output.splitlines()
    assert "  WARNING: Homebrew is not installed; skipped the Brewfile packages." in lines
    assert "  WARNING: neither bun nor npm is available; skipped mmd-ascii dependencies." in lines
    assert f"  Install Node.js or Bun, then rerun: {checkout}/install.sh" in lines
    assert not any("npm install" in line for line in lines), "the hint should work when only Bun is installed"
    assert "  Installed mmd-ascii dependencies" not in lines
    assert any(line.startswith("  WARNING: npx is unavailable") for line in lines), (
        "install.sh should reach the later third-party skills step"
    )
    assert lines[-1] == "Done. Re-open shell + Claude Code to apply changes."


def test_install_warns_and_continues_when_mmd_ascii_install_fails(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    fake_exe("bun", "exit 1\n")
    fake_exe("npx", "exit 0\n")  # no real third-party skills install
    fake_exe("uname", "echo Linux\n")

    checkout, output = run_copied_installer(isolated_env, run_tool, isolated_env.env["PATH"])

    lines = output.splitlines()
    assert "  WARNING: bun install failed for mmd-ascii; ~/bin/mmd-ascii may not work." in lines
    assert f'  Fix the error above, then run: (cd "{checkout}/tools/mmd-ascii" && bun install)' in lines
    assert "  Installed mmd-ascii dependencies" not in lines
    assert lines[-1] == "Done. Re-open shell + Claude Code to apply changes."


def test_install_links_the_reviewers_file_where_review_pr_reads_it_under_xdg(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    fake_exe("uname", "echo Linux\n")
    config = isolated_env.root / "xdg-config"
    isolated_env.env["XDG_CONFIG_HOME"] = str(config)

    checkout, _ = run_copied_installer(isolated_env, run_tool, isolated_env.env["PATH"])

    link = config / "review-pr/reviewers.json"
    assert link.is_symlink(), "review-pr reads $XDG_CONFIG_HOME/review-pr/reviewers.json when it is absolute"
    assert link.resolve() == checkout / "config/review-pr/reviewers.json"


# ---- no ro install --------------------------------------------------------------------------------

KEPT_COMMANDS = {"echo kept-stop-hook", "/opt/guard.sh pre-tool-use"}


def seed_settings(home: Path) -> dict:
    """Write settings that already hold the owner's own hooks and keys."""
    settings = {
        "model": "opus",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo kept-stop-hook"}]}],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/guard.sh pre-tool-use"}]}
            ],
        },
    }
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude/settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return settings


def hook_commands(settings: dict) -> list[str]:
    return [hook["command"] for groups in settings["hooks"].values() for group in groups for hook in group["hooks"]]


# Protects: install.sh no longer installs or runs ro, and it keeps the owner's settings as they are.
# Bug caught: a leftover `uv tool install` of ro, or a leftover `ro record install` that adds hooks for a command
# that new machines no longer have.
def test_install_neither_installs_nor_runs_ro(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    seed_settings(isolated_env.home)
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    fake_exe("uname", "echo Linux\n")

    _, output = run_copied_installer(isolated_env, run_tool, isolated_env.env["PATH"])

    lines = output.splitlines()
    assert lines[-1] == "Done. Re-open shell + Claude Code to apply changes.", "install.sh should finish"
    uv_log = isolated_env.home / "uv.log"
    uv_calls = uv_log.read_text().splitlines() if uv_log.exists() else []
    assert not [call for call in uv_calls if call.startswith("tool ")], (
        f"install.sh should install no uv tool: {uv_calls}"
    )
    assert not (isolated_env.home / "ro.log").exists(), "install.sh should not run ro"
    settings = json.loads((isolated_env.home / ".claude/settings.json").read_text())
    # install.sh adds only its own guard_irreversible and agent-trace hooks, which other tests cover.
    owner_commands = [
        command for command in hook_commands(settings) if not command.endswith((GUARD_NAME, TRACE_SUFFIX))
    ]
    assert sorted(owner_commands) == sorted(KEPT_COMMANDS), "install.sh should keep the owner's hooks"
    assert (isolated_env.home / ".config/review-pr/reviewers.json").is_symlink(), "the reviewers link should stay"


# ---- guard_irreversible hook ----------------------------------------------------------------------

GUARD_NAME = "guard_irreversible.py"
TRACE_SUFFIX = "agent-trace hook"


# Protects: install.sh registers the guard hook for both Claude Code and Codex, and keeps the owner's hooks.
# Bug caught: a missing or misdirected install_hooks.py call, which leaves an agent without the merge guard.
def test_install_registers_the_guard_hook(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool):
    seed_settings(isolated_env.home)
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    fake_exe("uname", "echo Linux\n")

    checkout, _ = run_copied_installer(isolated_env, run_tool, isolated_env.env["PATH"])

    expected = f"python3 {checkout / 'config/agent-hooks' / GUARD_NAME}"
    for target in (".claude/settings.json", ".codex/hooks.json"):
        settings = json.loads((isolated_env.home / target).read_text())
        groups = [
            group
            for group in settings["hooks"]["PreToolUse"]
            if any(hook["command"] == expected for hook in group["hooks"])
        ]
        assert len(groups) == 1, f"{target} should hold the guard hook once: {settings}"
        assert groups[0]["matcher"] == "Bash"
    claude = json.loads((isolated_env.home / ".claude/settings.json").read_text())
    trace = f"python3 {checkout / 'tools/agent-trace/bin/agent-trace'} hook"
    assert set(hook_commands(claude)) == KEPT_COMMANDS | {expected, trace}, "install.sh should keep the owner's hooks"
