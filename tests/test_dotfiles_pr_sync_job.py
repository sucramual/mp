"""Black-box tests for tools/dotfiles-pr/sync-job, the script that launchd runs every 15 minutes.

The script runs next to a fake bin/dotfiles-pr, so no real repository moves.
The fake reads its exit status, stdout, and stderr from files that each test step writes.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

SYNC_JOB = REPO_ROOT / "tools/dotfiles-pr/sync-job"

FAKE_DOTFILES_PR = """printf '%s\\n' "$*" >>"$HOME/dotfiles-pr.log"
cat "$HOME/sync.stderr" >&2
cat "$HOME/sync.stdout"
exit "$(cat "$HOME/sync.exit")"
"""


class Job:
    """A copy of sync-job beside a fake dotfiles-pr, with logs in a temp directory."""

    def __init__(self, env: IsolatedEnv, fake_exe: Callable[..., Path]) -> None:
        self.env = env
        tool_dir = env.root / "tools/dotfiles-pr"
        tool_dir.mkdir(parents=True)
        self.script = tool_dir / "sync-job"
        shutil.copy2(SYNC_JOB, self.script)
        fake_exe("dotfiles-pr", FAKE_DOTFILES_PR, directory=tool_dir / "bin")
        fake_exe("osascript", 'printf \'%s\\n\' "${@: -1}" >>"$HOME/notifications.log"\n')
        self.log_dir = env.root / "logs"

    def run(self, exit_code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
        home = self.env.home
        (home / "sync.exit").write_text(f"{exit_code}\n")
        (home / "sync.stdout").write_text(stdout)
        (home / "sync.stderr").write_text(stderr)
        return subprocess.run(
            ["/bin/bash", str(self.script)],
            env={**self.env.env, "DOTFILES_SYNC_LOG_DIR": str(self.log_dir)},
            text=True,
            capture_output=True,
            timeout=60,
        )

    def lines(self, name: str) -> list[str]:
        path = self.log_dir / name if name.startswith("sync") else self.env.home / name
        return path.read_text().splitlines() if path.exists() else []

    def log(self) -> list[str]:
        """sync.log lines without the leading date and time."""
        return [line.split(" ", 2)[2] for line in self.lines("sync.log")]


@pytest.fixture
def job(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path]) -> Job:
    return Job(isolated_env, fake_exe)


REFUSAL = "dotfiles-pr: branch 'claude/x' has an open PR; merge or close it first\n"


def test_repeated_outcomes_log_once_and_failures_notify_once(job: Job):
    ok = "main is at abc1234 (was on main)\n"
    for _ in range(2):
        assert job.run(0, stdout=ok, stderr="+ git fetch origin\n").returncode == 0
    for _ in range(2):
        result = job.run(1, stderr="+ git fetch origin\n" + REFUSAL)
        assert result.returncode == 1, "the job should exit with the sync status, so launchctl shows it"
    assert job.run(0, stdout="main is at def5678 (was on claude/x)\n").returncode == 0

    assert job.lines("dotfiles-pr.log") == ["sync --no-prune"] * 5, "every run should call sync without the prune"
    failed = "FAILED (exit 1): " + REFUSAL.strip()
    assert job.log() == [
        "ok: main is at abc1234 (was on main)",
        failed,
        "ok: main is at def5678 (was on claude/x)",
    ], "the log should get one line for each change of outcome, not one for each run"
    assert job.lines("notifications.log") == [failed], "only the new failure should notify"
    assert job.lines("sync-last-run.log") == ["main is at def5678 (was on claude/x)"], (
        "sync-last-run.log should hold the full output of the last run"
    )


def test_success_keeps_warnings_and_joins_summary_lines(job: Job):
    stdout = "main is at abc1234 (was on main)\nuncommitted edits remain; ship or discard them: a.txt\n"
    warning = "dotfiles-pr: warning: Codex config not merged: python3 is older than 3.11\n"
    assert job.run(0, stdout=stdout, stderr="+ git fetch origin\n" + warning).returncode == 0
    assert job.log() == [
        "ok: main is at abc1234 (was on main); uncommitted edits remain; ship or discard them: a.txt; "
        + warning.strip()
    ]
    assert job.lines("notifications.log") == []


def test_a_different_failure_logs_and_notifies_again(job: Job):
    job.run(1, stderr=REFUSAL)
    job.run(1, stderr="dotfiles-pr: command failed (exit 128): git fetch origin\n")
    assert len(job.log()) == 2
    assert len(job.lines("notifications.log")) == 2
