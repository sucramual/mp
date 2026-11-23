"""Black-box tests for config/claude/add_allow_rules.py, which syncs tracked allow rules into the live settings.

install.sh seeds ~/.claude/settings.json once and never overwrites it. These tests protect the step that adds
the tracked rules of config/claude/settings.allow.json on every install and sync, without a reseed.
The install.sh and sync wiring tests are in test_install_managed_configs.py and test_dotfiles_pr.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "config" / "claude" / "add_allow_rules.py"
TRACKED = REPO_ROOT / "config" / "claude" / "settings.allow.json"


def run(rules: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(rules), str(target)], capture_output=True, text=True)


def write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def rules_file(tmp_path: Path, *rules: str) -> Path:
    return write_json(tmp_path / "settings.allow.json", {"permissions": {"allow": list(rules)}})


# Protects: a tracked rule reaches a machine whose settings.json already exists, and the local keys stay.
# Bug caught: a merge that replaces the allow list or the permissions object, which drops the owner's local
# rules (such as "Bash") or a deny list.
def test_adds_rules_and_keeps_local_settings(tmp_path: Path) -> None:
    target = write_json(
        tmp_path / "settings.json",
        {"model": "opus", "permissions": {"allow": ["Bash"], "deny": ["Read(./.env)"]}},
    )
    result = run(rules_file(tmp_path, "mcp__x__save_comment"), target)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text()) == {
        "model": "opus",
        "permissions": {"allow": ["Bash", "mcp__x__save_comment"], "deny": ["Read(./.env)"]},
    }


# Protects: settings without a permissions key get one.
# Bug caught: a KeyError on settings that never had a permissions object, such as a fresh template seed.
def test_creates_the_allow_list_when_missing(tmp_path: Path) -> None:
    target = write_json(tmp_path / "settings.json", {"model": "opus"})
    result = run(rules_file(tmp_path, "mcp__x__save_comment"), target)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text()) == {"model": "opus", "permissions": {"allow": ["mcp__x__save_comment"]}}


# Protects: a sync every 15 minutes leaves an up-to-date file alone.
# Bug caught: a rewrite on every run, or a duplicate rule on each run.
def test_second_run_changes_nothing(tmp_path: Path) -> None:
    target = write_json(tmp_path / "settings.json", {"permissions": {"allow": ["mcp__x__save_comment"]}})
    before = target.read_text()
    mtime = target.stat().st_mtime_ns
    result = run(rules_file(tmp_path, "mcp__x__save_comment"), target)
    assert result.returncode == 0, result.stderr
    assert target.read_text() == before
    assert target.stat().st_mtime_ns == mtime, "an up-to-date file should not be rewritten"


# Protects: install.sh seeds settings.json from the template only when the file is missing.
# Bug caught: the step creates a settings.json that holds only the rules, so the later seed never happens.
def test_missing_target_is_left_missing(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    result = run(rules_file(tmp_path, "mcp__x__save_comment"), target)
    assert result.returncode == 0, result.stderr
    assert not target.exists(), "the step must not create settings.json before install.sh seeds it"


# Protects: a broken settings file is reported, not overwritten.
# Bug caught: the step replaces a file that does not hold a JSON object, which loses the owner's settings.
def test_non_object_target_fails_without_a_write(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text("[]\n")
    result = run(rules_file(tmp_path, "mcp__x__save_comment"), target)
    assert result.returncode == 1
    assert "does not hold a JSON object" in result.stderr
    assert target.read_text() == "[]\n"


# Protects: the tracked file has the shape the script reads, and the real sync adds its rules.
# Bug caught: a settings.allow.json that the script cannot read, so every sync warns and adds nothing.
def test_tracked_rules_apply(tmp_path: Path) -> None:
    rules = json.loads(TRACKED.read_text())["permissions"]["allow"]
    assert rules and all(isinstance(rule, str) and rule for rule in rules), rules
    target = write_json(tmp_path / "settings.json", {})
    result = run(TRACKED, target)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text())["permissions"]["allow"] == rules


# Protects: tracked ask rules reach the live settings, so a command that an allow rule matches still prompts
# when it also matches an ask rule (Claude Code applies ask before allow). Local ask rules stay.
# Bug caught: a sync that reads only "allow", so the guard for a risky flag never reaches a machine and the
# allow rule runs the command with no prompt.
def test_adds_ask_rules_and_keeps_local_ones(tmp_path: Path) -> None:
    target = write_json(tmp_path / "settings.json", {"permissions": {"allow": ["Bash"], "ask": ["Bash(rm *)"]}})
    rules = write_json(
        tmp_path / "settings.allow.json",
        {"permissions": {"allow": ["Bash(kubectl get pods *)"], "ask": ["Bash(kubectl * --kubeconfig *)"]}},
    )
    result = run(rules, target)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text())["permissions"] == {
        "allow": ["Bash", "Bash(kubectl get pods *)"],
        "ask": ["Bash(rm *)", "Bash(kubectl * --kubeconfig *)"],
    }


# Protects: the standing kubectl read rules never run a kubeconfig that a command names. kubectl runs the exec
# credential plugin of a kubeconfig, so a kubeconfig file in a repository could run any command with no prompt.
# Bug caught: a kubectl allow rule shipped without the ask rules that make --kubeconfig and KUBECONFIG prompt.
def test_tracked_kubectl_rules_ask_on_a_named_kubeconfig() -> None:
    permissions = json.loads(TRACKED.read_text())["permissions"]
    kubectl_allow = [rule for rule in permissions["allow"] if rule.startswith("Bash(kubectl ")]
    assert kubectl_allow, "this test guards the tracked kubectl allow rules, so they must exist"
    ask = permissions.get("ask", [])
    for rule in ("Bash(kubectl * --kubeconfig *)", "Bash(kubectl * --kubeconfig=*)", "Bash(KUBECONFIG=*)"):
        assert rule in ask, f"missing ask rule {rule}"
