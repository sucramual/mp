"""Black-box tests for scripts/cloud-bootstrap, which installs Claude Code config into a cloud session.

The script runs with HOME set to a temp dir, from a copy of this working tree.
A fake npx stands in for the `skills` CLI, so no test reaches the network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

RunTool = Callable[..., subprocess.CompletedProcess[str]]
TEMPLATE = json.loads((REPO_ROOT / "config/claude/settings.template.json").read_text())
CLOUD_SETTINGS = REPO_ROOT / "config/claude/settings.cloud.json"
_spec = importlib.util.spec_from_file_location(
    "merge_cloud_settings", REPO_ROOT / "config/claude/merge_cloud_settings.py"
)
assert _spec is not None and _spec.loader is not None
MERGE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MERGE)

# These plugins call a program that a cloud session does not have: the local Codex CLI, or the hallouminate binary.
LOCAL_ONLY_PLUGINS = {"codex@openai-codex", "hallouminate@hallouminate"}

# Fake npx: log each call's arguments as one line in $HOME/npx.log, then exit with $NPX_EXIT (default 0).
FAKE_NPX = """printf '%s\\n' "$*" >>"$HOME/npx.log"
exit "${NPX_EXIT:-0}"
"""

# Fake work overlay install.sh: link work.md into ~/.claude, log $HOME, then exit with $OVERLAY_EXIT (default 0).
FAKE_OVERLAY_INSTALLER = """overlay="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.claude"
ln -sfn "$overlay/work.md" "$HOME/.claude/work.md"
printf '%s\\n' "$HOME" >>"$overlay/runs.log"
exit "${OVERLAY_EXIT:-0}"
"""


def bootstrap(main_checkout: Path, isolated_env: IsolatedEnv, run_tool: RunTool, **extra_env: str):
    # A real cloud session's /home/user/mp-private must not leak into a test.
    extra_env.setdefault("DOTFILES_CLOUD_WORK_DIR", str(isolated_env.root / "no-cloud-overlay"))
    return run_tool([main_checkout / "scripts/cloud-bootstrap"], cwd=isolated_env.root, **extra_env)


def read_settings(home: Path) -> dict:
    return json.loads((home / ".claude/settings.json").read_text())


@pytest.fixture
def fake_npx(fake_exe: Callable[..., Path]) -> Path:
    return fake_exe("npx", FAKE_NPX)


@pytest.fixture
def fake_overlay(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path]) -> Path:
    """A private work overlay repo whose install.sh links work.md and logs each run's HOME."""
    overlay = isolated_env.root / "work-overlay"
    fake_exe("install.sh", FAKE_OVERLAY_INSTALLER, directory=overlay)
    (overlay / "work.md").write_text("Work guidance.\n")
    return overlay


# install.sh needs a full laptop setup, and cloud-bootstrap needs only the fake npx.
INSTALLERS = ["install.sh", "scripts/cloud-bootstrap"]


