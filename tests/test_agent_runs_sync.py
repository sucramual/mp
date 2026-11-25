"""Black-box tests for tools/agent-runs-sync, which copies agent run data between the laptop and the devbox.

A fake `ssh` runs the remote command locally with HOME set to a second temp folder, so the real tool and Python
move real files between two homes. The "laptop" is the isolated HOME; the "devbox" is REMOTE_HOME.
A fake `devbox` prints the `devbox status --json` state from $HOME/devbox-state (default STATE_RUNNING).
"""

from __future__ import annotations

import os
import stat
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

TOOL = REPO_ROOT / "tools/agent-runs-sync/bin/agent-runs-sync"

# Skip `-o value` options, take the host, and run the rest as one shell command under the remote HOME.
FAKE_SSH = """while [ "${1:-}" = "-o" ]; do shift 2; done
printf '%s\\n' "$1" >>"$HOME/ssh-hosts.log"
shift
if [ -e "$HOME/ssh-down" ]; then echo "ssh: connect to host: Connection refused" >&2; exit 255; fi
calls=$(wc -l <"$HOME/ssh-hosts.log")
if [ -e "$HOME/ssh-fail-after" ] && [ "$calls" -gt "$(cat "$HOME/ssh-fail-after")" ]; then
  echo "remote: broken pipe" >&2; exit 1
fi
HOME="$REMOTE_HOME" exec bash -c "$*"
"""


FAKE_DEVBOX = """printf '%s\\n' "$*" >>"$HOME/devbox.log"
state=$(cat "$HOME/devbox-state" 2>/dev/null || echo STATE_RUNNING)
printf '{"schema":1,"name":"devbox-marcus","state":"%s"}\\n' "$state"
"""


class Machines:
    def __init__(self, env: IsolatedEnv, fake_exe: Callable[..., Path]) -> None:
        fake_exe("ssh", FAKE_SSH)
        fake_exe("devbox", FAKE_DEVBOX)
        self.laptop = env.home
        self.devbox = env.root / "devbox-home"
        self.devbox.mkdir()
        self.env = {**env.env, "REMOTE_HOME": str(self.devbox)}

    def sync(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(TOOL), "--host", "devbox", "--as", "laptop", *args],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=60,
        )

    @staticmethod
    def write(home: Path, rel: str, text: str, *, age_days: float = 0) -> Path:
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if age_days:
            when = time.time() - age_days * 86400
            os.utime(path, (when, when))
        return path


@pytest.fixture
def machines(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path]) -> Machines:
    return Machines(isolated_env, fake_exe)


def mirror(home: Path, name: str) -> Path:
    return home / ".local/state/agent-runs/remotes" / name


def test_copies_each_machine_runs_into_the_other_machine_mirror(machines: Machines) -> None:
    # Bug this guards: a retro on either machine misses the runs of the other one.
    machines.write(machines.laptop, ".claude/projects/-Users-m-repo/L1.jsonl", '{"laptop": 1}\n')
    machines.write(machines.devbox, ".claude/projects/-home-user-repo/D1.jsonl", '{"devbox": 1}\n')
    machines.write(machines.devbox, ".codex/sessions/2026/11/25/rollout-x-D2.jsonl", '{"codex": 1}\n')
    machines.write(machines.devbox, ".local/state/agent-trace/spans/2026-11-25.jsonl", '{"span": 1}\n')
    machines.write(machines.devbox, ".local/state/agent-trace/sessions/D1.ticket", "CH-2\n")
    machines.write(machines.devbox, ".local/state/agent-trace/collect.log", "noise\n")
    machines.write(machines.devbox, "dotfiles/.retro/2026-11-25-matrix-run.md", "report\n")

    result = machines.sync()
    assert result.returncode == 0, result.stderr

    pulled = mirror(machines.laptop, "devbox")
    assert (pulled / "claude-projects/-home-user-repo/D1.jsonl").read_text() == '{"devbox": 1}\n'
    assert (pulled / "codex-sessions/2026/11/25/rollout-x-D2.jsonl").read_text() == '{"codex": 1}\n'
    assert (pulled / "agent-trace/spans/2026-11-25.jsonl").read_text() == '{"span": 1}\n'
    assert (pulled / "agent-trace/sessions/D1.ticket").read_text() == "CH-2\n"
    assert (pulled / "retro/2026-11-25-matrix-run.md").read_text() == "report\n"
    assert (pulled / "agent-trace").is_dir() and not (pulled / "agent-trace/collect.log").exists()

    pushed = mirror(machines.devbox, "laptop")
    assert (pushed / "claude-projects/-Users-m-repo/L1.jsonl").read_text() == '{"laptop": 1}\n'
    # A mirror is never copied on again, so the laptop does not get its own runs back through the devbox.
    assert not mirror(machines.laptop, "laptop").exists()


