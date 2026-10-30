"""Black-box tests for config/agent-hooks: the guard_irreversible PreToolUse hook and its installer.

The hook runs as a subprocess with hook JSON on stdin, as Claude Code and Codex run it.
It allows with exit 0 and no output, and blocks with exit 2 and a reason on stderr.
The installer runs on temp settings files; the tests parse the JSON it writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

GUARD = REPO_ROOT / "config/agent-hooks/guard_irreversible.py"
INSTALLER = REPO_ROOT / "config/agent-hooks/install_hooks.py"
SHA = "0123456789abcdef0123456789abcdef01234567"

# Reason fragments. Each names the safe form that the agent must use instead.
PIN_REASON = "--match-head-commit <full 40-character head SHA you reviewed>"
VARIABLE_REASON = "shell variable is not accepted"
ADMIN_REASON = "--admin"
AUTO_REASON = "--auto"
REST_REASON = "-f sha=<full 40-character head SHA you reviewed>"
REST_INPUT_REASON = "pass -f sha=<sha> inline"
GRAPHQL_REASON = 'expectedHeadOid: "<sha>"'
AUTO_MERGE_REASON = "enablePullRequestAutoMerge"
SPACELIFT_REASON = "Spacelift is read-only for agents"
PARSE_REASON = "could not parse its input"


def run_guard(stdin: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD)], input=stdin, cwd=cwd, text=True, capture_output=True, timeout=30
    )


def bash(command: str | list[str], cwd: Path, tool: str = "Bash") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)})


BLOCKED = [
    ("gh pr merge 12 --squash", PIN_REASON),
    ('gh pr merge 12 --squash --match-head-commit "$SHA"', VARIABLE_REASON),
    (f"gh pr merge 12 --squash --admin --match-head-commit {SHA}", ADMIN_REASON),
    (f"gh pr merge 12 --squash --auto --match-head-commit {SHA}", AUTO_REASON),
    ("cd repo && gh pr merge 12", PIN_REASON),
    ("gh -R o/r pr merge 12 --squash", PIN_REASON),
    ("gh --repo o/r pr merge 12 --squash", PIN_REASON),
    ("gh --repo=o/r pr merge 12 --squash", PIN_REASON),
    ("if true; then gh pr merge 12 --squash; fi", PIN_REASON),
    ("if true; then spacectl stack deploy --id x; fi", SPACELIFT_REASON),
    (
        'gh api graphql -f query=\'mutation { mergePullRequest(input: {pullRequestId: "X", expectedHeadOid: null}) '
        "{ clientMutationId } }'",
        GRAPHQL_REASON,
    ),
    ("echo ok\n/usr/local/bin/gh pr merge 12 --squash", PIN_REASON),
    ("gh api -X PUT repos/o/r/pulls/12/merge", REST_REASON),
    ("gh api repos/o/r/pulls/12/merge -f merge_method=squash", REST_REASON),
    ("gh api --method=PUT /repos/o/r/pulls/12/merge --input body.json", REST_INPUT_REASON),
    (
        "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
        GRAPHQL_REASON,
    ),
    (
        "gh api graphql -f query='mutation { enqueuePullRequest(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
        GRAPHQL_REASON,
    ),
    (
        "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"X\"}) { x } }'",
        AUTO_MERGE_REASON,
    ),
    ("gh pr merge 12 'unbalanced", "could not split"),
    ("spacectl stack deploy --id x", SPACELIFT_REASON),
    ("spacectl stack confirm --id x --run y", SPACELIFT_REASON),
    ("spacectl stack discard --id x --run y", SPACELIFT_REASON),
    ("spacectl stack approve --id x --run y", SPACELIFT_REASON),
    ("spacectl stack environment setvar --id x KEY value", SPACELIFT_REASON),
    ("spacectl stack local-preview --id x", SPACELIFT_REASON),
    ("spacectl module create-version --id m", SPACELIFT_REASON),
]


# Protects: each irreversible action is refused with a reason that names the safe form.
# Bug caught: a missed flag, endpoint, or mutation lets an unpinned merge or a Spacelift write through.
@pytest.mark.parametrize(("command", "reason"), BLOCKED)
def test_blocks_irreversible_actions(command: str, reason: str, tmp_path: Path):
    result = run_guard(bash(command, tmp_path), tmp_path)
    assert result.returncode == 2, f"should block: {command}\n{result.stderr}"
    assert reason in result.stderr
    assert result.stdout == ""


def test_blocks_a_graphql_merge_in_an_input_file(tmp_path: Path):
    (tmp_path / "mutation.json").write_text(
        json.dumps({"query": 'mutation { mergePullRequest(input: {pullRequestId: "X"}) { clientMutationId } }'})
    )
    result = run_guard(bash("gh api graphql --input mutation.json", tmp_path), tmp_path)
    assert result.returncode == 2, result.stderr
    assert GRAPHQL_REASON in result.stderr


def test_blocks_a_list_command_from_codex(tmp_path: Path):
    result = run_guard(bash(["gh", "pr", "merge", "12", "--squash"], tmp_path, tool="exec_command"), tmp_path)
    assert result.returncode == 2, result.stderr
    assert PIN_REASON in result.stderr


ALLOWED = [
    f"gh pr merge 12 --squash --match-head-commit {SHA}",
    f"gh pr merge 12 --squash --match-head-commit={SHA}",
    "gh pr merge 12 --disable-auto",
    "gh pr merge --help",
    f"gh api -X PUT repos/o/r/pulls/12/merge -f sha={SHA}",
    "gh api repos/o/r/pulls/12/merge",
    'gh api graphql -f query=\'mutation { mergePullRequest(input: {pullRequestId: "X", '
    f'expectedHeadOid: "{SHA}"}}) {{ clientMutationId }} }}\'',
    'gh api graphql -f query=\'mutation { enqueuePullRequest(input: {pullRequestId: "X", '
    f'expectedHeadOid: "{SHA}"}}) {{ clientMutationId }} }}\'',
    "gh pr view 12",
    "gh pr checks 12",
    "spacectl stack list",
    "spacectl stack show --id x",
    "spacectl stack logs --id x --run y",
    "spacectl stack deploy --help",
    "spacectl whoami",
    "ls -la",
    "grep -rn mergePullRequest src/",
]


# Protects: everyday read commands and pinned merges run without a prompt.
# Bug caught: an over-broad match that blocks reads, so agents learn to work around the hook.
@pytest.mark.parametrize("command", ALLOWED)
def test_allows_reads_and_pinned_merges(command: str, tmp_path: Path):
    result = run_guard(bash(command, tmp_path), tmp_path)
    assert result.returncode == 0, f"should allow: {command}\n{result.stderr}"
    assert result.stderr == ""
    assert result.stdout == ""


def test_allows_other_tools(tmp_path: Path):
    stdin = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x", "new_string": "gh pr merge 1"}})
    result = run_guard(stdin, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# Protects: the hook fails closed. Bug caught: a crash on bad input exits 1, which both agents treat as "allow".
@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        "",
        "[]",
        json.dumps({"tool_name": "Bash", "tool_input": {"command": 12}}),
        json.dumps({"tool_name": "Bash", "tool_input": {"command": ["gh", 1]}}),
    ],
)
def test_fails_closed_on_bad_input(stdin: str, tmp_path: Path):
    result = run_guard(stdin, tmp_path)
    assert result.returncode == 2, result.stderr
    assert PARSE_REASON in result.stderr


# --- installer ---------------------------------------------------------------------------------------------------


def install(*targets: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), *map(str, targets)], text=True, capture_output=True, timeout=30
    )


def guard_hooks(settings: dict) -> list[dict]:
    """Every hook entry in PreToolUse whose command runs guard_irreversible.py."""
    return [
        hook
        for group in settings["hooks"]["PreToolUse"]
        for hook in group["hooks"]
        if hook.get("command", "").endswith("guard_irreversible.py")
    ]


def guard_groups(settings: dict) -> list[dict]:
    guards = guard_hooks(settings)
    return [group for group in settings["hooks"]["PreToolUse"] if any(hook in guards for hook in group["hooks"])]


def test_installer_creates_a_missing_file(tmp_path: Path):
    target = tmp_path / "new" / "hooks.json"
    result = install(target)
    assert result.returncode == 0, result.stderr
    settings = json.loads(target.read_text())
    groups = guard_groups(settings)
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Bash"
    assert groups[0]["hooks"] == [{"type": "command", "command": f"python3 {GUARD}", "timeout": 10}]


def test_installer_keeps_other_keys_and_hooks_and_is_idempotent(tmp_path: Path):
    target = tmp_path / "settings.json"
    other_pre = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/other-guard.sh"}]}
    stop = {"hooks": [{"type": "command", "command": "echo stop"}]}
    target.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [other_pre], "Stop": [stop]}}))

    first = install(target)
    after_first = target.read_bytes()
    second = install(target)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    settings = json.loads(after_first)
    assert settings["model"] == "opus"
    assert settings["hooks"]["Stop"] == [stop]
    assert settings["hooks"]["PreToolUse"][0] == other_pre
    assert len(guard_hooks(settings)) == 1
    assert target.read_bytes() == after_first, "a second run should leave the file byte-identical"


def test_installer_updates_an_old_entry_in_place(tmp_path: Path):
    target = tmp_path / "settings.json"
    old = {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 /old/path/guard_irreversible.py"}]}
    target.write_text(json.dumps({"hooks": {"PreToolUse": [old]}}))

    result = install(target)

    assert result.returncode == 0, result.stderr
    settings = json.loads(target.read_text())
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert guard_hooks(settings) == [{"type": "command", "command": f"python3 {GUARD}", "timeout": 10}]


def test_installer_refuses_a_file_that_is_not_an_object(tmp_path: Path):
    target = tmp_path / "settings.json"
    target.write_text("[1, 2]\n")
    before = target.read_bytes()

    result = install(target)

    assert result.returncode == 1
    assert "not a JSON object" in result.stderr
    assert target.read_bytes() == before


# Protects: the command the installer registers really runs the hook.
# Bug caught: a quoting or path error in the registered command, which both agents report as a hook error.
def test_the_registered_command_blocks_an_unpinned_merge(tmp_path: Path):
    target = tmp_path / "settings.json"
    assert install(target).returncode == 0
    command = guard_hooks(json.loads(target.read_text()))[0]["command"]

    result = subprocess.run(
        ["bash", "-c", command], input=bash("gh pr merge 12", tmp_path), text=True, capture_output=True, timeout=30
    )

    assert result.returncode == 2, result.stderr
    assert PIN_REASON in result.stderr