def run_installer(
    script: str,
    main_checkout: Path,
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    """Run one public installer with the isolated HOME. Fakes keep install.sh away from Homebrew and downloads."""
    fake_exe("brew", "exit 0\n")
    fake_exe("bun", "exit 0\n")
    # install.sh writes ~/.gitconfig, so it gets the temp HOME's global Git config, not the test one.
    env = {key: value for key, value in isolated_env.env.items() if key != "GIT_CONFIG_GLOBAL"}
    extra_env.setdefault("DOTFILES_CLOUD_WORK_DIR", str(isolated_env.root / "no-cloud-overlay"))
    return run_tool([main_checkout / script], cwd=isolated_env.root, env=env, **extra_env)


@pytest.mark.parametrize("script", INSTALLERS)
def test_installer_runs_the_work_overlay_installer_when_present(
    script: str,
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    main_checkout: Path,
    fake_npx: Path,
    fake_overlay: Path,
):
    # Bug caught: the installer no longer calls the overlay, so ~/.claude/work.md is never linked.
    home = isolated_env.home

    result = run_installer(script, main_checkout, isolated_env, fake_exe, run_tool, DOTFILES_WORK_DIR=str(fake_overlay))

    assert result.returncode == 0, result.stderr
    assert (fake_overlay / "runs.log").read_text().splitlines() == [str(home)], "the overlay should run once"
    assert (home / ".claude/work.md").resolve() == fake_overlay / "work.md"
    assert (home / ".claude/CLAUDE.md").resolve() == main_checkout / "agents/global.md"


# Protects: a cloud session gets the overlay's work plugin, with the same portable-key rules as the template.
# Bug caught: cloud-bootstrap ignores the overlay settings fragment, so the work plugin that left the public
# template is never enabled in the cloud; or the fragment's local-only plugin gets through.
def test_cloud_bootstrap_merges_the_overlay_settings_fragment(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path, fake_overlay: Path
):
    fragment = fake_overlay / "config" / "claude" / "settings.template.json"
    fragment.parent.mkdir(parents=True)
    fragment.write_text(json.dumps({"enabledPlugins": {"work@work-plugins": True, "codex@openai-codex": True}}))

    result = bootstrap(main_checkout, isolated_env, run_tool, DOTFILES_WORK_DIR=str(fake_overlay))

    assert result.returncode == 0, result.stderr
    plugins = read_settings(isolated_env.home)["enabledPlugins"]
    assert plugins["work@work-plugins"] is True, "the overlay's work plugin should be enabled"
    assert "codex@openai-codex" not in plugins, "a local-only plugin stays out, from the overlay too"
    portable = {name: on for name, on in TEMPLATE["enabledPlugins"].items() if name not in LOCAL_ONLY_PLUGINS}
    assert portable.items() <= plugins.items(), "the template's portable plugins should still be enabled"


# Protects: a cloud session that selects sucramual/mp-private gets the work guidance, the work settings, and the
# leak-check terms, which the pre-push hook later reads from ~/dotfiles-work in another process.
# Bug caught: cloud-bootstrap looks only at ~/dotfiles-work, so the session's /home/user/mp-private is ignored; or it
# runs that overlay but later steps and the pre-push hook still read the empty ~/dotfiles-work; or it wins over an
# explicit DOTFILES_WORK_DIR or an existing ~/dotfiles-work.
@pytest.mark.parametrize("winner", ["cloud", "env", "home"])
def test_cloud_bootstrap_finds_the_overlay_that_the_session_cloned(
    winner: str,
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    main_checkout: Path,
    fake_npx: Path,
    fake_overlay: Path,
):
    home = isolated_env.home
    cloud_overlay = isolated_env.root / "home-user" / "mp-private"
    fake_exe("install.sh", FAKE_OVERLAY_INSTALLER, directory=cloud_overlay)
    (cloud_overlay / "work.md").write_text("Cloud work guidance.\n")
    fragment = cloud_overlay / "config" / "claude" / "settings.template.json"
    fragment.parent.mkdir(parents=True)
    fragment.write_text(json.dumps({"enabledPlugins": {"work@work-plugins": True}}))
    env = {"DOTFILES_CLOUD_WORK_DIR": str(cloud_overlay)}
    if winner == "env":
        env["DOTFILES_WORK_DIR"] = str(fake_overlay)
    elif winner == "home":
        (home / "dotfiles-work").symlink_to(fake_overlay)

    result = bootstrap(main_checkout, isolated_env, run_tool, **env)

    assert result.returncode == 0, result.stderr
    expected, other = (cloud_overlay, fake_overlay) if winner == "cloud" else (fake_overlay, cloud_overlay)
    assert (expected / "runs.log").read_text().splitlines() == [str(home)], "the chosen overlay should run once"
    assert not (other / "runs.log").exists(), "only one overlay should run"
    assert (home / ".claude/work.md").resolve() == expected / "work.md"
    if winner == "cloud":
        assert (home / "dotfiles-work").resolve() == cloud_overlay, "the default overlay path should lead to it"
        assert read_settings(home)["enabledPlugins"]["work@work-plugins"] is True, "its settings should merge"


@pytest.mark.parametrize("script", INSTALLERS)
@pytest.mark.parametrize("overlay_state", ["missing", "not-executable"])
def test_installer_skips_a_missing_work_overlay_and_continues(
    script: str,
    overlay_state: str,
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    main_checkout: Path,
    fake_npx: Path,
):
    # Bug caught: a machine without the overlay fails the install, or runs a non-executable file.
    home = isolated_env.home
    overlay = isolated_env.root / "absent-overlay"
    if overlay_state == "not-executable":
        overlay.mkdir()
        (overlay / "install.sh").write_text('#!/usr/bin/env bash\ntouch "$HOME/overlay-ran"\n')

    result = run_installer(script, main_checkout, isolated_env, fake_exe, run_tool, DOTFILES_WORK_DIR=str(overlay))

    assert result.returncode == 0, result.stderr
    skip_lines = [line for line in result.stdout.splitlines() if "No work overlay found" in line]
    assert len(skip_lines) == 1 and str(overlay) in skip_lines[0], result.stdout
    assert not (home / "overlay-ran").exists(), "a non-executable overlay installer should not run"
    assert not (home / ".claude/work.md").exists()
    # The rest of the install still ran after the skip.
    assert (home / ".claude/CLAUDE.md").resolve() == main_checkout / "agents/global.md"
    assert (home / ".claude/skills").is_dir()


@pytest.mark.parametrize("script", INSTALLERS)
def test_installer_fails_when_the_work_overlay_installer_fails(
    script: str,
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    main_checkout: Path,
    fake_npx: Path,
    fake_overlay: Path,
):
    # Bug caught: an overlay refusal (for example, a real file at a link target) is hidden behind a success exit.
    result = run_installer(
        script, main_checkout, isolated_env, fake_exe, run_tool, DOTFILES_WORK_DIR=str(fake_overlay), OVERLAY_EXIT="3"
    )

    assert result.returncode != 0, result.stdout
    assert (fake_overlay / "runs.log").read_text().splitlines() == [str(isolated_env.home)]
    lines = result.stdout.splitlines()
    assert lines, "the installer should print its progress"
    assert not [line for line in lines if line.startswith("Done.")], "the installer should stop at the overlay failure"


def test_bootstrap_links_global_guidance_and_skills(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    assert (home / ".claude/CLAUDE.md").resolve() == main_checkout / "agents/global.md"
    assert (home / ".agent-guidance").resolve() == main_checkout / "agents"
    skills = sorted(path.parent.name for path in (main_checkout / "skills").glob("*/SKILL.md"))
    assert skills, "the checkout should hold skills"
    for name in skills:
        assert (home / ".claude/skills" / name).resolve() == main_checkout / "skills" / name


def test_bootstrap_installs_each_third_party_source(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    manifest = (main_checkout / "skills/third-party.txt").read_text().splitlines()
    sources = sorted(line.split()[0] for line in manifest if line.strip() and not line.startswith("#"))

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    calls = (isolated_env.home / "npx.log").read_text().splitlines()
    assert sorted(call.split()[3] for call in calls) == sources


def test_bootstrap_writes_only_portable_settings(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    settings = read_settings(isolated_env.home)
    # This key turns off a permission safety prompt, so it must stay on the laptop.
    assert "skipDangerousModePermissionPrompt" in MERGE.LOCAL_ONLY_KEYS
    for key in MERGE.LOCAL_ONLY_KEYS:
        assert key not in settings, f"{key} is laptop-only and must not reach the cloud"
    for key in set(MERGE.PORTABLE_KEYS) - {"enabledPlugins", "extraKnownMarketplaces"}:
        assert settings[key] == TEMPLATE[key], f"cloud {key} differs from the laptop template"
    assert LOCAL_ONLY_PLUGINS <= set(TEMPLATE["enabledPlugins"]), "the template no longer enables a local-only plugin"
    expected_plugins = {name: on for name, on in TEMPLATE["enabledPlugins"].items() if name not in LOCAL_ONLY_PLUGINS}
    assert settings["enabledPlugins"] == expected_plugins
    # A marketplace stays only when a kept plugin comes from it.
    assert set(settings["extraKnownMarketplaces"]) == {
        name.split("@")[1] for name in expected_plugins if name.split("@")[1] in TEMPLATE["extraKnownMarketplaces"]
    }


def test_bootstrap_keeps_machine_settings_and_existing_guidance(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home
    claude = home / ".claude"
    claude.mkdir()
    machine_hooks = {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "machine-hook"}]}]}
    (claude / "settings.json").write_text(
        json.dumps({"hooks": machine_hooks, "effortLevel": "low", "enabledPlugins": {"machine@market": True}})
    )
    (claude / "CLAUDE.md").write_text("machine guidance\n")

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    settings = read_settings(home)
    assert settings["hooks"]["Stop"] == machine_hooks["Stop"]
    assert settings["effortLevel"] == TEMPLATE["effortLevel"]
    assert settings["enabledPlugins"]["machine@market"] is True
    assert (claude / "CLAUDE.md").resolve() == main_checkout / "agents/global.md"
    assert (claude / "CLAUDE.md.bak").read_text() == "machine guidance\n"


def test_bootstrap_repoints_the_old_root_agents_link(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    # Before agents/global.md, ~/.claude/CLAUDE.md linked to the root AGENTS.md, which now holds dotfiles-only rules.
    home = isolated_env.home
    (home / ".claude").mkdir()
    (home / ".claude/CLAUDE.md").symlink_to(main_checkout / "AGENTS.md")

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    assert os.readlink(home / ".claude/CLAUDE.md") == str(main_checkout / "agents/global.md")
    assert not (home / ".claude/CLAUDE.md.bak").exists(), "a link is replaced, not backed up"


# Protects: a cloud session gets the guard_irreversible hook from its own checkout, beside the machine's hooks.
# Bug caught: cloud-bootstrap skips install_hooks.py, so a cloud agent can merge a PR at an unreviewed head.
def test_bootstrap_registers_the_guard_hook_and_keeps_machine_hooks(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    claude = isolated_env.home / ".claude"
    claude.mkdir()
    machine_pre = {"matcher": "Bash", "hooks": [{"type": "command", "command": "machine-pre-hook"}]}
    (claude / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [machine_pre]}}))

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    groups = read_settings(isolated_env.home)["hooks"]["PreToolUse"]
    expected = f"python3 {main_checkout / 'config/agent-hooks/guard_irreversible.py'}"
    assert machine_pre in groups, "the machine's own PreToolUse hook should stay"
    guard = [group for group in groups if [hook["command"] for hook in group["hooks"]] == [expected]]
    assert len(guard) == 1, f"the guard hook should be registered once: {groups}"
    assert guard[0]["matcher"] == "Bash"
    assert not (isolated_env.home / ".codex").exists(), "the cloud has no Codex"


