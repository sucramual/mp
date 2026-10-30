"""Black-box tests for install.sh's Codex config, agent prefs, and legacy-layout migration.

The installer runs with HOME set to a temp dir that models a machine still linked to the old repo
layout. The real HOME, ~/bin, and ~/dotfiles are never touched. ~/.codex/config.toml is a real,
machine-owned file that install.sh merges the tracked config/codex/config.toml into.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT, IsolatedEnv

INSTALLER = REPO_ROOT / "install.sh"
CONFIG_SOURCE = REPO_ROOT / "config" / "codex" / "config.toml"
RunTool = Callable[..., subprocess.CompletedProcess[str]]

# Auth and cache state must stay machine-local, so the repo must ignore these paths.
IGNORED_STATE_PATHS = [
    "codex/auth.json",
    "codex/cache/session.json",
    "config/codex/auth.json",
    "config/codex/cache/session.json",
    ".codex/auth.json",
    ".codex/cache/session.json",
]

# Old-layout links (target under HOME -> path under the repo) that install.sh must repoint.
LEGACY_LINKS = {
    ".zshrc": "zshrc",
    ".zprofile": "zprofile",
    ".claude/statusline-command.sh": "statusline-command.sh",
    ".codex/config.toml": "codex/config.toml",
    ".config/ghostty/config": "ghostty/config",
    "bin/mmd-ascii": "bin/mmd-ascii",
    "bin/git-unlock": "bin/git-unlock",
    # Before agents/global.md, both global guidance links pointed at the root AGENTS.md.
    ".claude/CLAUDE.md": "AGENTS.md",
    ".codex/AGENTS.md": "AGENTS.md",
}

# Installed link (under HOME) -> the repo file it must point to after install.
# ~/.codex/config.toml is not here: it becomes a real file (see assert_real_codex_config).
MANAGED_LINKS = {
    ".zshrc": "config/shell/zshrc",
    ".zprofile": "config/shell/zprofile",
    ".claude/statusline-command.sh": "config/claude/statusline-command.sh",
    ".config/ghostty/config": "config/ghostty/config",
    "bin/mmd-ascii": "tools/mmd-ascii/bin/mmd-ascii",
    "bin/git-unlock": "tools/git-unlock/bin/git-unlock",
}

# (key path in config/codex/config.toml, expected value, failure message)
EXPECTED_CONFIG_VALUES: list[tuple[tuple[str, ...], object, str]] = [
    (("mcp_servers", "notion", "url"), "https://mcp.notion.com/mcp", "Notion MCP server should use the hosted url"),
    (("sandbox_mode",), "workspace-write", "Codex should use the workspace-write sandbox mode"),
    (
        ("sandbox_workspace_write", "writable_roots"),
        ["~/Documents/Obsidian/Default"],
        "the sandbox should make only the Obsidian vault writable",
    ),
    (("model",), "gpt-6-sol", "Codex should use the preferred model"),
    (("model_reasoning_effort",), "high", "Codex should use the preferred reasoning effort"),
    (("projects", "/Users/marcus/dotfiles", "trust_level"), "trusted", "the dotfiles project should be trusted"),
    (("desktop", "followUpQueueMode"), "queue", "the Codex app should queue follow-up messages"),
    (("plugins", "browser@openai-bundled", "enabled"), True, "the bundled browser plugin should be enabled"),
]
BARE_TOML_KEY = re.compile(r"[A-Za-z0-9_-]+")

# Words that suggest auth or cache state. Any match in the portable config fails the test.
FORBIDDEN_STATE_PATTERN = re.compile(r"(token|secret|oauth|auth\.json|cache)", re.IGNORECASE)


def installer_env(env: IsolatedEnv) -> dict[str, str]:
    """isolated_env without GIT_CONFIG_GLOBAL, so `git config --global` uses the temp HOME's ~/.gitconfig."""
    return {key: value for key, value in env.env.items() if key != "GIT_CONFIG_GLOBAL"}


def stub_mmd_ascii_install(fake_exe: Callable[..., Path]) -> None:
    """Fake bun, npx, and brew, so install.sh runs no real installs.

    This covers mmd-ascii dependencies, third-party skills, and the `brew bundle` step on the faked Darwin run.
    """
    fake_exe("bun", "exit 0\n")
    fake_exe("npx", "exit 0\n")
    fake_exe("brew", "exit 0\n")
    fake_exe("uname", "echo Darwin\n")


