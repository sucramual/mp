"""Black-box tests for the devbox support: the bootstrap steps, the sync loop, on-start, verify-browser, and the
installer section.

Every script runs with a temp HOME and fake gh, tmux, uname, sleep, sudo, npx, claude, and codex commands first on
PATH. No test reaches GitHub, starts a real tmux session or Chrome, installs a package, changes a real MCP config,
or touches the real HOME.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

BOOTSTRAP_STEP = REPO_ROOT / "config/devbox/bootstrap.d/20-dotfiles"
ON_START = REPO_ROOT / "config/devbox/on-start"
SYNC_LOOP = REPO_ROOT / "tools/dotfiles-pr/sync-loop"
SYNC_JOB = REPO_ROOT / "tools/dotfiles-pr/sync-job"
INSTALL_DEVBOX = REPO_ROOT / "scripts/install_devbox.sh"
INSTALLER = REPO_ROOT / "install.sh"
VERIFY_BROWSER_STEP = REPO_ROOT / "config/devbox/bootstrap.d/30-verify-browser"
VERIFY_BROWSER = REPO_ROOT / "config/devbox/verify-browser/verify-browser"

RunTool = Callable[..., subprocess.CompletedProcess[str]]
FakeExe = Callable[..., Path]

# Fake gh: `auth status` follows $HOME/gh.authed.
# `repo clone <repo> <dir>` logs, then makes <dir> with a fake install.sh. It fails, and makes nothing, when
# $HOME/gh.fail.<repo with / as _> exists.
FAKE_GH = """printf '%s\\n' "$*" >>"$HOME/gh.log"
case "$1 $2" in
  "auth status") [ -e "$HOME/gh.authed" ] || { echo "You are not logged in" >&2; exit 1; } ;;
  "repo clone")
    [ -e "$HOME/gh.fail.${3//\\//_}" ] && { echo "GraphQL: Could not resolve to a Repository" >&2; exit 1; }
    mkdir -p "$4"
    printf '#!/bin/bash\\necho install >>"$HOME/install.log"\\n' >"$4/install.sh"
    printf 'exit "$(cat "$HOME/install.exit" 2>/dev/null || echo 0)"\\n' >>"$4/install.sh"
    chmod +x "$4/install.sh"
    ;;
esac
exit 0
"""

# Fake tmux with state: a session exists once `new-session -s <name>` ran. Each call is logged.
FAKE_TMUX = """printf '%s\\n' "$*" >>"$HOME/tmux.log"
case "$1" in
  has-session) [ -e "$HOME/tmux.session.$3" ] ;;
  new-session) touch "$HOME/tmux.session.$4" ;;
esac
"""


# Fake claude and codex `mcp get` and `mcp add`, with state in @MCP@/<tool>. `add` stores the server as JSON:
# its scope (claude only) and the command that starts it. Each add is also logged, so a test can count them.
FAKE_MCP_CLI = """dir="@MCP@/@TOOL@"
mkdir -p "$dir"
case "$1 $2" in
  "mcp get") [ -e "$dir/$3.json" ] ;;
  "mcp add")
    shift 2
    scope=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -s | --scope) scope=$2; shift 2 ;;
        --) shift; break ;;
        *) name=$1; shift ;;
      esac
    done
    echo "$name" >>"$dir/adds.log"
    python3 -c 'import json, sys; json.dump({"scope": sys.argv[2], "command": sys.argv[3:]}, open(sys.argv[1], "w"))' \\
      "$dir/$name.json" "$scope" "$@" ;;
  *) echo "fake @TOOL@: unexpected command: $*" >&2; exit 2 ;;
