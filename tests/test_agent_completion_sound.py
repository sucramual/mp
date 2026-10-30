"""Exercise completion audio and config installation with isolated files and fake commands."""

from __future__ import annotations

import json
import shlex
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

RUNTIME = REPO_ROOT / "tools/agent-completion-sound/bin/agent-completion-sound.py"
INSTALLER = REPO_ROOT / "tools/agent-completion-sound/install.py"


# install.sh takes about 2 s alone but over 20 s when parallel test runs load the machine.
# Its runs get the same hang limit as conftest's run_tool, so the limit catches a hang and not a busy machine.
INSTALL_SH_TIMEOUT = 120


def run(args: list[str], env: IsolatedEnv, payload: str = "", timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, env=env.env, input=payload, text=True, capture_output=True, timeout=timeout)


def install(env: IsolatedEnv) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(INSTALLER)], env)


def configs(env: IsolatedEnv, codex: str = "", claude: dict | None = None) -> tuple[Path, Path]:
    c = env.home / ".codex/config.toml"
    h = env.home / ".claude/settings.json"
    c.parent.mkdir(exist_ok=True)
    h.parent.mkdir(exist_ok=True)
    c.write_text(codex)
    h.write_text(json.dumps(claude or {}))
    c.chmod(0o600)
    h.chmod(0o600)
    return c, h


def notify(path: Path) -> list[str]:
    return tomllib.loads(path.read_text())["notify"]


def stop(path: Path) -> list[dict]:
    return json.loads(path.read_text())["hooks"]["Stop"]


def test_fresh_install_and_repeat_are_safe(isolated_env: IsolatedEnv):
    env = isolated_env
    first = install(env)
    assert first.returncode == 0, first.stderr
    c, h = env.home / ".codex/config.toml", env.home / ".claude/settings.json"
    expected = [str(env.home / "bin/agent-completion-sound.py")]
    assert notify(c) == [*expected, "--codex"]
    assert stop(h) == [{"hooks": [{"type": "command", "command": shlex.join([*expected, "--claude"]), "async": True}]}]
    before = (c.read_bytes(), h.read_bytes(), c.stat().st_mtime_ns, h.stat().st_mtime_ns)
    assert install(env).returncode == 0
    assert before == (c.read_bytes(), h.read_bytes(), c.stat().st_mtime_ns, h.stat().st_mtime_ns)
    assert not list(env.home.rglob("*.bak*"))


def test_preserves_unrelated_toml_and_claude_fields(isolated_env: IsolatedEnv):
    callback = ["/path with spaces/callback", "arg spaces", '"quotes"', "$(touch nope)"]
    text = f'# local comment\nnotify = {json.dumps(callback)} # callback\nmodel = "local"\n\n[custom]\nx = 1\n'
    other = {"type": "command", "command": "echo another", "timeout": 7}
    group = {"matcher": "", "hooks": [other], "custom": True}
    claude = {"permissions": {"allow": ["Read"]}, "hooks": {"Stop": [group], "PreToolUse": [group]}}
    c, h = configs(isolated_env, text, claude)
    original_h = h.read_bytes()
    assert install(isolated_env).returncode == 0
    assert notify(c)[2:] == ["--forward", *callback]
    assert c.read_text().split("model =", 1)[1] == text.split("model =", 1)[1]
    assert c.read_text().startswith("# local comment\n")
    new = json.loads(h.read_text())
    assert new["permissions"] == claude["permissions"]
    assert new["hooks"]["PreToolUse"] == [group]
    assert stop(h)[0] == group
    assert c.with_suffix(".toml.bak").read_text() == text
    assert h.with_suffix(".json.bak").read_bytes() == original_h
    assert stat.S_IMODE(c.stat().st_mode) == stat.S_IMODE(h.stat().st_mode) == 0o600
    before = c.read_bytes(), h.read_bytes()
    assert install(isolated_env).returncode == 0
    assert before == (c.read_bytes(), h.read_bytes())
    assert len(list(isolated_env.home.rglob("*.bak*"))) == 2


