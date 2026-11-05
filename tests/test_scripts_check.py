"""scripts/check: the groups that CI runs as separate jobs, and a run that reports every failure.

Each test copies scripts/check into a scratch tree and puts a fake `uv` first on PATH. The fake records each
command it gets and fails the ones named in FAIL_ON, so the tests see which checks ran without running them.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check"

ALL_COMMANDS = [
    "run --frozen ruff check",
    "run --frozen ruff format --check",
    "run --frozen ty check",
    "run --frozen python scripts/check_guidance_links.py",
    "run --frozen python scripts/check_md_budgets.py",
    "run --frozen python scripts/check_leaks.py",
    "run --frozen pytest",
]

FAKE_UV = """#!/usr/bin/env bash
echo "$*" >> "$UV_LOG"
case "|$FAIL_ON|" in *"|$*|"*) exit 1 ;; esac
exit 0
"""


def run_check(
    tmp_path: Path, *groups: str, fail_on: tuple[str, ...] = ()
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    tree = tmp_path / "repo"
    (tree / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, tree / "scripts" / "check")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "uv.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "UV_LOG": str(log),
        "FAIL_ON": "|".join(fail_on),
    }
    result = subprocess.run(
        [str(tree / "scripts" / "check"), *groups], text=True, capture_output=True, env=env, check=False
    )
    ran = log.read_text().splitlines() if log.exists() else []
    return result, ran


def test_no_group_runs_every_check(tmp_path: Path) -> None:
    result, ran = run_check(tmp_path)

    assert result.returncode == 0, result.stderr
    assert ran == ALL_COMMANDS


def test_a_failure_does_not_hide_the_checks_after_it(tmp_path: Path) -> None:
    # Bug caught: with `set -e`, a format failure stopped the run and pytest never ran, so CI hid test failures.
    result, ran = run_check(tmp_path, fail_on=("run --frozen ruff format --check", "run --frozen pytest"))

    assert result.returncode == 1
    assert ran == ALL_COMMANDS
    assert "2 check(s) failed" in result.stderr
    assert "ruff format --check" in result.stderr
    assert "pytest" in result.stderr


def test_a_group_runs_only_its_own_checks(tmp_path: Path) -> None:
    # Bug caught: a CI job that ignores its group runs every check, so its red mark no longer names the cause.
    result, ran = run_check(tmp_path, "md-budgets")

    assert result.returncode == 0, result.stderr
    assert ran == ["run --frozen python scripts/check_md_budgets.py"]


def test_a_failing_group_fails_the_run(tmp_path: Path) -> None:
    result, ran = run_check(tmp_path, "lint", fail_on=("run --frozen ty check",))

    assert result.returncode == 1
    assert ran == ALL_COMMANDS[:3]


def test_an_unknown_group_is_refused_before_any_check_runs(tmp_path: Path) -> None:
    # Bug caught: a misspelled group in checks.yml would run nothing and pass.
    result, ran = run_check(tmp_path, "lint", "test")

    assert result.returncode == 2
    assert "unknown group 'test'" in result.stderr
    assert ran == []