def run_install(isolated_env: IsolatedEnv, run_tool: RunTool, home: Path | None = None) -> str:
    """Run install.sh with HOME set to home (default: the isolated HOME). Returns its stdout."""
    env = installer_env(isolated_env)
    if home is not None:
        env["HOME"] = str(home)
    result = run_tool([INSTALLER], cwd=isolated_env.root, env=env)
    assert result.returncode == 0, f"install.sh should succeed\n{result.stdout}\n{result.stderr}"
    return result.stdout


def config_digest() -> str:
    return hashlib.sha256(CONFIG_SOURCE.read_bytes()).hexdigest()


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def contains(actual: object, expected: object) -> bool:
    """True when every key of expected is in actual with the same value (tables compare recursively)."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in expected.items())
    return type(actual) is type(expected) and actual == expected


def assert_real_codex_config(target: Path) -> dict:
    """The Codex config is a real file (not a symlink) holding every tracked key. Returns it parsed."""
    assert target.is_file() and not target.is_symlink(), f"{target} should be a real machine-owned file"
    data = load_toml(target)
    assert contains(data, load_toml(CONFIG_SOURCE)), f"{target} should hold every tracked key and value"
    return data


def backups(target: Path) -> list[Path]:
    return sorted(target.parent.glob(f"{target.name}.bak*"))


def assert_symlink(target: Path, source: Path, label: str | None = None) -> None:
    name = label or str(target)
    assert target.is_symlink(), f"{name} should be a symlink managed by install.sh"
    assert os.readlink(target) == str(source), f"{name} symlink points to the wrong file"


@pytest.mark.parametrize("path", IGNORED_STATE_PATHS)
def test_repo_ignores_codex_auth_and_cache_state(path: str, run_tool: RunTool):
    result = run_tool(["git", "-C", REPO_ROOT, "check-ignore", "-q", path], cwd=REPO_ROOT)
    assert result.returncode == 0, f"{path} should be ignored so auth/cache state is not committed"


def test_install_repoints_legacy_links_to_the_current_layout(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool, main_checkout: Path
):
    # install.sh runs from a main checkout, because scripts/link_tools.py refuses in a linked worktree.
    root = main_checkout
    home = isolated_env.home
    for target, old_source in LEGACY_LINKS.items():
        link = home / target
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(root / old_source)
    stub_mmd_ascii_install(fake_exe)

    result = run_tool([root / "install.sh"], cwd=isolated_env.root, env=installer_env(isolated_env))
    assert result.returncode == 0, f"install.sh should succeed\n{result.stdout}\n{result.stderr}"

    assert CONFIG_SOURCE.is_file(), "missing portable Codex config at config/codex/config.toml"
    for target, source in MANAGED_LINKS.items():
        assert_symlink(home / target, root / source)
    # The old codex/config.toml link dangles, so the result is just the tracked config.
    assert_real_codex_config(home / ".codex" / "config.toml")
    for agent_target in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md"):
        assert_symlink(agent_target, root / "agents" / "global.md")
    guidance = home / ".agent-guidance"
    assert guidance.is_symlink(), "~/.agent-guidance should be a symlink managed by install.sh"
    assert os.readlink(guidance) == str(root / "agents"), "~/.agent-guidance symlink points to the wrong directory"


def test_legacy_personal_md_stays_a_compatibility_symlink():
    legacy = REPO_ROOT / "agents" / "personal.md"
    assert legacy.is_symlink(), "agents/personal.md should remain as a compatibility symlink"
    assert os.readlink(legacy) == "global.md", "agents/personal.md should point to the global rules, global.md"


def toml_key(path: tuple[str, ...]) -> str:
    """Write a key path the way TOML does, e.g. plugins."browser@openai-bundled".enabled."""
    return ".".join(key if BARE_TOML_KEY.fullmatch(key) else f'"{key}"' for key in path)


def load_portable_config() -> dict[str, Any]:
    return tomllib.loads(CONFIG_SOURCE.read_text())


@pytest.mark.parametrize(
    ("path", "expected", "message"),
    EXPECTED_CONFIG_VALUES,
    ids=[toml_key(path) for path, _, _ in EXPECTED_CONFIG_VALUES],
)
def test_portable_codex_config_has_expected_setting(path: tuple[str, ...], expected: object, message: str):
    value: object = load_portable_config()
    for depth, key in enumerate(path, start=1):
        assert isinstance(value, dict) and key in value, (
            f"config/codex/config.toml has no {toml_key(path[:depth])}: {message}"
        )
        value = value[key]
    assert value == expected and type(value) is type(expected), (
        f"config/codex/config.toml sets {toml_key(path)} = {value!r}, want {expected!r}: {message}"
    )


def test_portable_codex_config_has_no_auth_or_cache_state():
    matches = [
        f"{number}: {text}"
        for number, text in enumerate(CONFIG_SOURCE.read_text().splitlines(), start=1)
        if FORBIDDEN_STATE_PATTERN.search(text)
    ]
    assert not matches, "portable Codex config must not contain auth or cache state\n" + "\n".join(matches)


# --- Codex config: legacy symlinks and the machine-owned local file ------------------

# A local file as the Codex app leaves it: app-only keys plus a stale tracked key (model).
APP_WRITTEN_CONFIG = """\
notify = ["/Applications/Example.app/Contents/MacOS/notifier", "turn-ended"]
model = "other"