@pytest.mark.parametrize("async_value", [None, False, True], ids=["missing", "false", "true"])
def test_migrates_only_exact_owned_wrappers_and_preserves_hook_metadata(
    isolated_env: IsolatedEnv, async_value: bool | None
):
    env = isolated_env
    old = str(env.home / ".local/bin/agent-completion-sound.py")
    new = str(env.home / "bin/agent-completion-sound.py")
    callback = ["/existing/callback", "arg"]
    nested = [sys.executable, old, "--codex", "--forward", sys.executable, new, "--codex", "--forward", *callback]
    owned = {
        "type": "command",
        "command": shlex.join([sys.executable, old, "--claude"]),
        "timeout": 9,
        "statusMessage": "Keep completion status",
    }
    if async_value is not None:
        owned["async"] = async_value
    unknown = {"type": "command", "command": "python /other/agent-completion-sound.py --claude", "async": False}
    group = {"matcher": "*", "custom": "keep metadata", "hooks": [owned, unknown]}
    c, h = configs(env, f"notify = {json.dumps(nested)}\n", {"hooks": {"Stop": [group], "PreToolUse": [group]}})
    assert install(env).returncode == 0
    assert notify(c)[3:] == callback
    expected = {**owned, "command": shlex.join([new, "--claude"]), "async": True}
    assert stop(h) == [{**group, "hooks": [expected, unknown]}]
    assert json.loads(h.read_text())["hooks"]["PreToolUse"] == [group]
    before = (c.read_bytes(), h.read_bytes(), c.stat().st_mtime_ns, h.stat().st_mtime_ns)
    assert install(env).returncode == 0
    assert before == (c.read_bytes(), h.read_bytes(), c.stat().st_mtime_ns, h.stat().st_mtime_ns)
    assert len(list(env.home.rglob("*.bak*"))) == 2


@pytest.mark.parametrize(
    "value", ['"notify" = [\n "callback", # keep arg\n "with spaces",\n]\n', "notify = ['callback']\n"]
)
def test_accepts_toml_notify_forms(isolated_env: IsolatedEnv, value: str):
    c, _ = configs(isolated_env, value + "[table]\nnotify = ['nested']\n")
    before = tomllib.loads(c.read_text())
    assert install(isolated_env).returncode == 0
    assert notify(c)[3:] == before["notify"]
    assert tomllib.loads(c.read_text())["table"] == before["table"]


def test_invalid_config_leaves_both_files_untouched(isolated_env: IsolatedEnv):
    c, h = configs(isolated_env, 'notify = "not an argv list"\n')
    before = c.read_bytes(), h.read_bytes()
    assert install(isolated_env).returncode != 0
    assert before == (c.read_bytes(), h.read_bytes())
    assert not list(isolated_env.home.rglob("*.bak*"))


def test_duplicate_owned_hooks_and_unknown_codex_callback(isolated_env: IsolatedEnv):
    helper = str(isolated_env.home / "bin/agent-completion-sound.py")
    hook = {"type": "command", "command": shlex.join([sys.executable, helper, "--claude"])}
    unrelated = {"type": "command", "command": "echo preserved"}
    callback = ["/other/agent-completion-sound.py", "--codex", "--forward", "original"]
    c, h = configs(
        isolated_env,
        f"notify = {json.dumps(callback)}\n",
        {"hooks": {"Stop": [{"hooks": [hook, hook, unrelated]}]}},
    )
    assert install(isolated_env).returncode == 0
    assert notify(c)[3:] == callback
    assert stop(h) == [{"hooks": [{**hook, "command": shlex.join([helper, "--claude"]), "async": True}, unrelated]}]


def test_installed_commands_work_with_home_spaces(isolated_env: IsolatedEnv):
    env = isolated_env
    env.home = env.root / "home with spaces"
    env.home.mkdir()
    env.env["HOME"] = str(env.home)
    helper = env.home / "bin/agent-completion-sound.py"
    helper.parent.mkdir()
    helper.symlink_to(RUNTIME)
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').touch()\n")
    assert install(env).returncode == 0
    c, h = env.home / ".codex/config.toml", env.home / ".claude/settings.json"
    assert run([*notify(c), '{"type":"agent-turn-complete"}'], env).returncode == 0
    assert run(shlex.split(stop(h)[0]["hooks"][0]["command"]), env, '{"hook_event_name":"Stop"}').returncode == 0
    assert (env.home / "played").exists()


