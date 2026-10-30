"""Tests for how dotfiles wires agent-trace into Codex and launchd.

The agent-trace tool has its own tests in test_agent_trace_*.py. install_hooks.py has test_install_hooks.py.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
import tomllib
from pathlib import Path

from conftest import REPO_ROOT

CODEX_BASE = REPO_ROOT / "config" / "codex" / "config.toml"
MERGE_SCRIPT = REPO_ROOT / "config" / "codex" / "merge_config.py"
COLLECT_TEMPLATE = REPO_ROOT / "config" / "launchd" / "com.sucramual.agent-trace-collect.plist.template"
EXPECTED_OTEL = {
    "trace_exporter": {"otlp-http": {"endpoint": "http://127.0.0.1:4318/v1/traces", "protocol": "json"}},
    "exporter": {"otlp-http": {"endpoint": "http://127.0.0.1:4318/v1/logs", "protocol": "json"}},
}


# Protects: Codex exports its traces and tool-result events to agent-trace collect on a synced machine.
# Bug caught: the [otel] table is missing, or merge_config.py cannot write its nested tables with a dashed key
# (otlp-http), so ~/.codex/config.toml ends up without the exporter or fails to parse.
def test_codex_base_exports_otel_to_collect_after_the_merge(tmp_path: Path) -> None:
    assert tomllib.loads(CODEX_BASE.read_text())["otel"] == EXPECTED_OTEL
    local = tmp_path / "config.toml"
    local.write_text('model = "local"\n')

    result = subprocess.run(
        [sys.executable, str(MERGE_SCRIPT), str(CODEX_BASE), str(local)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert tomllib.loads(local.read_text())["otel"] == EXPECTED_OTEL


# Protects: launchd keeps one agent-trace collect running on the Mac and restarts it when it exits.
# Bug caught: a plist that runs the wrong file or exits for good after one crash, so native spans are lost.
def test_collect_plist_template_keeps_collect_running() -> None:
    job = plistlib.loads(COLLECT_TEMPLATE.read_bytes())

    assert job["Label"] == "com.sucramual.agent-trace-collect"
    assert job["ProgramArguments"][-2:] == ["__HOME__/dotfiles/tools/agent-trace/bin/agent-trace", "collect"]
    assert job["KeepAlive"] is True and job["RunAtLoad"] is True
    assert job["ThrottleInterval"] >= 30, "a collect that cannot bind its port should not restart in a tight loop"