def test_copies_a_changed_file_again_and_skips_files_older_than_the_window(machines: Machines) -> None:
    transcript = machines.write(machines.devbox, ".claude/projects/p/D1.jsonl", "line 1\n")
    machines.write(machines.devbox, ".claude/projects/p/OLD.jsonl", "old\n", age_days=40)
    assert machines.sync().returncode == 0

    with transcript.open("a") as handle:
        handle.write("line 2\n")
    result = machines.sync()
    assert result.returncode == 0, result.stderr

    pulled = mirror(machines.laptop, "devbox") / "claude-projects/p"
    assert (pulled / "D1.jsonl").read_text() == "line 1\nline 2\n"
    assert not (pulled / "OLD.jsonl").exists()
    assert machines.sync("--days", "60").returncode == 0
    assert (pulled / "OLD.jsonl").read_text() == "old\n"


def test_files_of_a_finished_batch_stay_copied_when_a_later_batch_fails(machines: Machines) -> None:
    # Bug this guards: one tar for the whole first copy (about 120 MB for two days of transcripts) can pass the
    # ssh time limit over the devbox tunnel. Then every run fails and the copy never grows.
    for name in ("a", "b", "c"):
        machines.write(machines.devbox, f".claude/projects/p/{name}.jsonl", name * 700_000)
    (machines.laptop / "ssh-fail-after").write_text("2\n")  # the list call and the first batch succeed

    result = machines.sync("--batch-mb", "1")

    assert result.returncode == 1
    assert "broken pipe" in result.stderr
    pulled = mirror(machines.laptop, "devbox") / "claude-projects/p"
    copied = sorted(path.name for path in pulled.glob("*.jsonl"))
    assert copied == ["a.jsonl"]
    assert (pulled / "a.jsonl").read_text() == "a" * 700_000

    (machines.laptop / "ssh-fail-after").unlink()
    assert machines.sync("--batch-mb", "1").returncode == 0
    assert sorted(path.name for path in pulled.glob("*.jsonl")) == ["a.jsonl", "b.jsonl", "c.jsonl"]


def test_mirror_is_private_to_the_user(machines: Machines) -> None:
    # Spans hold the user's email address, so the copy keeps agent-trace's 0700 folders and 0600 files.
    machines.write(machines.devbox, ".local/state/agent-trace/spans/2026-11-25.jsonl", "{}\n").chmod(0o644)
    assert machines.sync().returncode == 0

    root = mirror(machines.laptop, "devbox")
    for path in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o700 if path.is_dir() else 0o600), f"{path}: {oct(mode)}"


def test_a_stopped_devbox_is_skipped_without_ssh(machines: Machines) -> None:
    # `ssh devbox` starts a stopped box (devbox.sh _proxy passes --start-workstation). A sync every
    # 15 minutes would then keep the box running and paid for, so the tool checks the state first.
    (machines.laptop / "devbox-state").write_text("STATE_STOPPED\n")
    machines.write(machines.laptop, ".claude/projects/p/L1.jsonl", "x\n")

    result = machines.sync()

    assert result.returncode == 0, result.stderr
    assert "devbox is STATE_STOPPED, skipped" in result.stdout
    assert (machines.laptop / "devbox.log").read_text().splitlines() == ["status --json"]
    assert not (machines.laptop / "ssh-hosts.log").exists()
    assert not mirror(machines.laptop, "devbox").exists()


def test_unreachable_devbox_is_a_quiet_skip(machines: Machines) -> None:
    # The box can stop between the state check and the copy. The launchd job must not fail then.
    (machines.laptop / "ssh-down").touch()
    machines.write(machines.laptop, ".claude/projects/p/L1.jsonl", "x\n")

    result = machines.sync()

    assert result.returncode == 0, result.stderr
    assert "devbox not reachable" in result.stdout
    assert (machines.laptop / "ssh-hosts.log").read_text().splitlines() == ["devbox"]
    assert not mirror(machines.laptop, "devbox").exists()
    assert not mirror(machines.devbox, "laptop").exists()


def test_refuses_a_name_that_is_not_a_plain_folder_name(machines: Machines) -> None:
    result = subprocess.run(
        [str(TOOL), "--host", "devbox", "--as", "../evil"], env=machines.env, text=True, capture_output=True
    )
    assert result.returncode == 2
    assert "--as" in result.stderr
    assert not (machines.laptop / "ssh-hosts.log").exists()
