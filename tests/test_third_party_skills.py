"""Tests for scripts/third_party_skills.py. They never read the real HOME or run npx."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "third_party_skills.py"
_spec = importlib.util.spec_from_file_location("third_party_skills_under_test", SCRIPT)
assert _spec is not None and _spec.loader is not None
tps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tps)


def lock_entry(source: str, source_type: str = "github", url: str = "") -> dict:
    return {"source": source, "sourceType": source_type, "sourceUrl": url or f"https://github.com/{source}.git"}


LOCK = {
    "version": 3,
    "skills": {
        "zeta": lock_entry("owner/b"),
        "alpha": lock_entry("owner/b"),
        "solo": lock_entry("owner/a"),
        "capture-concept": lock_entry("sucramual/mp"),
        # Older lock files record this repository under its old name.
        "old-name": lock_entry("sucramual/dotfiles"),
        "local-one": lock_entry("/Users/someone/dotfiles", "local", "/Users/someone/dotfiles"),
    },
    "dismissed": {},
    "lastSelectedAgents": ["claude-code"],
}


def run_script(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True, check=False, timeout=60
    )


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(LOCK))
    return lock, tmp_path / "third-party.txt"


def test_parse_manifest_ignores_comments_and_blank_lines():
    text = "# header\n\nowner/b  zeta alpha  # trailing comment\n   \nowner/a solo\n"

    assert tps.parse_manifest(text) == {"owner/b": ["alpha", "zeta"], "owner/a": ["solo"]}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("owner/a\n", "has no skill names"),
        ("owner/a x\nowner/a y\n", "appears more than once"),
        ("owner/a x\nowner/b x\n", "already listed"),
        ("sucramual/mp x\n", "not a third-party source"),
        ("sucramual/dotfiles x\n", "not a third-party source"),
    ],
)
def test_parse_manifest_rejects_bad_lines(text: str, message: str):
    with pytest.raises(tps.ManifestError, match=message):
        tps.parse_manifest(text)


def test_export_filters_dotfiles_sources_and_sorts(files: tuple[Path, Path]):
    lock, manifest = files

    result = run_script("--lock", lock, "--manifest", manifest, "export")

    assert result.returncode == 0, result.stderr
    body = [line for line in manifest.read_text().splitlines() if line and not line.startswith("#")]
    assert body == ["owner/a  solo", "owner/b  alpha zeta"]
    assert tps.parse_manifest(manifest.read_text()) == {"owner/a": ["solo"], "owner/b": ["alpha", "zeta"]}


@pytest.mark.parametrize(
    ("entry", "own"),
    [
        (lock_entry("sucramual/mp"), True),
        (lock_entry("sucramual/dotfiles"), True),
        (lock_entry("other/name", url="https://github.com/sucramual/mp.git"), True),
        (lock_entry("other/name", url="git@github.com:sucramual/dotfiles.git"), True),
        (lock_entry("other/name", url="https://github.com/sucramual/mp/tree/main/skills"), True),
        (lock_entry("sucramual/mp-private"), False),
        (lock_entry("sucramual/mpx"), False),
        (lock_entry("owner/a"), False),
    ],
)
def test_is_local_source_knows_both_repository_names(entry: dict, own: bool):
    # Bug caught: a lock entry under the old or the new name is exported as a third-party skill,
    # or a different repository whose name starts with "mp" is dropped from the manifest.
    assert tps.is_local_source(entry["source"], entry) is own


def test_export_is_deterministic(files: tuple[Path, Path]):
    lock, manifest = files
    run_script("--lock", lock, "--manifest", manifest, "export")
    first = manifest.read_text()

    run_script("--lock", lock, "--manifest", manifest, "export")

    assert manifest.read_text() == first


def test_check_passes_when_in_sync(files: tuple[Path, Path]):
    lock, manifest = files
    run_script("--lock", lock, "--manifest", manifest, "export")

    result = run_script("--lock", lock, "--manifest", manifest, "check")

    assert result.returncode == 0, result.stderr
    assert "matches" in result.stdout


def test_check_reports_drift_in_both_directions(files: tuple[Path, Path]):
    lock, manifest = files
    manifest.write_text("owner/a  solo\nowner/b  alpha gone\n")

    result = run_script("--lock", lock, "--manifest", manifest, "check")

    assert result.returncode == 1
    assert "+ owner/b zeta" in result.stderr
    assert "- owner/b gone" in result.stderr
    assert "solo" not in result.stderr
    assert "export" in result.stderr


def test_check_fails_clearly_without_lock(tmp_path: Path):
    manifest = tmp_path / "third-party.txt"
    manifest.write_text("owner/a solo\n")

    result = run_script("--lock", tmp_path / "missing.json", "--manifest", manifest, "check")

    assert result.returncode == 2
    assert "lock not found" in result.stderr


def test_install_dry_run_prints_one_command_per_source_and_ignores_the_lock(files: tuple[Path, Path]):
    lock, manifest = files
    manifest.write_text("owner/b  alpha new zeta\nowner/a  solo\n")

    result = run_script("--lock", lock, "--manifest", manifest, "install", "--dry-run")

    assert result.returncode == 0, result.stderr
    commands = [line for line in result.stdout.splitlines() if line.startswith("[dry-run]")]
    agents = "-g -a claude-code codex cursor -y"
    # owner/a solo is in the lock, but install still runs: the lock has no per-agent link data.
    assert commands == [
        f"[dry-run] npx --yes skills@latest add owner/a {agents} --skill solo",
        f"[dry-run] npx --yes skills@latest add owner/b {agents} --skill alpha new zeta",
    ]
    assert "would run 2 install commands for 4 skills" in result.stdout


def test_install_has_no_force_flag(files: tuple[Path, Path]):
    lock, manifest = files
    manifest.write_text("owner/a  solo\n")

    result = run_script("--lock", lock, "--manifest", manifest, "install", "--force")

    assert result.returncode == 2
    assert "--force" in result.stderr


def test_install_runs_without_a_lock_and_reports_failures(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    manifest = tmp_path / "third-party.txt"
    manifest.write_text("owner/a  one two\nowner/b  three\n")
    calls: list[list[str]] = []

    def runner(command: list[str]) -> int:
        calls.append(command)
        return 1 if "owner/a" in command else 0

    code = tps.main(["--lock", str(tmp_path / "missing.json"), "--manifest", str(manifest), "install"], runner=runner)

    assert code == 1
    assert calls == [tps.install_command("owner/a", ["one", "two"]), tps.install_command("owner/b", ["three"])]
    assert calls[0][-3:] == ["--skill", "one", "two"]
    assert "Install failed for: owner/a" in capsys.readouterr().err


@pytest.mark.parametrize("source_type", ["git", "well-known", None])
def test_export_rejects_non_github_sources(files: tuple[Path, Path], source_type: str | None):
    lock, manifest = files
    data = json.loads(lock.read_text())
    data["skills"]["remote"] = {"source": "https://example.com/skills.git", "sourceType": source_type}
    lock.write_text(json.dumps(data))

    result = run_script("--lock", lock, "--manifest", manifest, "export")

    assert result.returncode == 2
    assert "'remote'" in result.stderr
    assert "https://example.com/skills.git" in result.stderr
    assert not manifest.exists(), "a failed export should not write the manifest"


def test_default_lock_path_mirrors_the_skills_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert tps.default_lock_path({}) == tmp_path / ".agents" / ".skill-lock.json"
    # The CLI treats an empty XDG_STATE_HOME as unset.
    assert tps.default_lock_path({"XDG_STATE_HOME": ""}) == tmp_path / ".agents" / ".skill-lock.json"
    assert tps.default_lock_path({"XDG_STATE_HOME": "/state"}) == Path("/state/skills/.skill-lock.json")


@pytest.mark.parametrize("use_xdg", [True, False])
def test_check_reads_the_default_lock_from_the_environment(tmp_path: Path, use_xdg: bool):
    home, state = tmp_path / "home", tmp_path / "state"
    lock = state / "skills" / ".skill-lock.json" if use_xdg else home / ".agents" / ".skill-lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps(LOCK))
    manifest = tmp_path / "third-party.txt"
    manifest.write_text("owner/a  solo\nowner/b  alpha zeta\n")
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    if use_xdg:
        env["XDG_STATE_HOME"] = str(state)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest), "check"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "matches" in result.stdout


def test_lock_without_skills_key_is_empty():
    assert tps.parse_lock('{"token": "x"}') == {}