def test_bootstrap_is_idempotent(isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path):
    home = isolated_env.home
    first = bootstrap(main_checkout, isolated_env, run_tool)
    settings_after_first = (home / ".claude/settings.json").read_text()

    second = bootstrap(main_checkout, isolated_env, run_tool)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (home / ".claude/settings.json").read_text() == settings_after_first
    assert not (home / ".claude/CLAUDE.md.bak").exists(), "a second run must not back up its own link"
    assert os.readlink(home / ".claude/CLAUDE.md") == str(main_checkout / "agents/global.md")


def test_bootstrap_puts_the_tools_in_local_bin(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    assert (home / ".local/bin/auth-helper").resolve() == main_checkout / "tools/auth-helper/bin/auth-helper"
    # rogue-auth, the old name, is an alias in the same bin directory.
    assert (home / ".local/bin/rogue-auth").resolve() == main_checkout / "tools/auth-helper/bin/auth-helper"
    assert not (home / "bin").exists(), "the cloud image has no ~/bin on PATH, so nothing should go there"


def test_bootstrap_does_not_touch_bashrc(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home
    original = b"# machine bashrc\n[ -z \"$PS1\" ] && return\nalias ll='ls -l'"  # no final newline
    (home / ".bashrc").write_bytes(original)
    other = isolated_env.root / "other-home"
    other.mkdir()

    result = bootstrap(main_checkout, isolated_env, run_tool)
    fresh = run_tool([main_checkout / "scripts/cloud-bootstrap"], cwd=isolated_env.root, HOME=str(other))

    assert result.returncode == 0, result.stderr
    assert fresh.returncode == 0, fresh.stderr
    assert (home / ".bashrc").read_bytes() == original
    assert not (other / ".bashrc").exists(), "the bootstrap must not create ~/.bashrc"


def test_failed_tool_linking_warns_and_keeps_the_rest(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home
    # A real file at ~/.local/bin blocks the directory, so link_tools.py cannot link.
    (home / ".local").mkdir()
    (home / ".local/bin").write_text("not a directory\n")

    result = bootstrap(main_checkout, isolated_env, run_tool)

    # A non-zero exit marks the cloud setup script as failed, so a linking failure only warns.
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr and "~/.local/bin" in result.stderr
    assert (home / ".claude/CLAUDE.md").resolve() == main_checkout / "agents/global.md"


def test_failed_third_party_install_warns_and_keeps_the_rest(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    home = isolated_env.home

    result = bootstrap(main_checkout, isolated_env, run_tool, NPX_EXIT="1")

    # A non-zero exit marks the cloud setup script as failed. A network failure here must not cause that.
    assert result.returncode == 0, result.stderr
    assert "third-party skills" in result.stderr
    assert (home / "npx.log").exists(), "the bootstrap should have tried the install"
    assert (home / ".claude/CLAUDE.md").resolve() == main_checkout / "agents/global.md"
    assert "effortLevel" in read_settings(home)


def test_bootstrap_removes_local_only_plugins_that_an_earlier_run_enabled(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    claude = isolated_env.home / ".claude"
    claude.mkdir()
    earlier = {name: True for name in LOCAL_ONLY_PLUGINS} | {"machine@market": True}
    (claude / "settings.json").write_text(json.dumps({"enabledPlugins": earlier}))

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    plugins = read_settings(isolated_env.home)["enabledPlugins"]
    assert plugins["machine@market"] is True, "the merge must keep a plugin that only the machine enables"
    assert not LOCAL_ONLY_PLUGINS & set(plugins), "a re-run must remove local-only plugins that an earlier run enabled"


def test_bootstrap_adds_cloud_allow_rules_and_keeps_machine_permissions(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    claude = isolated_env.home / ".claude"
    claude.mkdir()
    machine = {"allow": ["Bash(machine-tool *)"], "deny": ["Edit(machine/**)"]}
    (claude / "settings.json").write_text(json.dumps({"permissions": machine}))
    rules = json.loads(CLOUD_SETTINGS.read_text())["permissions"]["allow"]

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    permissions = read_settings(isolated_env.home)["permissions"]
    assert permissions["deny"] == machine["deny"]
    assert permissions["allow"][0] == "Bash(machine-tool *)", "the merge must keep a rule that only the machine has"
    assert rules, "the cloud settings should allow at least one tool"
    assert sorted(permissions["allow"][1:]) == sorted(rules)


def test_cloud_allow_rules_name_only_mcp_tools_that_do_not_delete_or_merge():
    # A rule here runs with no prompt in every cloud session, so it must not delete data, merge code, or run a shell.
    rules = json.loads(CLOUD_SETTINGS.read_text())["permissions"]["allow"]
    assert rules, "the cloud settings should allow at least one tool"
    for rule in rules:
        assert rule.startswith("mcp__"), f"{rule} is not an MCP tool rule"
        assert not any(word in rule.lower() for word in ("delete", "trash", "merge")), f"{rule} is destructive"


def test_each_template_key_is_portable_or_local_only():
    # A new laptop key must fail here until someone decides if the cloud gets it.
    portable, local_only = set(MERGE.PORTABLE_KEYS), set(MERGE.LOCAL_ONLY_KEYS)
    assert not portable & local_only, f"keys in both lists: {sorted(portable & local_only)}"
    unclassified = set(TEMPLATE) - portable - local_only
    assert not unclassified, f"add each to PORTABLE_KEYS or LOCAL_ONLY_KEYS: {sorted(unclassified)}"
    stale = (portable | local_only) - set(TEMPLATE)
    assert not stale, f"the template no longer sets: {sorted(stale)}"


def claude_links(home: Path) -> dict[str, Path]:
    """Map each Claude guidance and skill link under home to the path it resolves to."""
    paths = [home / ".agent-guidance", *sorted((home / ".claude").glob("*.md"))]
    paths += sorted((home / ".claude/skills").iterdir()) + sorted((home / ".agents/skills").iterdir())
    return {str(path.relative_to(home)): path.resolve() for path in paths if path.is_symlink()}


def tool_links(directory: Path) -> dict[str, Path]:
    """Map each tool link in directory to the path it resolves to."""
    return {path.name: path.resolve() for path in sorted(directory.iterdir()) if path.is_symlink()}


def test_install_and_cloud_bootstrap_give_claude_the_same_guidance_and_skills(
    isolated_env: IsolatedEnv,
    fake_exe: Callable[..., Path],
    run_tool: RunTool,
    main_checkout: Path,
    fake_npx: Path,
    fake_overlay: Path,
):
    # Fakes keep install.sh away from real Homebrew on macOS and from package downloads.
    fake_exe("brew", "exit 0\n")
    fake_exe("bun", "exit 0\n")
    laptop, cloud = isolated_env.root / "laptop-home", isolated_env.root / "cloud-home"
    laptop.mkdir()
    cloud.mkdir()
    # install.sh writes ~/.gitconfig, so it gets the temp HOME's global Git config, not the test one.
    laptop_env = {key: value for key, value in isolated_env.env.items() if key != "GIT_CONFIG_GLOBAL"}

    overlay = str(fake_overlay)

    installed = run_tool(
        [main_checkout / "install.sh"],
        cwd=isolated_env.root,
        env=laptop_env,
        HOME=str(laptop),
        DOTFILES_WORK_DIR=overlay,
    )
    bootstrapped = run_tool(
        [main_checkout / "scripts/cloud-bootstrap"], cwd=isolated_env.root, HOME=str(cloud), DOTFILES_WORK_DIR=overlay
    )

    assert installed.returncode == 0, installed.stderr
    assert bootstrapped.returncode == 0, bootstrapped.stderr
    laptop_links, cloud_links = claude_links(laptop), claude_links(cloud)
    assert ".claude/CLAUDE.md" in laptop_links, "install.sh should link the global guidance"
    assert ".claude/work.md" in laptop_links, "install.sh should run the work overlay installer"
    assert cloud_links == laptop_links
    laptop_tools, cloud_tools = tool_links(laptop / "bin"), tool_links(cloud / ".local/bin")
    assert "auth-helper" in laptop_tools, "install.sh should link the tools"
    assert cloud_tools == laptop_tools, "the bootstrap should link the same tools into ~/.local/bin"
    laptop_npx = sorted((laptop / "npx.log").read_text().splitlines())
    assert laptop_npx, "install.sh should install the third-party skills"
    assert sorted((cloud / "npx.log").read_text().splitlines()) == laptop_npx


def test_bootstrap_links_the_reviewers_file_and_installs_no_ro(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    # Bug caught: a leftover `uv tool install` of ro, or a lost reviewers link that the ready check reads.
    home = isolated_env.home

    result = bootstrap(main_checkout, isolated_env, run_tool)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "Done. Cloud Claude config installed."
    uv_log = home / "uv.log"
    calls = uv_log.read_text().splitlines() if uv_log.exists() else []
    assert not [call for call in calls if call.startswith("tool ")], f"the bootstrap should install no uv tool: {calls}"
    assert not (home / "ro.log").exists(), "the bootstrap should not run ro"
    link = home / ".config/review-pr/reviewers.json"
    assert link.is_symlink()
    assert link.resolve() == main_checkout / "config/review-pr/reviewers.json"


def test_bootstrap_links_the_reviewers_file_where_review_pr_reads_it_under_xdg(
    isolated_env: IsolatedEnv, run_tool: RunTool, main_checkout: Path, fake_npx: Path
):
    config = isolated_env.root / "xdg-config"

    result = bootstrap(main_checkout, isolated_env, run_tool, XDG_CONFIG_HOME=str(config))

    assert result.returncode == 0, result.stderr
    link = config / "review-pr/reviewers.json"
    assert link.is_symlink(), "review-pr reads $XDG_CONFIG_HOME/review-pr/reviewers.json when it is absolute"
    assert link.resolve() == main_checkout / "config/review-pr/reviewers.json"
