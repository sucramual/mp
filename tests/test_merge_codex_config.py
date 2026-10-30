"""Black-box tests for config/codex/merge_config.py, run directly as a subprocess.

install.sh-level behavior (legacy links, drift, idempotence) lives in test_install_codex_config.py.
These tests cover what needs custom bases or a temp git repo: recovering app keys from git history,
removing keys the base dropped, dotfiles-pr's conversion record, and TOML edge cases.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

SCRIPT = REPO_ROOT / "config" / "codex" / "merge_config.py"
RunTool = Callable[..., subprocess.CompletedProcess[str]]

# The tracked file before and after the app-written keys left it, as in the PR that stripped them.
WITH_APP_KEYS = """\
notify = ["/Applications/Example.app/notifier", "turn-ended"]
model = "old"

[mcp_servers.notion]
url = "https://mcp.notion.com/mcp"

[mcp_servers.node_repl.env]
NODE_REPL_TRUSTED_SERVICES = '{"browser":"/x/service.mjs"}'
"""
STRIPPED = """\
model = "new"

[mcp_servers.notion]
url = "https://mcp.notion.com/mcp"
"""


def merge(run_tool: RunTool, env: IsolatedEnv, *args: str | Path, **extra_env: str) -> str:
    result = run_tool([sys.executable, SCRIPT, *args], cwd=env.root, **extra_env)
    assert result.returncode == 0, f"merge_config.py should succeed\n{result.stdout}\n{result.stderr}"
    assert result.stderr == "", f"merge_config.py should not write to stderr\n{result.stderr}"
    return result.stdout


def load(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def repo_with_history(env: IsolatedEnv) -> Path:
    """A git repo whose config.toml had app keys in its first commit and lost them in the second."""
    repo = env.root / "dotfiles"
    repo.mkdir()
    env.git(repo, "init", "-q")
    config = repo / "config" / "codex" / "config.toml"  # In a subdirectory, like the real layout.
    config.parent.mkdir(parents=True)
    config.write_text(WITH_APP_KEYS)
    env.git(repo, "add", "config")
    env.git(repo, "commit", "-qm", "feat: config with app keys")
    config.write_text(STRIPPED)
    env.git(repo, "commit", "-qam", "fix: strip app keys")
    return config


def test_converting_a_link_into_git_recovers_keys_from_before_the_latest_commit(
    isolated_env: IsolatedEnv, run_tool: RunTool
):
    tracked = repo_with_history(isolated_env)
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.symlink_to(tracked)

    merge(run_tool, isolated_env, tracked, target)

    merged = load(target)
    assert not target.is_symlink(), "the legacy symlink should become a real file"
    assert merged["notify"] == ["/Applications/Example.app/notifier", "turn-ended"], "notify should be recovered"
    assert merged["mcp_servers"]["node_repl"]["env"]["NODE_REPL_TRUSTED_SERVICES"] == '{"browser":"/x/service.mjs"}'
    assert merged["model"] == "new", "recovered keys fill gaps only; they never override current values"
    assert tracked.read_text() == STRIPPED, "the tracked file must not be written"


def test_recovery_is_skipped_silently_without_git(isolated_env: IsolatedEnv, run_tool: RunTool):
    tracked = repo_with_history(isolated_env)
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.symlink_to(tracked)

    merge(run_tool, isolated_env, tracked, target, PATH=str(isolated_env.bin))  # bin is empty: no git.

    assert load(target) == tomllib.loads(STRIPPED), "without git the link's current contents are all that is kept"


def test_a_conversion_record_recovers_history_as_of_its_commit(isolated_env: IsolatedEnv, run_tool: RunTool):
    """dotfiles-pr byte-copied the link at the strip commit; a later commit must not hide the old keys."""
    tracked = repo_with_history(isolated_env)
    repo = tracked.parents[2]
    strip_commit = isolated_env.git(repo, "rev-parse", "HEAD")
    tracked.write_text(STRIPPED.replace('"new"', '"newer"'))
    isolated_env.git(repo, "commit", "-qam", "feat: newer model")
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text(STRIPPED)
    record = Path(f"{target}.dotfiles-legacy-link")
    record.write_text(f"{tracked}\n{strip_commit}\n")

    merge(run_tool, isolated_env, tracked, target)

    merged = load(target)
    assert merged["notify"] == ["/Applications/Example.app/notifier", "turn-ended"], "notify should be recovered"
    assert merged["model"] == "newer", "the tracked value still wins"
    assert not record.exists(), "a merge should consume the conversion record"


def test_keys_the_base_dropped_are_removed_only_when_unchanged(isolated_env: IsolatedEnv, run_tool: RunTool):
    base = isolated_env.root / "base.toml"
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    base.write_text('keep = "k"\ngone = "g"\nedited = "e"\n\n[old]\nonly = true\n\n[mixed]\ntracked = 1\n')
    target.write_text('app = "a"\n\n[mixed]\nlocal = 2\n')
    merge(run_tool, isolated_env, base, target)
    assert Path(f"{target}.dotfiles-base").read_bytes() == base.read_bytes(), "the applied base should be recorded"

    target.write_text(target.read_text().replace('edited = "e"', 'edited = "mine"'))
    base.write_text('keep = "k"\n')
    output = merge(run_tool, isolated_env, base, target).splitlines()

    assert load(target) == {"keep": "k", "app": "a", "edited": "mine", "mixed": {"local": 2}}, (
        "unchanged dropped keys go, emptied tables go, edited and app keys stay"
    )
    for key in ("gone", "old.only", "mixed.tracked"):
        assert f"  Codex config removed: {key}" in output, f"removal of {key} should be reported\n{output}"
    assert "  Codex config note: edited is no longer tracked but was changed locally; kept" in output, output
    assert Path(f"{target}.dotfiles-base").read_text() == 'keep = "k"\n', "the new base should be recorded"


# Protects: the work overlay's keys reach the local config, win over the public base, and stay on later runs.
# Bug caught: dotfiles-pr sync merges without the overlay, so the recorded base drops the work project and the
# next sync removes it; or the state file holds only the public base, so the overlay keys are never removed.
def test_overlay_keys_merge_on_top_of_the_base_and_leave_when_the_overlay_does(
    isolated_env: IsolatedEnv, run_tool: RunTool
):
    base = isolated_env.root / "base.toml"
    base.write_text('model = "public"\n\n[projects."/p/public"]\ntrust_level = "trusted"\n')
    overlay = isolated_env.root / "work.toml"
    overlay.write_text('model = "work"\n\n[projects."/p/work"]\ntrust_level = "trusted"\n')
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('app = "a"\n')

    merge(run_tool, isolated_env, "--overlay", overlay, base, target)

    combined = {
        "model": "work",
        "projects": {"/p/public": {"trust_level": "trusted"}, "/p/work": {"trust_level": "trusted"}},
    }
    assert load(target) == {"app": "a", **combined}, "the overlay adds its keys and wins on a conflict"
    assert load(Path(f"{target}.dotfiles-base")) == combined, "the recorded base should be base plus overlay"
    assert base.read_text().startswith('model = "public"'), "the tracked base is only read"

    second = merge(run_tool, isolated_env, "--overlay", overlay, base, target)
    assert second == "  ~/.codex/config.toml already current\n", second

    output = merge(run_tool, isolated_env, base, target).splitlines()
    assert load(target) == {
        "app": "a",
        "model": "public",
        "projects": {"/p/public": {"trust_level": "trusted"}},
    }, "without the overlay, its unchanged keys go and the base value returns"
    assert '  Codex config removed: projects."/p/work".trust_level' in output, output


# Protects: a named overlay that does not exist stops the merge before the local file changes.
# Bug caught: a typo in the overlay path merges only the public base, which removes the work keys.
def test_a_missing_overlay_is_refused(isolated_env: IsolatedEnv, run_tool: RunTool):
    base = isolated_env.root / "base.toml"
    base.write_text('model = "public"\n')
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('app = "a"\n')
    missing = isolated_env.root / "absent.toml"

    result = run_tool([sys.executable, SCRIPT, "--overlay", missing, base, target], cwd=isolated_env.root)

    assert result.returncode != 0
    assert f"overlay {missing} is not a file" in result.stderr
    assert target.read_text() == 'app = "a"\n', "the local file should not change"
    assert not Path(f"{target}.dotfiles-base").exists(), "no base should be recorded"


def test_no_recorded_base_means_no_removals(isolated_env: IsolatedEnv, run_tool: RunTool):
    base = isolated_env.root / "base.toml"
    base.write_text('keep = "k"\n')
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('keep = "k"\ngone = "g"\n')

    output = merge(run_tool, isolated_env, base, target)

    assert load(target) == {"keep": "k", "gone": "g"}, "without a recorded base nothing is removed"
    assert output == "  ~/.codex/config.toml already current\n", output
    assert Path(f"{target}.dotfiles-base").read_bytes() == base.read_bytes(), (
        "the base should be recorded even when the file is already current"
    )


def test_nan_and_multiline_keys(isolated_env: IsolatedEnv, run_tool: RunTool):
    base = isolated_env.root / "base.toml"
    base.write_text('ratio = nan\nmodel = "tracked"\n')
    target = isolated_env.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('ratio = nan\nmodel = "stale"\n"line\\n" = 1\n')

    merge(run_tool, isolated_env, base, target)

    assert load(target)["line\n"] == 1, "a key ending in a newline must be written quoted"
    second = merge(run_tool, isolated_env, base, target)
    assert second == "  ~/.codex/config.toml already current\n", f"NaN should compare equal to NaN\n{second}"


def test_a_write_after_loading_aborts_the_no_op_path(
    isolated_env: IsolatedEnv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The app rewrites a tracked key between load and the "already current" check: abort, record nothing."""
    spec = importlib.util.spec_from_file_location("merge_config_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    base = isolated_env.root / "base.toml"
    base.write_text('model = "tracked"\n')
    target = isolated_env.root / "config.toml"
    target.write_text('model = "tracked"\n')
    record = Path(f"{target}.dotfiles-legacy-link")
    record.write_text("/nonexistent/config.toml\nHEAD\n")
    app_write = 'model = "set by the app"\n'
    original_merge = module.merge

    def merge_then_app_writes(local: dict, tracked: dict) -> tuple[dict, list]:
        target.write_text(app_write)  # Lands after Local() loaded the file, before the no-op check.
        return original_merge(local, tracked)

    monkeypatch.setattr(module, "merge", merge_then_app_writes)
    with pytest.raises(SystemExit) as exit_info:
        module.main(["merge_config.py", str(base), str(target)])

    assert "Codex wrote the config during install; re-run" in str(exit_info.value.code)
    assert "already current" not in capsys.readouterr().out, "a changed file must not be reported as current"
    assert target.read_text() == app_write, "the app's write must be left untouched"
    assert not Path(f"{target}.dotfiles-base").exists(), "an aborted merge must not record the base"
    assert record.is_file(), "an aborted merge must keep the conversion record"