[mcp_servers.node_repl]
command = "/Applications/Example.app/node_repl"
startup_timeout_sec = 120

[mcp_servers.node_repl.env]
NODE_REPL_TRUSTED_SERVICES = '{"browser":"/Users/x/.codex/plugins/cache/b/service.mjs","sky":"@oai/sky/service"}'
QUOTED = "say \\"hi\\" \\\\ bye"

[marketplaces.x]
source_type = "local"
source = "/Users/x/.cache/codex-runtimes/x"

[tui.model_availability_nux]
gpt-6-astra = 1
"""
APP_ONLY_KEYS = ("marketplaces", "tui")


def assert_original_callback(merged: dict, original: dict, home: Path) -> None:
    wrapped = merged["notify"]
    assert Path(wrapped[0]).is_absolute(), "the installed helper must use an absolute path"
    assert wrapped[:3] == [str(home / "bin/agent-completion-sound.py"), "--codex", "--forward"]
    assert wrapped[3:] == original["notify"], "the original callback argv must remain exact"


def test_install_converts_a_symlink_to_the_tracked_config(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    before = config_digest()
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.symlink_to(CONFIG_SOURCE)
    stub_mmd_ascii_install(fake_exe)

    output = run_install(isolated_env, run_tool)

    assert_real_codex_config(target)
    assert "Found legacy ~/.codex/config.toml symlink" in output, f"install should report the conversion\n{output}"
    backup, audio_backup = backups(target)
    assert backup.is_file() and not backup.is_symlink(), "the legacy symlink should be backed up as a content copy"
    assert backup.read_bytes() == CONFIG_SOURCE.read_bytes(), "the backup should hold the linked file's contents"
    assert contains(load_toml(audio_backup), load_toml(CONFIG_SOURCE)), "audio migration backs up the merged config"
    assert config_digest() == before, "install must never modify the tracked config/codex/config.toml"


def test_install_keeps_app_values_and_mode_from_a_linked_file(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    before = config_digest()
    linked = isolated_env.root / "linked-config.toml"
    linked.write_text(APP_WRITTEN_CONFIG)
    linked.chmod(0o600)
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.symlink_to(linked)
    stub_mmd_ascii_install(fake_exe)

    run_install(isolated_env, run_tool)

    merged = assert_real_codex_config(target)
    original = tomllib.loads(APP_WRITTEN_CONFIG)
    assert_original_callback(merged, original, isolated_env.home)
    for key in APP_ONLY_KEYS:
        assert merged[key] == original[key], f"install should keep the app-written {key} from the linked file"
    assert linked.read_text() == APP_WRITTEN_CONFIG, "install should not write through a legacy symlink"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600, "the converted file should keep the linked file's mode"
    assert config_digest() == before, "install must never modify the tracked config/codex/config.toml"


def test_install_merges_into_a_local_file_and_then_is_a_no_op(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    before = config_digest()
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text(APP_WRITTEN_CONFIG)
    target.chmod(0o600)
    stub_mmd_ascii_install(fake_exe)

    first = run_install(isolated_env, run_tool)

    merged = assert_real_codex_config(target)
    original = tomllib.loads(APP_WRITTEN_CONFIG)
    assert_original_callback(merged, original, isolated_env.home)
    for key in APP_ONLY_KEYS:
        assert merged[key] == original[key], f"install should keep the app-only {key}"
    assert merged["mcp_servers"]["node_repl"] == original["mcp_servers"]["node_repl"], (
        "install should keep app-written MCP servers value for value, JSON and escaped strings included"
    )
    assert '  Codex config drift: model: "other" -> "gpt-6-sol" (tracked value wins)' in first.splitlines(), (
        f"install should report drift for the overwritten tracked key\n{first}"
    )
    backup, audio_backup = backups(target)
    assert backup.read_text() == APP_WRITTEN_CONFIG, "install should back up the local file before rewriting it"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600, "a rewrite should keep the local file's mode"

    merged_bytes = target.read_bytes()
    second = run_install(isolated_env, run_tool)

    assert "drift" not in second, f"a second install should report no Codex config drift\n{second}"
    assert "  ~/.codex/config.toml already current" in second.splitlines(), (
        f"a second install should leave the Codex config alone\n{second}"
    )
    assert backups(target) == [backup, audio_backup], "a second install should not create another backup"
    assert target.read_bytes() == merged_bytes, "a second install should not rewrite the Codex config"
    assert config_digest() == before, "install must never modify the tracked config/codex/config.toml"


def test_install_corrects_a_tracked_key_with_the_wrong_type(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('[plugins."browser@openai-bundled"]\nenabled = 1\n')
    stub_mmd_ascii_install(fake_exe)

    output = run_install(isolated_env, run_tool)

    assert '  Codex config drift: plugins."browser@openai-bundled".enabled: 1 -> true (tracked value wins)' in (
        output.splitlines()
    ), f"install should report 1 vs true as drift\n{output}"
    assert assert_real_codex_config(target)["plugins"]["browser@openai-bundled"]["enabled"] is True


# --- the private work overlay's config fragments -------------------------------------

WORK_PROJECT = "/work/repo"
WORK_PLUGIN = "work@work-plugins"


def work_overlay(root: Path) -> Path:
    """A fake work overlay with a Codex fragment and a Claude settings fragment, and no install.sh."""
    overlay = root / "work-overlay"
    (overlay / "config" / "codex").mkdir(parents=True)
    (overlay / "config" / "codex" / "config.toml").write_text(f'[projects."{WORK_PROJECT}"]\ntrust_level = "trusted"\n')
    (overlay / "config" / "claude").mkdir(parents=True)
    (overlay / "config" / "claude" / "settings.template.json").write_text(
        json.dumps({"enabledPlugins": {WORK_PLUGIN: True}})
    )
    return overlay


def run_install_with(isolated_env: IsolatedEnv, run_tool: RunTool, overlay: Path) -> str:
    env = installer_env(isolated_env) | {"DOTFILES_WORK_DIR": str(overlay)}
    result = run_tool([INSTALLER], cwd=isolated_env.root, env=env)
    assert result.returncode == 0, f"install.sh should succeed\n{result.stdout}\n{result.stderr}"
    return result.stdout


# Protects: the work keys that left the public files reach a work laptop through the overlay.
# Bug caught: install.sh ignores the overlay, so the work project is no longer trusted in Codex and the work
# plugin is never enabled; or it seeds settings without the public template's plugins.
def test_install_merges_the_work_overlay_fragments(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    stub_mmd_ascii_install(fake_exe)
    overlay = work_overlay(isolated_env.root)

    run_install_with(isolated_env, run_tool, overlay)

    codex = assert_real_codex_config(isolated_env.home / ".codex" / "config.toml")
    assert codex["projects"][WORK_PROJECT] == {"trust_level": "trusted"}, "the overlay's work project is trusted"
    settings = json.loads((isolated_env.home / ".claude" / "settings.json").read_text())
    template = json.loads((REPO_ROOT / "config" / "claude" / "settings.template.json").read_text())
    assert settings["enabledPlugins"] == {**template["enabledPlugins"], WORK_PLUGIN: True}, (
        "the seeded settings should hold the template plugins plus the overlay plugin"
    )

    second = run_install_with(isolated_env, run_tool, overlay)
    assert "  ~/.codex/config.toml already current" in second.splitlines(), second


# Protects: a machine without the overlay gets only the public keys.
# Bug caught: install.sh fails when the overlay is absent, or the public files still hold the work keys.
def test_install_without_a_work_overlay_uses_only_the_public_config(
    isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool
):
    stub_mmd_ascii_install(fake_exe)

    run_install_with(isolated_env, run_tool, isolated_env.root / "no-overlay")

    codex = assert_real_codex_config(isolated_env.home / ".codex" / "config.toml")
    assert codex["projects"], "the public projects should be there"
    assert WORK_PROJECT not in codex["projects"]
    settings = json.loads((isolated_env.home / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"], "the public plugins should be there"
    assert WORK_PLUGIN not in settings["enabledPlugins"]
