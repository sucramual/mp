"""Black-box tests for config/agent-hooks/install_hooks.py: the agent-trace hook and the Claude Code telemetry env.

The guard_irreversible hook has its own tests in test_install_managed_configs.py, test_dotfiles_pr.py, and
test_cloud_bootstrap.py. These tests cover what install_hooks.py adds for agent-trace.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "config" / "agent-hooks" / "install_hooks.py"
TRACE_COMMAND = f"python3 {REPO_ROOT / 'tools' / 'agent-trace' / 'bin' / 'agent-trace'} hook"
TELEMETRY_ENV = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
}


def install(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, paths)], capture_output=True, text=True, check=False)


def post_tool_commands(settings: dict) -> list[tuple[str | None, str]]:
    return [
        (group.get("matcher"), hook["command"])
        for group in settings.get("hooks", {}).get("PostToolUse", [])
        for hook in group["hooks"]
    ]


# Protects: Claude Code and Codex run the agent-trace PR hook after Bash, beside the owner's own PostToolUse hooks.
# Bug caught: install_hooks.py registers only the guard, so no PR create or merge reaches the run trace.
def test_registers_the_trace_hook_once_in_both_files(tmp_path: Path) -> None:
    claude = tmp_path / "settings.json"
    codex = tmp_path / "hooks.json"
    owner = {"matcher": "Edit", "hooks": [{"type": "command", "command": "owner-post-hook"}]}
    claude.write_text(json.dumps({"hooks": {"PostToolUse": [owner]}}))

    first = install(claude, codex)
    second = install(claude, codex)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    for path in (claude, codex):
        commands = post_tool_commands(json.loads(path.read_text()))
        assert commands.count(("Bash", TRACE_COMMAND)) == 1, f"{path.name} should hold the trace hook once: {commands}"
    assert ("Edit", "owner-post-hook") in post_tool_commands(json.loads(claude.read_text())), "owner hook kept"


# Protects: a moved checkout updates the trace hook in place instead of adding a second copy.
# Bug caught: matching the full command, so an old path stays and the hook runs twice, or dangles.
def test_updates_a_moved_trace_hook_in_place(tmp_path: Path) -> None:
    claude = tmp_path / "settings.json"
    old = {"type": "command", "command": "python3 /old/checkout/tools/agent-trace/bin/agent-trace hook"}
    claude.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [old]}]}}))

    result = install(claude)

    assert result.returncode == 0, result.stderr
    assert post_tool_commands(json.loads(claude.read_text())) == [("Bash", TRACE_COMMAND)]


# Protects: Claude Code exports its native spans to agent-trace collect on every machine that syncs dotfiles.
# Bug caught: the env lives only in settings.template.json, which install.sh copies once, so existing machines
# never export traces. The owner's own value must win, so a machine can opt out or point elsewhere.
def test_adds_missing_telemetry_env_to_claude_settings_only(tmp_path: Path) -> None:
    claude = tmp_path / "settings.json"
    codex = tmp_path / "hooks.json"
    claude.write_text(json.dumps({"env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9999", "KEEP": "x"}}))

    result = install(claude, codex)

    assert result.returncode == 0, result.stderr
    env = json.loads(claude.read_text())["env"]
    assert env == {**TELEMETRY_ENV, "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9999", "KEEP": "x"}
    codex_settings = json.loads(codex.read_text())
    assert "hooks" in codex_settings and "env" not in codex_settings, "Codex hooks.json has no env block"


# Protects: a freshly seeded machine and a cloud session get the same telemetry env as a synced machine.
# Bug caught: the template and install_hooks.py drift apart.
def test_settings_template_holds_the_telemetry_env() -> None:
    template = json.loads((REPO_ROOT / "config" / "claude" / "settings.template.json").read_text())

    assert TELEMETRY_ENV.items() <= template["env"].items()