esac
"""


def lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


@pytest.fixture
def home(isolated_env: IsolatedEnv) -> Path:
    return isolated_env.home


# --- bootstrap step ---------------------------------------------------------------------------------------------


@pytest.fixture
def bootstrap(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool
) -> Callable[[], subprocess.CompletedProcess[str]]:
    fake_exe("gh", FAKE_GH)
    return lambda: run_tool(["/bin/bash", BOOTSTRAP_STEP], cwd=isolated_env.root)


def test_bootstrap_step_refuses_without_gh_login_and_does_nothing_else(bootstrap, home: Path):
    result = bootstrap()

    assert result.returncode != 0, "the step should fail so the devbox bootstrap shows 'needs you'"
    assert "gh auth login" in result.stdout + result.stderr, "the step should name the command the engineer runs"
    assert lines(home / "gh.log") == ["auth status"], "the step should call no other gh command"
    assert not (home / "dotfiles").exists(), "the step should not clone"
    assert not (home / "install.log").exists(), "the step should not run install.sh"


def test_bootstrap_step_clones_then_installs(bootstrap, home: Path):
    (home / "gh.authed").touch()

    result = bootstrap()

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"repo clone sucramual/mp {home}/dotfiles" in lines(home / "gh.log")
    assert lines(home / "install.log") == ["install"]


def test_bootstrap_step_keeps_an_existing_checkout_and_is_idempotent(bootstrap, home: Path):
    (home / "gh.authed").touch()
    (home / "dotfiles").mkdir()
    (home / "dotfiles/install.sh").write_text('#!/bin/bash\necho install >>"$HOME/install.log"\n')
    (home / "dotfiles/install.sh").chmod(0o755)
    (home / "dotfiles-work").mkdir()

    assert bootstrap().returncode == 0
    assert bootstrap().returncode == 0

    assert not any(line.startswith("repo clone") for line in lines(home / "gh.log")), "an existing checkout is kept"
    assert lines(home / "install.log") == ["install", "install"]


def write_overlay_aware_install(home: Path, overlay: Path) -> None:
    """An existing ~/dotfiles whose install.sh logs whether the overlay checkout existed when it ran."""
    (home / "dotfiles").mkdir()
    install = home / "dotfiles/install.sh"
    install.write_text(
        f'#!/bin/bash\n[ -d "{overlay}" ] && word=with-overlay || word=install\necho "$word" >>"$HOME/install.log"\n'
    )
    install.chmod(0o755)


# Protects: a rebuilt devbox gets the work overlay, so install.sh links the work guidance.
# Bug caught: the step clones only sucramual/mp, or clones the overlay after install.sh ran, or ignores
# DOTFILES_WORK_DIR, or clones again over an existing overlay.
@pytest.mark.parametrize("custom_dir", [False, True])
def test_bootstrap_step_clones_the_work_overlay_before_install(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path, custom_dir: bool
):
    fake_exe("gh", FAKE_GH)
    (home / "gh.authed").touch()
    overlay = isolated_env.root / "work" if custom_dir else home / "dotfiles-work"
    env = {"DOTFILES_WORK_DIR": str(overlay)} if custom_dir else {}
    write_overlay_aware_install(home, overlay)

    first = run_tool(["/bin/bash", BOOTSTRAP_STEP], cwd=isolated_env.root, **env)
    second = run_tool(["/bin/bash", BOOTSTRAP_STEP], cwd=isolated_env.root, **env)

    assert first.returncode == 0 and second.returncode == 0, first.stdout + first.stderr
    clones = [line for line in lines(home / "gh.log") if line.startswith("repo clone")]
    assert clones == [f"repo clone sucramual/mp-private {overlay}"], "the overlay should be cloned once"
    assert lines(home / "install.log") == ["with-overlay", "with-overlay"], "install.sh should run after the clone"


# Bug caught: a devbox login without access to the private overlay stops the public install.
def test_bootstrap_step_still_installs_when_the_overlay_clone_fails(bootstrap, home: Path):
    (home / "gh.authed").touch()
    (home / "gh.fail.sucramual_mp-private").touch()

    result = bootstrap()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repo clone sucramual/mp-private" in "\n".join(lines(home / "gh.log")), "the step should try the clone"
    assert not (home / "dotfiles-work").exists()
    assert lines(home / "install.log") == ["install"], "install.sh should still run"
    warnings = [line for line in (result.stdout + result.stderr).splitlines() if "WARNING" in line]
    assert len(warnings) == 1 and "sucramual/mp-private" in warnings[0], result.stdout + result.stderr


def test_bootstrap_step_exits_with_the_install_status(bootstrap, home: Path):
    (home / "gh.authed").touch()
    (home / "install.exit").write_text("7\n")

    assert bootstrap().returncode == 7


# --- sync-job log directory -------------------------------------------------------------------------------------


@pytest.fixture
def sync_job(isolated_env: IsolatedEnv, fake_exe: FakeExe) -> Path:
    """A copy of sync-job beside a fake dotfiles-pr that prints one line."""
    tool_dir = isolated_env.root / "tools/dotfiles-pr"
    tool_dir.mkdir(parents=True)
    script = tool_dir / "sync-job"
    script.write_text(SYNC_JOB.read_text())
    fake_exe("dotfiles-pr", "echo synced\n", directory=tool_dir / "bin")
    return script


@pytest.mark.parametrize(
    ("system", "expected"),
    [("Linux", ".local/state/dotfiles-pr"), ("Darwin", "Library/Logs/dotfiles-pr")],
)
def test_sync_job_default_log_dir_follows_the_platform(
    sync_job: Path, fake_exe: FakeExe, run_tool: RunTool, isolated_env: IsolatedEnv, system: str, expected: str
):
    fake_exe("uname", f"echo {system}\n")

    result = run_tool(["/bin/bash", sync_job], cwd=isolated_env.root)

    assert result.returncode == 0, result.stderr
    log = isolated_env.home / expected / "sync.log"
    assert log.exists(), f"{system} should log to ~/{expected}"
    assert "ok: synced" in log.read_text()


def test_sync_job_log_dir_override_wins_on_linux(
    sync_job: Path, fake_exe: FakeExe, run_tool: RunTool, isolated_env: IsolatedEnv
):
    fake_exe("uname", "echo Linux\n")
    override = isolated_env.root / "custom-logs"

    run_tool(["/bin/bash", sync_job], cwd=isolated_env.root, DOTFILES_SYNC_LOG_DIR=str(override))

    assert (override / "sync.log").exists()
    assert not (isolated_env.home / ".local/state/dotfiles-pr").exists()


# --- sync-loop --------------------------------------------------------------------------------------------------


def test_sync_loop_runs_sync_job_every_15_minutes_and_survives_failures(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    tool_dir = isolated_env.root / "tools/dotfiles-pr"
    tool_dir.mkdir(parents=True)
    loop = tool_dir / "sync-loop"
    loop.write_text(SYNC_LOOP.read_text())
    loop.chmod(0o755)
    fake_exe("sync-job", 'echo run >>"$HOME/sync-job.log"\nexit 1\n', directory=tool_dir)
    # The third sleep kills the loop (its parent), so the test ends.
    fake_exe(
        "sleep",
        'echo "$1" >>"$HOME/sleep.log"\n[ "$(wc -l <"$HOME/sleep.log")" -ge 3 ] && kill "$PPID"\nexit 0\n',
    )

    run_tool(["/bin/bash", loop], cwd=isolated_env.root)

    assert lines(home / "sleep.log") == ["900", "900", "900"], "the loop should wait 900 seconds between runs"
    assert lines(home / "sync-job.log") == ["run"] * 3, "a failing sync-job should not stop the loop"


# Protects: the devbox, which has no launchd, keeps agent-trace collect running through the sync loop.
# Bug caught: the loop never starts collect, or a failing collect stops the sync loop.
def test_sync_loop_ensures_agent_trace_collect_each_round(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    tool_dir = isolated_env.root / "tools/dotfiles-pr"
    tool_dir.mkdir(parents=True)
    loop = tool_dir / "sync-loop"
    loop.write_text(SYNC_LOOP.read_text())
    loop.chmod(0o755)
    fake_exe("sync-job", 'echo run >>"$HOME/sync-job.log"\nexit 0\n', directory=tool_dir)
    trace_bin = isolated_env.root / "tools/agent-trace/bin"
    trace_bin.mkdir(parents=True)
    fake_exe("agent-trace", 'echo "$*" >>"$HOME/agent-trace.log"\nexit 1\n', directory=trace_bin)
    fake_exe(
        "sleep",
        'echo "$1" >>"$HOME/sleep.log"\n[ "$(wc -l <"$HOME/sleep.log")" -ge 2 ] && kill "$PPID"\nexit 0\n',
    )

    run_tool(["/bin/bash", loop], cwd=isolated_env.root)

    assert lines(home / "agent-trace.log") == ["collect --ensure"] * 2, "each round should ensure collect runs"
    assert lines(home / "sync-job.log") == ["run"] * 2, "a failing collect should not stop the sync loop"


# --- on-start ---------------------------------------------------------------------------------------------------


def test_on_start_starts_the_sync_session_once(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    fake_exe("tmux", FAKE_TMUX)
    link = home / ".config/devbox/on-start"
    link.parent.mkdir(parents=True)
    link.symlink_to(ON_START)  # the real entry point is the symlink, so on-start must resolve its own path

    first = run_tool([link], cwd=isolated_env.root)
    second = run_tool([link], cwd=isolated_env.root)

    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    new_sessions = [line for line in lines(home / "tmux.log") if line.startswith("new-session")]
    assert len(new_sessions) == 1, "the second run should find the session and start nothing"
    assert "-s dotfiles-sync" in new_sessions[0]
    assert str(SYNC_LOOP) in new_sessions[0], "the session should run the repo's sync-loop"


def test_on_start_without_tmux_does_not_fail(isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool):
    # A PATH of only /usr/bin-less fakes: bash, dirname, and readlink come from links in a private bin dir.
    private = isolated_env.root / "private-bin"
    private.mkdir()
    for tool in ("bash", "dirname", "readlink", "cat", "command"):
        found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True).stdout.strip()
        if found.startswith("/"):
            (private / tool).symlink_to(found)

    result = run_tool([ON_START], cwd=isolated_env.root, env={**isolated_env.env, "PATH": str(private)})

    assert result.returncode == 0, result.stderr


# --- install_devbox.sh ------------------------------------------------------------------------------------------


class Devbox:
    def __init__(self, iso: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool) -> None:
        self.iso = iso
        self.home = iso.home
        self.run_tool = run_tool
        self.marker = iso.root / "opt-devbox"
        self.mcp = iso.root / "mcp"
        fake_exe("uname", "echo Linux\n")
        fake_exe("tmux", FAKE_TMUX)
        for tool in ("claude", "codex"):
            fake_exe(tool, FAKE_MCP_CLI.replace("@MCP@", str(self.mcp)).replace("@TOOL@", tool))

    def install(self, script: Path = INSTALL_DEVBOX, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {"DOTFILES_DEVBOX_MARKER": str(self.marker), "DOTFILES_DIR": str(REPO_ROOT), **extra_env}
        return self.run_tool(["/bin/bash", script], cwd=self.iso.root, **env)

    @property
    def bootstrap_link(self) -> Path:
        return self.home / ".config/devbox/bootstrap.d/20-dotfiles"

    @property
    def on_start_link(self) -> Path:
        return self.home / ".config/devbox/on-start"

    def tmux_new_sessions(self) -> list[str]:
        return [line for line in lines(self.home / "tmux.log") if line.startswith("new-session")]

    def mcp_server(self, tool: str, name: str = "chrome-devtools") -> dict:
        return json.loads((self.mcp / tool / f"{name}.json").read_text())

    def mcp_adds(self, tool: str) -> list[str]:
        return lines(self.mcp / tool / "adds.log")


@pytest.fixture
def devbox(isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool) -> Devbox:
    return Devbox(isolated_env, fake_exe, run_tool)


def snapshot(home: Path) -> dict[str, str]:
    """Every path under HOME with its type and link target, so a re-run that changes anything shows up."""
    result: dict[str, str] = {}
    for path in sorted(home.rglob("*")):
        key = str(path.relative_to(home))
        if "tmux" in key:
            continue
        result[key] = os.readlink(path) if path.is_symlink() else ("dir" if path.is_dir() else path.read_text())
    return result


def test_install_devbox_links_the_hooks_and_starts_the_session(devbox: Devbox):
    devbox.marker.mkdir()

    result = devbox.install()

    assert result.returncode == 0, result.stdout + result.stderr
    assert os.readlink(devbox.bootstrap_link) == str(REPO_ROOT / "config/devbox/bootstrap.d/20-dotfiles")
    assert os.readlink(devbox.on_start_link) == str(REPO_ROOT / "config/devbox/on-start")
    assert len(devbox.tmux_new_sessions()) == 1, "install should start the dotfiles-sync session now"


def test_install_devbox_rerun_changes_nothing(devbox: Devbox):
    devbox.marker.mkdir()
    devbox.install()
    before = snapshot(devbox.home)

    result = devbox.install()

    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(devbox.home) == before, "a second run should change no file or link"
    assert len(devbox.tmux_new_sessions()) == 1, "a second run should not start a second session"


def test_install_devbox_skips_off_a_devbox(devbox: Devbox):
    result = devbox.install()  # the marker directory does not exist

    assert result.returncode == 0
    assert "skipped (not a devbox)" in result.stdout
    assert not (devbox.home / ".config/devbox").exists()
    assert devbox.tmux_new_sessions() == []
    assert not devbox.mcp.exists(), "the Chrome DevTools MCP server is registered on the devbox only"


def test_install_devbox_skips_on_macos_even_if_the_marker_exists(devbox: Devbox, fake_exe: FakeExe):
    devbox.marker.mkdir()
    fake_exe("uname", "echo Darwin\n")

    result = devbox.install()

    assert "skipped (not a devbox)" in result.stdout
    assert not (devbox.home / ".config/devbox").exists()
    assert not devbox.mcp.exists(), "the Mac never gets the Chrome DevTools MCP server"


def test_install_devbox_env_zero_forces_off(devbox: Devbox):
    devbox.marker.mkdir()

    result = devbox.install(DOTFILES_DEVBOX="0")

    assert "skipped (not a devbox)" in result.stdout
    assert not (devbox.home / ".config/devbox").exists()


def test_install_devbox_env_one_forces_on(devbox: Devbox):
    result = devbox.install(DOTFILES_DEVBOX="1")  # no marker directory

    assert result.returncode == 0, result.stdout + result.stderr
    assert devbox.on_start_link.is_symlink()


def test_install_devbox_keeps_a_user_on_start_and_prints_the_line_to_add(devbox: Devbox):
    devbox.marker.mkdir()
    devbox.on_start_link.parent.mkdir(parents=True)
    devbox.on_start_link.write_text("#!/bin/bash\necho mine\n")

    result = devbox.install()

    assert result.returncode == 0
    assert devbox.on_start_link.read_text() == "#!/bin/bash\necho mine\n", "the user's on-start must stay"
    assert not devbox.on_start_link.is_symlink()
    assert not list(devbox.on_start_link.parent.glob("on-start.bak*")), "the user's on-start is not moved"
    assert "WARNING" in result.stdout
    assert f"{REPO_ROOT}/config/devbox/on-start" in result.stdout, "the warning names the line to add"
    assert os.readlink(devbox.bootstrap_link).endswith("20-dotfiles"), "the other steps still run"


def test_install_devbox_backs_up_a_regular_bootstrap_file(devbox: Devbox):
    devbox.marker.mkdir()
    devbox.bootstrap_link.parent.mkdir(parents=True)
    devbox.bootstrap_link.write_text("old step\n")

    devbox.install()

    assert devbox.bootstrap_link.is_symlink()
    assert (devbox.bootstrap_link.parent / "20-dotfiles.bak").read_text() == "old step\n"


def test_install_devbox_replaces_a_stale_bootstrap_symlink(devbox: Devbox):
    devbox.marker.mkdir()
    devbox.bootstrap_link.parent.mkdir(parents=True)
    devbox.bootstrap_link.symlink_to("/nonexistent/old-20-dotfiles")

    devbox.install()

    assert os.readlink(devbox.bootstrap_link) == str(REPO_ROOT / "config/devbox/bootstrap.d/20-dotfiles")


def test_install_sh_calls_the_devbox_section(devbox: Devbox, fake_exe: FakeExe):
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    env = {key: value for key, value in devbox.iso.env.items() if key != "GIT_CONFIG_GLOBAL"}

    result = devbox.run_tool([INSTALLER], cwd=devbox.iso.root, env=env, DOTFILES_DEVBOX="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert os.readlink(devbox.bootstrap_link) == str(REPO_ROOT / "config/devbox/bootstrap.d/20-dotfiles")


# --- verify-browser ---------------------------------------------------------------------------------------------

# Fake sudo, dpkg-query, and npx for `verify-browser install`. dpkg-query reports a package installed when
# $HOME/dpkg.installed exists. npx `@puppeteer/browsers install chrome@stable --path DIR` makes a fake Chrome under DIR.
FAKE_SUDO = 'printf "%s\\n" "$*" >>"$HOME/sudo.log"\nexit 0\n'
FAKE_DPKG_QUERY = '[ -e "$HOME/dpkg.installed" ] && printf "install ok installed"\nexit 0\n'
FAKE_NPX = """printf '%s\\n' "$*" >>"$HOME/npx.log"
prev=""
for arg in "$@"; do
  [ "$prev" = --path ] && dir=$arg
  prev=$arg