def test_installed_commands_survive_removal_of_installer_python(isolated_env: IsolatedEnv):
    env = isolated_env
    helper = env.home / "bin/agent-completion-sound.py"
    helper.parent.mkdir()
    helper.symlink_to(RUNTIME)
    (env.bin / "python3").symlink_to(sys.executable)
    obsolete_python = env.root / "obsolete/python3.99"
    obsolete_python.parent.mkdir()
    obsolete_python.symlink_to(sys.executable)
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').touch()\n")
    callback = fake_python(
        env.bin / "callback with spaces",
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nprint('callback error', file=sys.stderr)\nsys.exit(7)\n",
    )
    callback_args = [str(callback), "argument with spaces", "$(no shell)", '"quoted"']
    c, h = configs(env, f"notify = {json.dumps(callback_args)}\n")
    launcher = "import runpy, sys; sys.executable = sys.argv[2]; runpy.run_path(sys.argv[1], run_name='__main__')"
    result = run([sys.executable, "-c", launcher, str(INSTALLER), str(obsolete_python)], env)
    assert result.returncode == 0, result.stderr
    obsolete_python.unlink()

    payload = '{"type":"agent-turn-complete","text":"payload with spaces"}'
    result = run([*notify(c), payload], env)
    assert result.returncode == 7
    assert json.loads(result.stdout) == [*callback_args[1:], payload]
    assert result.stderr == "callback error\n"
    assert (env.home / "played").exists()
    (env.home / "played").unlink()
    result = run(shlex.split(stop(h)[0]["hooks"][0]["command"]), env, '{"hook_event_name":"Stop"}')
    assert result.returncode == 0
    assert not result.stdout and not result.stderr
    assert (env.home / "played").exists()


def test_configs_do_not_write_through_symlinks(isolated_env: IsolatedEnv):
    c, h = configs(isolated_env)
    for path in (c, h):
        source = isolated_env.root / path.name
        path.rename(source)
        path.symlink_to(source)
    assert install(isolated_env).returncode == 0
    assert not c.is_symlink() and not h.is_symlink()
    assert (isolated_env.root / "config.toml").read_text() == ""
    assert (isolated_env.root / "settings.json").read_text() == "{}"