done
mkdir -p "$dir/chrome/linux-156.0.8078.80/chrome-linux64"
printf '#!/bin/bash\\nexit 0\\n' >"$dir/chrome/linux-156.0.8078.80/chrome-linux64/chrome"
chmod +x "$dir/chrome/linux-156.0.8078.80/chrome-linux64/chrome"
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def install_fake_browser(home: Path, fake_exe: FakeExe) -> None:
    """Make verify-browser count as installed: a Chrome at the stable path and the display tools on PATH."""
    chrome = home / ".local/share/verify-browser/current/chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("#!/bin/bash\nexit 0\n")
    chrome.chmod(0o755)
    for tool in ("Xvfb", "x11vnc", "websockify"):
        fake_exe(tool, "exit 0\n")


def verify_browser_sessions(home: Path) -> list[str]:
    return [
        line for line in lines(home / "tmux.log") if line.startswith("new-session") and "-s verify-browser " in line
    ]


# Protects: on-start starts the verify-browser session only when its Chrome is installed, and only once.
# Bug caught: on-start fails or starts a dead session on a devbox without Chrome, or starts a second Chrome on the
# same profile at each start.
def test_on_start_starts_verify_browser_only_when_installed(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    fake_exe("tmux", FAKE_TMUX)

    without = run_tool([ON_START], cwd=isolated_env.root)
    assert without.returncode == 0, without.stdout + without.stderr
    assert verify_browser_sessions(home) == [], "no Chrome is installed, so no verify-browser session starts"
    assert any("dotfiles-sync" in line for line in lines(home / "tmux.log")), "the sync loop still starts"

    install_fake_browser(home, fake_exe)
    first = run_tool([ON_START], cwd=isolated_env.root)
    second = run_tool([ON_START], cwd=isolated_env.root)

    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert len(verify_browser_sessions(home)) == 1, "the second start should find the session and start nothing"
    profile = home / ".local/state/verify-browser/profile"
    for directory in (profile, profile.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, f"{directory} holds the Okta session"


# Protects: the bootstrap step that installs verify-browser exists, runs, and install_devbox.sh links it.
# Bug caught: the step is missing or not executable, so a rebuilt devbox never gets Chrome.
def test_install_devbox_links_the_verify_browser_bootstrap_step(devbox: Devbox):
    devbox.marker.mkdir()

    result = devbox.install()

    assert result.returncode == 0, result.stdout + result.stderr
    link = devbox.home / ".config/devbox/bootstrap.d/30-verify-browser"
    assert os.readlink(link) == str(VERIFY_BROWSER_STEP)
    assert os.access(VERIFY_BROWSER_STEP, os.X_OK) and os.access(VERIFY_BROWSER, os.X_OK)


# Protects: verify-browser install never prompts (apt goes through `sudo -n`), installs the display tools and Chrome
# for Testing, keeps a stable path to Chrome, and does nothing on a re-run.
# Bug caught: sudo waits for a password in an unattended bootstrap; the Chrome path moves with each version; or a
# re-run downloads Chrome and calls apt again.
def test_verify_browser_install_is_non_interactive_and_idempotent(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    for name, body in (("sudo", FAKE_SUDO), ("dpkg-query", FAKE_DPKG_QUERY), ("npx", FAKE_NPX)):
        fake_exe(name, body)

    first = run_tool([VERIFY_BROWSER_STEP], cwd=isolated_env.root)

    assert first.returncode == 0, first.stdout + first.stderr
    sudo_calls = lines(home / "sudo.log")
    assert sudo_calls, "missing packages should be installed through sudo"
    assert all(call.split()[0] == "-n" for call in sudo_calls), f"every sudo call must be non-interactive: {sudo_calls}"
    assert any(all(package in call for package in ("xvfb", "x11vnc", "novnc", "websockify")) for call in sudo_calls)
    chrome = home / ".local/share/verify-browser/current/chrome"
    assert os.access(chrome, os.X_OK), "the stable path should reach the installed Chrome"
    assert len(lines(home / "npx.log")) == 1

    (home / "dpkg.installed").touch()
    second = run_tool([VERIFY_BROWSER_STEP], cwd=isolated_env.root)

    assert second.returncode == 0, second.stdout + second.stderr
    assert len(lines(home / "sudo.log")) == len(sudo_calls), "a re-run should not call apt"
    assert len(lines(home / "npx.log")) == 1, "a re-run should not download Chrome again"


EXAMPLE_OKTA = "https://example.okta.com"


def verify_browser_status(isolated_env: IsolatedEnv, run_tool: RunTool, **env: str) -> tuple[dict, int]:
    """Run `verify-browser status --json` with no Chrome listening. Returns the parsed report and the exit code."""
    result = run_tool(
        [VERIFY_BROWSER, "status", "--json"], cwd=isolated_env.root, VERIFY_BROWSER_PORT=str(free_port()), **env
    )
    return json.loads(result.stdout), result.returncode


# Protects: status --json prints a JSON report that says Chrome does not answer, and exits 1, when no Chrome listens.
# Bug caught: a stack trace or empty output, so auth-helper cannot tell a stopped Chrome from a signed-out session.
def test_verify_browser_status_json_when_chrome_does_not_answer(isolated_env: IsolatedEnv, run_tool: RunTool):
    report, code = verify_browser_status(isolated_env, run_tool, VERIFY_BROWSER_OKTA_URL=EXAMPLE_OKTA)

    assert report["chrome"]["answers"] is False, report
    assert report["okta"] is None
    assert code == 1


# Protects: without an Okta URL, status --json still prints JSON, with an okta.error that says how to set the URL.
# Bug caught: the check opens a built-in company URL, or prints no JSON, so auth-helper cannot report the cause.
def test_verify_browser_status_json_without_an_okta_url_names_the_setting(isolated_env: IsolatedEnv, run_tool: RunTool):
    report, code = verify_browser_status(isolated_env, run_tool)

    assert report["okta"] is not None, report
    error = report["okta"]["error"]
    assert "VERIFY_BROWSER_OKTA_URL" in error and "okta-url" in error, error
    assert report["okta"]["status"] is None and report["okta_url"] is None, report
    assert code == 1


# Protects: the Okta URL comes from VERIFY_BROWSER_OKTA_URL, else from the first line of
# ~/.config/verify-browser/okta-url, and the variable wins over the file.
# Bug caught: the config file is ignored, its trailing newline or spaces end up in the URL, or the file wins.
def test_verify_browser_reads_the_okta_url_from_the_variable_or_the_file(
    isolated_env: IsolatedEnv, run_tool: RunTool, home: Path
):
    config = home / ".config/verify-browser/okta-url"
    config.parent.mkdir(parents=True)
    config.write_text("  https://from-file.okta.com  \nsecond line\n")

    from_file, _ = verify_browser_status(isolated_env, run_tool)
    from_variable, _ = verify_browser_status(isolated_env, run_tool, VERIFY_BROWSER_OKTA_URL=EXAMPLE_OKTA)

    assert from_file["okta_url"] == "https://from-file.okta.com", from_file
    assert from_variable["okta_url"] == EXAMPLE_OKTA, from_variable


# Protects: the keep-alive checks the Okta session every 3600 seconds and appends one JSON line per check, also
# when a check fails.
# Bug caught: a failed check stops the loop, a check writes nothing or several lines, or the interval is wrong.
def test_verify_browser_keepalive_appends_one_json_line_per_check(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    # The second sleep kills the loop (its parent), so the test ends.
    fake_exe(
        "sleep",
        'echo "$1" >>"$HOME/sleep.log"\n[ "$(wc -l <"$HOME/sleep.log")" -ge 2 ] && kill "$PPID"\nexit 0\n',
    )

    config = home / ".config/verify-browser/okta-url"
    config.parent.mkdir(parents=True)
    config.write_text(EXAMPLE_OKTA + "\n")

    run_tool([VERIFY_BROWSER, "keepalive"], cwd=isolated_env.root, VERIFY_BROWSER_PORT=str(free_port()))

    assert lines(home / "sleep.log") == ["3600", "3600"]
    entries = [json.loads(line) for line in lines(home / ".local/state/verify-browser/okta-session.log")]
    assert len(entries) == 2, entries
    assert all(entry["checked_at"] and entry["chrome"]["answers"] is False for entry in entries), entries
    assert all(entry["okta_url"] == EXAMPLE_OKTA for entry in entries), "the keep-alive should use the config file"


def private_verify_browser(root: Path) -> Path:
    """A copy of verify-browser for a test that runs stop. stop ends every `<script> run` loop of its own path, so
    a test that ran stop on the repository copy would end the loops of tests that run in parallel."""
    copy = root / "verify-browser-copy"
    shutil.copytree(VERIFY_BROWSER.parent, copy)
    return copy / "verify-browser"


def spawn_with_profile(profile: str) -> subprocess.Popen[bytes]:
    """A stand-in Chrome: a process whose command line carries --user-data-dir=<profile>."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", f"--user-data-dir={profile}"],
        start_new_session=True,
    )


def gone(process: subprocess.Popen[bytes], seconds: float = 10) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


# Protects: stop ends only the Chrome that uses the verify-browser profile, matched by its --user-data-dir argument.
# Bug caught: stop kills processes by name, or by a profile prefix, and so ends another Chrome on the host.
def test_verify_browser_stop_ends_only_the_chrome_with_its_profile(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    fake_exe("tmux", FAKE_TMUX)
    profile = home / ".local/state/verify-browser/profile"
    ours = spawn_with_profile(str(profile))
    other = spawn_with_profile(f"{profile}-other")
    try:
        result = run_tool([private_verify_browser(isolated_env.root), "stop"], cwd=isolated_env.root)

        assert result.returncode == 0, result.stdout + result.stderr
        assert gone(ours), "the Chrome with the verify-browser profile should stop"
        assert other.poll() is None, "a process with another profile must keep running"
    finally:
        for process in (ours, other):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


# Fake Chrome for `run chrome`: it records which Singleton links exist when it starts. Chrome makes them as links.
FAKE_CHROME_RECORDS_LOCKS = """for name in SingletonLock SingletonSocket SingletonCookie; do
  for arg in "$@"; do
    case "$arg" in --user-data-dir=*) [ -L "${arg#--user-data-dir=}/$name" ] && echo "$name" ;; esac
  done
done >"$HOME/locks-at-start.log"
"""


# Protects: `run chrome` removes the Singleton locks that a killed Chrome left, but only when no process uses the
# profile.
# Bug caught: Chrome refuses to start after a SIGKILL; or the locks of a running Chrome are removed, so two Chromes
# share one profile and damage the Okta session.
@pytest.mark.parametrize("running", [False, True])
def test_verify_browser_clears_stale_locks_only_when_no_chrome_uses_the_profile(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path, running: bool
):
    install_fake_browser(home, fake_exe)
    chrome = home / ".local/share/verify-browser/current/chrome"
    chrome.write_text("#!/bin/bash\n" + FAKE_CHROME_RECORDS_LOCKS)
    profile = home / ".local/state/verify-browser/profile"
    profile.mkdir(parents=True)
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        (profile / name).symlink_to("stale-host-1234")
    display_socket = isolated_env.root / "X99"
    display_socket.touch()
    # The window loops; the first restart pause ends the test.
    fake_exe("sleep", 'kill "$PPID"\nexit 0\n')
    holder = spawn_with_profile(str(profile)) if running else None
    try:
        run_tool(
            [VERIFY_BROWSER, "run", "chrome"], cwd=isolated_env.root, VERIFY_BROWSER_DISPLAY_SOCKET=str(display_socket)
        )
    finally:
        if holder is not None:
            os.killpg(holder.pid, signal.SIGKILL)
            holder.wait()

    seen = lines(home / "locks-at-start.log")
    assert (home / "locks-at-start.log").exists(), "the fake Chrome should have started"
    if running:
        assert sorted(seen) == ["SingletonCookie", "SingletonLock", "SingletonSocket"], seen
    else:
        assert seen == [], seen


# Protects: install_devbox.sh registers the Chrome DevTools MCP server for Claude Code (user scope) and Codex,
# attached to the verify-browser Chrome on 127.0.0.1:9222, once.
# Bug caught: the server launches its own Chrome without the Okta session, or a re-run adds it again.
def test_install_devbox_registers_the_chrome_devtools_mcp_server(devbox: Devbox):
    devbox.marker.mkdir()

    first = devbox.install()
    second = devbox.install()

    assert first.returncode == second.returncode == 0, first.stdout + first.stderr + second.stdout + second.stderr
    for tool in ("claude", "codex"):
        server = devbox.mcp_server(tool)
        command = server["command"]
        assert any(part.startswith("chrome-devtools-mcp") for part in command), server
        assert command[command.index("--browserUrl") + 1] == "http://127.0.0.1:9222", server
        assert devbox.mcp_adds(tool) == ["chrome-devtools"], f"{tool}: a re-run should not add the server again"
    assert devbox.mcp_server("claude")["scope"] == "user", "the server should serve every project on the devbox"


# Protects: each verify-browser window restarts its process 5 seconds after it exits, and logs one line per restart.
# Bug caught: a crashed Xvfb, Chrome, VNC, noVNC, or keep-alive stays dead, because start does nothing while the
# tmux session exists.
@pytest.mark.parametrize("window", ["xvfb", "chrome", "vnc", "novnc"])
def test_verify_browser_window_restarts_its_process_after_a_pause(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path, window: str
):
    install_fake_browser(home, fake_exe)
    started = 'echo started >>"$HOME/process.log"\nexit 3\n'
    for tool in ("Xvfb", "x11vnc", "websockify"):
        fake_exe(tool, started)
    (home / ".local/share/verify-browser/current/chrome").write_text("#!/bin/bash\n" + started)
    display_socket = isolated_env.root / "X99"
    display_socket.touch()
    # The second restart pause ends the test.
    fake_exe(
        "sleep",
        'echo "$1" >>"$HOME/sleep.log"\n[ "$(wc -l <"$HOME/sleep.log")" -ge 2 ] && kill "$PPID"\nexit 0\n',
    )

    run_tool([VERIFY_BROWSER, "run", window], cwd=isolated_env.root, VERIFY_BROWSER_DISPLAY_SOCKET=str(display_socket))

    assert lines(home / "process.log") == ["started", "started"], "the process should run again after it exits"
    assert lines(home / "sleep.log") == ["5", "5"], "the window should pause 5 seconds before each restart"
    restarts = lines(home / f".local/state/verify-browser/{window}.log")
    assert len(restarts) == 2 and all("3" in line for line in restarts), restarts


# Protects: the keep-alive window also restarts when the keep-alive loop itself ends.
# Bug caught: the keepalive window runs the loop once, so a crash of the loop stops all later Okta checks.
def test_verify_browser_keepalive_window_restarts(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    # A sleep of 3600 fails, which ends one keep-alive loop. The second pause of 5 seconds ends the test.
    fake_exe(
        "sleep",
        'echo "$1" >>"$HOME/sleep.log"\n'
        '[ "$1" = 5 ] && [ "$(grep -c "^5$" "$HOME/sleep.log")" -ge 2 ] && kill "$PPID"\n'
        '[ "$1" = 3600 ] && kill "$PPID"\nexit 0\n',
    )

    run_tool(
        [VERIFY_BROWSER, "run", "keepalive"],
        cwd=isolated_env.root,
        VERIFY_BROWSER_PORT=str(free_port()),
        VERIFY_BROWSER_OKTA_URL=EXAMPLE_OKTA,
    )

    assert len(lines(home / ".local/state/verify-browser/keepalive.log")) >= 1, "the restart should be logged"
    assert len(lines(home / ".local/state/verify-browser/okta-session.log")) >= 2, "the keep-alive should run again"


def processes_with_profile(profile: Path) -> list[str]:
    listing = subprocess.run(["ps", "-ww", "-eo", "pid=,command="], capture_output=True, text=True, check=True).stdout
    return [line for line in listing.splitlines() if f"--user-data-dir={profile}" in line.split(" ", 2)[-1].split()]


# Protects: stop ends the restart loop before it stops Chrome, so no Chrome with the profile remains.
# Bug caught: stop kills Chrome first, and the chrome window starts it again 5 seconds later.
def test_verify_browser_stop_leaves_no_chrome_while_the_window_loops(
    isolated_env: IsolatedEnv, fake_exe: FakeExe, run_tool: RunTool, home: Path
):
    fake_exe("tmux", FAKE_TMUX)
    install_fake_browser(home, fake_exe)
    (home / ".local/share/verify-browser/current/chrome").write_text("#!/bin/bash\nsleep 60\n")
    profile = home / ".local/state/verify-browser/profile"
    display_socket = isolated_env.root / "X99"
    display_socket.touch()
    env = {
        **isolated_env.env,
        "VERIFY_BROWSER_DISPLAY_SOCKET": str(display_socket),
        "VERIFY_BROWSER_RESTART_SECONDS": "1",
    }
    script = private_verify_browser(isolated_env.root)
    loop = subprocess.Popen([script, "run", "chrome"], env=env, cwd=isolated_env.root, start_new_session=True)
    try:
        for _ in range(100):
            if processes_with_profile(profile):
                break
            subprocess.run(["/bin/sleep", "0.1"], check=True)
        assert processes_with_profile(profile), "the window should have started Chrome"

        result = run_tool([script, "stop"], cwd=isolated_env.root)
        assert result.returncode == 0, result.stdout + result.stderr
        subprocess.run(["/bin/sleep", "3"], check=True)  # longer than the 1-second restart pause

        assert processes_with_profile(profile) == [], "no loop may start Chrome again after stop"
    finally:
        try:
            os.killpg(loop.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        loop.wait()