def test_app_edit_before_replace_is_preserved(isolated_env: IsolatedEnv):
    c, h = configs(isolated_env, 'notify = ["callback"]\n')
    original_h = h.read_bytes()
    launcher = """
import os, runpy, sys
from pathlib import Path
target = Path(sys.argv[2])
chmod = os.chmod
def edit_during_staging(path, mode, **kwargs):
    chmod(path, mode, **kwargs)
    if Path(path).name.startswith('.config.toml.'):
        target.write_text('notify = ["app changed callback"]\\n')
os.chmod = edit_during_staging
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    result = run([sys.executable, "-c", launcher, str(INSTALLER), str(c)], isolated_env)
    assert result.returncode != 0
    assert "changed during install" in result.stderr
    assert c.read_text() == 'notify = ["app changed callback"]\n'
    assert h.read_bytes() == original_h
    assert not list(c.parent.glob(".config.toml.*"))


def fake_python(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path


def test_controls_default_persist_and_are_idempotent(isolated_env: IsolatedEnv):
    env = isolated_env
    env.env["XDG_CONFIG_HOME"] = str(env.root / "other config")
    marker = env.home / ".config/agent-completion-sound/disabled"
    for command, expected in [("status", "on"), ("off", "off"), ("off", "off"), ("status", "off")]:
        result = run([sys.executable, str(RUNTIME), command], env)
        assert (result.returncode, result.stdout, result.stderr) == (0, expected + "\n", "")
    assert marker.is_file()
    for command in ["on", "on", "status"]:
        result = run([sys.executable, str(RUNTIME), command], env)
        assert (result.returncode, result.stdout, result.stderr) == (0, "on\n", "")
    assert not marker.exists()
    assert not Path(env.env["XDG_CONFIG_HOME"]).exists()


def test_shared_controls_mute_and_restore_both_adapters(isolated_env: IsolatedEnv):
    env = isolated_env
    c, h = configs(env, 'notify = ["untouched"]\n', {"hooks": {"Stop": [{"hooks": []}]}})
    original_configs = c.read_bytes(), h.read_bytes()
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').touch()\n")
    callback = fake_python(
        env.bin / "callback with spaces",
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nprint('callback error', file=sys.stderr)\nsys.exit(7)\n",
    )
    args = ["argument with spaces", "$(no shell)", '"quoted"', '{"type":"agent-turn-complete"}']
    for command, played in [("off", False), ("on", True)]:
        assert run([sys.executable, str(RUNTIME), command], env).returncode == 0
        env.env["XDG_CONFIG_HOME"] = str(env.root / command)
        result = run([sys.executable, str(RUNTIME), "--codex", "--forward", str(callback), *args], env)
        assert result.returncode == 7
        assert json.loads(result.stdout) == args
        assert result.stderr == "callback error\n"
        assert (env.home / "played").exists() == played
        (env.home / "played").unlink(missing_ok=True)
        result = run([sys.executable, str(RUNTIME), "--claude"], env, '{"hook_event_name":"Stop"}')
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert (env.home / "played").exists() == played
        (env.home / "played").unlink(missing_ok=True)
        for mode, payload in [("--codex", '{"type":"other"}'), ("--claude", '{"hook_event_name":"SubagentStop"}')]:
            invocation = [sys.executable, str(RUNTIME), mode, *([payload] if mode == "--codex" else [])]
            result = run(invocation, env, payload if mode == "--claude" else "")
            assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
            assert not (env.home / "played").exists()
    assert (c.read_bytes(), h.read_bytes()) == original_configs


@pytest.mark.parametrize("args", [["off", "extra"], ["invalid"]])
def test_invalid_control_arguments_report_usage(isolated_env: IsolatedEnv, args: list[str]):
    result = run([sys.executable, str(RUNTIME), *args], isolated_env)
    assert result.returncode != 0
    assert not result.stdout
    assert "Usage: acs" in result.stderr


def test_control_help_is_concise(isolated_env: IsolatedEnv):
    result = run([sys.executable, str(RUNTIME), "--help"], isolated_env)
    assert result.returncode == 0
    assert "Usage: acs" in result.stdout
    assert "on|off|status" in result.stdout
    assert not result.stderr


@pytest.mark.parametrize("command", ["on", "off", "status"])
def test_control_io_errors_are_reported(isolated_env: IsolatedEnv, command: str):
    config = isolated_env.home / ".config"
    config.mkdir()
    (config / "agent-completion-sound").write_text("blocked parent directory")
    result = run([sys.executable, str(RUNTIME), command], isolated_env)
    assert result.returncode != 0
    assert not result.stdout
    assert result.stderr.startswith("acs:")
    assert "agent-completion-sound" in result.stderr


@pytest.mark.parametrize("mode", ["--codex", "--claude"])
def test_hook_state_io_errors_are_quiet_and_fail_open(isolated_env: IsolatedEnv, mode: str):
    env = isolated_env
    config = env.home / ".config"
    config.mkdir()
    (config / "agent-completion-sound").write_text("blocked parent directory")
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').touch()\n")
    callback = fake_python(env.bin / "callback", "print('callback still ran')\nraise SystemExit(7)\n")
    invocation = [sys.executable, str(RUNTIME), mode]
    if mode == "--codex":
        invocation += ["--forward", str(callback), '{"type":"agent-turn-complete"}']
    result = run(invocation, env, '{"hook_event_name":"Stop"}' if mode == "--claude" else "")
    assert (result.returncode, result.stdout) == ((7, "callback still ran\n") if mode == "--codex" else (0, ""))
    assert not result.stderr
    assert (env.home / "played").exists()


@pytest.mark.parametrize(
    "payload", ['{"type":"agent-turn-complete","text":"a \\"quote\\""}', '{"type":"other"}', "bad json"]
)
def test_codex_preserves_callback_argv_output_status(isolated_env: IsolatedEnv, payload: str):
    env = isolated_env
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').write_text('yes')\n")
    callback = fake_python(
        env.bin / "callback with spaces",
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nprint('err', file=sys.stderr)\nsys.exit(7)\n",
    )
    args = ["spaces", "$(no shell)", '"quoted"', payload]
    result = run([sys.executable, str(RUNTIME), "--codex", "--forward", str(callback), *args], env)
    assert result.returncode == 7
    assert json.loads(result.stdout) == args
    assert result.stderr == "err\n"
    assert (env.home / "played").exists() == (
        json.loads(payload).get("type") == "agent-turn-complete" if payload != "bad json" else False
    )


@pytest.mark.parametrize(
    ("mode", "payload", "played"),
    [
        ("--claude", '{"hook_event_name":"Stop"}', True),
        ("--claude", '{"hook_event_name":"PreToolUse"}', False),
        ("--claude", "[]", False),
        ("--claude", "bad", False),
        ("--codex", '{"type":"agent-turn-complete"}', True),
        ("--codex", '{"type":"other"}', False),
    ],
)
def test_sound_only_and_event_filtering(isolated_env: IsolatedEnv, mode: str, payload: str, played: bool):
    env = isolated_env
    fake_python(env.bin / "afplay", "from pathlib import Path\nPath.home().joinpath('played').write_text('yes')\n")
    args = [sys.executable, str(RUNTIME), mode]
    if mode == "--codex":
        args.append(payload)
    result = run(args, env, payload if mode == "--claude" else "")
    assert result.returncode == 0
    assert not result.stdout and not result.stderr
    assert (env.home / "played").exists() == played


@pytest.mark.parametrize("failure", ["audio", "callback"])
def test_failures_are_independent(isolated_env: IsolatedEnv, failure: str):
    env = isolated_env
    fake_python(
        env.bin / "afplay",
        "from pathlib import Path\nPath.home().joinpath('played').write_text('yes')\nraise SystemExit(1)\n",
    )
    callback = (
        fake_python(env.bin / "callback", "print('callback still ran')\n")
        if failure == "audio"
        else env.bin / "missing"
    )
    result = run(
        [sys.executable, str(RUNTIME), "--codex", "--forward", str(callback), '{"type":"agent-turn-complete"}'], env
    )
    assert result.returncode == (0 if failure == "audio" else 127)
    assert (env.home / "played").exists()
    if failure == "audio":
        assert result.stdout == "callback still ran\n"


def test_install_sh_configures_mac_only(isolated_env: IsolatedEnv, main_checkout: Path):
    env = isolated_env
    fake_python(env.bin / "bun", "")
    fake_python(env.bin / "npx", "")  # no real third-party skills install
    fake_python(env.bin / "brew", "")
    fake_python(env.bin / "uname", "print('Darwin')\n")
    # install.sh runs from a main checkout, because scripts/link_tools.py refuses in a linked worktree.
    result = run([str(main_checkout / "install.sh")], env, timeout=INSTALL_SH_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert notify(env.home / ".codex/config.toml")[1] == "--codex"
    assert stop(env.home / ".claude/settings.json")
    assert (env.home / "bin/agent-completion-sound.py").is_symlink()
    command = env.home / "bin/acs"
    assert command.is_symlink()
    result = run([str(command), "status"], env)
    assert (result.returncode, result.stdout, result.stderr) == (0, "on\n", "")


def test_install_sh_skips_audio_on_linux(isolated_env: IsolatedEnv):
    env = isolated_env
    fake_python(env.bin / "bun", "")
    fake_python(env.bin / "npx", "")  # no real third-party skills install
    fake_python(env.bin / "brew", "")
    fake_python(env.bin / "uname", "print('Linux')\n")
    result = run([str(REPO_ROOT / "install.sh")], env, timeout=INSTALL_SH_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert "notify" not in tomllib.loads((env.home / ".codex/config.toml").read_text())
    settings = env.home / ".claude/settings.json"
    hooks = json.loads(settings.read_text()).get("hooks", {}) if settings.exists() else {}
    commands = [hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]]
    assert not any("agent-completion-sound" in command for command in commands), commands
