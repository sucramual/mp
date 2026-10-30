"""Black-box tests for tools/dotfiles-pr.

Each test runs the real tool as a subprocess against temp Git repos, with fake ``gh`` and ``bu``
on PATH. Set DOTFILES_PR_PYTHON (e.g. /opt/homebrew/bin/python3.13) to pick the interpreter; the default is
the tool's shebang.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from collections.abc import Callable
from functools import cached_property
from pathlib import Path

import pytest
from conftest import REPO_ROOT, IsolatedEnv

TOOL = REPO_ROOT / "tools" / "dotfiles-pr" / "bin" / "dotfiles-pr"
MERGE_SCRIPT = REPO_ROOT / "config" / "codex" / "merge_config.py"
LINK_SCRIPT = REPO_ROOT / "scripts" / "link_skills.py"
PR_URL = "https://github.com/sucramual/mp/pull/123"
BODY_LINES = "## Summary\nAdds a thing.\n"
RunTool = Callable[..., subprocess.CompletedProcess[str]]

# Fake gh logs each call as one JSON array of its arguments, so argument boundaries survive,
# and reports a PR only after `pr create` ran.
# Like a Claude Code cloud session, it rejects `pr view` (GraphQL) with HTTP 403. It answers the REST call
# `api repos/{owner}/{repo}/pulls?head=...&state=all` with a JSON list.
# A file gh-prs/<branch with / as _>.json overrides the PR for that branch. It holds either
# {"state", "headRefOid"} (converted to the REST shape) or a raw REST list.
FAKE_GH = r"""python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>"@GH_LOG@"
if [[ "$1 $2" == 'pr view' ]]; then
  echo 'HTTP 403: GitHub GraphQL is not available from Claude Code sessions; use the REST API instead' >&2
  exit 1
fi
if [[ "$1" == api && "$2" == repos/*/pulls\?head=* ]]; then
  if [[ -e "@API_FAIL@" ]]; then
    echo 'error connecting to api.github.com' >&2
    exit 1
  fi
  exec python3 - "$2" <<'PY'
import json, os, sys
from urllib.parse import parse_qs, urlsplit

query = parse_qs(urlsplit(sys.argv[1]).query)
branch = query["head"][0].split(":", 1)[1]
override = os.path.join("@GH_PRS@", branch.replace("/", "_") + ".json")
if os.path.exists(override):
    data = json.load(open(override))
    if isinstance(data, list):
        prs = data
    else:
        merged = data["state"] == "MERGED"
        prs = [{
            "state": "open" if data["state"] == "OPEN" else "closed",
            "merged_at": "2026-01-01T00:00:00Z" if merged else None,
            "created_at": "2026-01-01T00:00:00Z",
            "html_url": "@PR_URL@",
            "head": {"sha": data["headRefOid"]},
        }]
elif os.path.exists("@PR_MARKER@"):
    prs = [{"state": "open", "merged_at": None, "created_at": "2026-01-01T00:00:00Z",
            "html_url": "@PR_URL@", "head": {"sha": "0" * 40}}]
else:
    prs = []
print(json.dumps(prs))
PY
fi
if [[ "$1 $2" == 'pr create' ]]; then
  touch "@PR_MARKER@"
  echo 'Creating pull request...' >&2
  printf '%s\n' "@PR_URL@"
  exit 0
fi
echo "fake gh: unexpected command: $*" >&2
exit 2
"""

# Fake bu records "<cwd><TAB><args>", and separately the HEAD of its cwd when it ran.
# The file bu-mode picks its behavior: ok (default), fail, or unknown.
FAKE_BU = r"""printf '%s\t%s\n' "$(pwd -P)" "$*" >>"@BU_LOG@"
printf '%s\n' "$(git rev-parse HEAD 2>/dev/null || echo 'no HEAD')" >>"@BU_HEAD_LOG@"
case "$(cat "@BU_MODE@" 2>/dev/null || echo ok)" in
  fail)
    echo 'fake bu: prune report'
    echo 'fake bu: removal failed' >&2
    exit 1 ;;
  unknown)
    printf '%s\n' "error: unrecognized subcommand 'prune'" '' 'Usage: bu [OPTIONS] <COMMAND>' >&2
    exit 2 ;;
esac
echo 'fake bu: prune report'
"""

# Fake scripts/check, committed to the fake origin's main like the real one. It records its cwd, and
# separately the worktree's HEAD and `git status --porcelain` when it ran.
# The file check-mode picks its behavior: pass (default) or fail (exit 3).
FAKE_CHECK = r"""#!/usr/bin/env bash
printf '%s\n' "$(pwd -P)" >>"@CHECK_LOG@"
{ git rev-parse HEAD; git status --porcelain; } >>"@CHECK_STATE_LOG@"
if [[ "$(cat "@CHECK_MODE@" 2>/dev/null || echo pass)" == fail ]]; then
  echo 'fake check: failed' >&2
  exit 3
fi
echo 'fake check: passed'
"""


def tool_cmd() -> list[str]:
    python = os.environ.get("DOTFILES_PR_PYTHON")
    return [python, str(TOOL)] if python else [str(TOOL)]


def fill(template: str, **values: str | Path) -> str:
    for key, value in values.items():
        template = template.replace(f"@{key}@", str(value))
    return template


def error_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("dotfiles-pr:")]


def last_line(text: str) -> str:
    lines = text.splitlines()
    return lines[-1] if lines else ""


def flag_values(args: list[str]) -> dict[str, str]:
    """Parse ["--flag", "value", ...] into {flag: value}, so a test can ignore flag order."""
    flags, values = args[::2], args[1::2]
    assert len(args) % 2 == 0 and all(flag.startswith("--") for flag in flags), (
        f"expected --flag value pairs, got {args}"
    )
    assert len(set(flags)) == len(flags), f"expected each flag once, got {args}"
    return dict(zip(flags, values, strict=True))


def traced(stderr: str, command: str) -> bool:
    """Whether stderr has a `+ ` trace line that runs command, such as "git push" or "gh api".

    The README's contract: each git and gh command is echoed to stderr before it runs. This matches only the
    program and its subcommand words, after any options such as `--literal-pathspecs`, so it ignores the
    arguments and the flag order.
    """
    program, *subcommand = command.split()
    for line in stderr.splitlines():
        words = line.split()
        if words[:2] != ["+", program]:
            continue
        positional = [word for word in words[2:] if not word.startswith("-")]
        if positional[: len(subcommand)] == subcommand:
            return True
    return False


class World:
    """The temp setup: a bare origin with one commit on main, and a clone that stands in for ~/dotfiles."""

    def __init__(self, env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool) -> None:
        self.iso = env
        self.root = env.root
        self._run_tool = run_tool
        self.gh_log = self.root / "gh.log"
        self.gh_prs = self.root / "gh-prs"
        self.pr_marker = self.root / "pr-created"
        self.gh_api_fail = self.root / "gh-api-fail"
        self.bu_log = self.root / "bu.log"
        self.bu_head_log = self.root / "bu-head.log"
        self.bu_mode = self.root / "bu-mode"
        self.bu_config = self.root / "bu-dotfiles.toml"
        self.check_log = self.root / "check.log"
        self.check_state_log = self.root / "check-state.log"
        self.check_mode = self.root / "check-mode"
        self.hook_log = self.root / "hook.log"
        self.body = self.root / "body.md"
        self.gh_prs.mkdir()
        self.bu_config.write_text("")
        self.body.write_text(BODY_LINES)

        fake_exe(
            "gh",
            fill(
                FAKE_GH,
                GH_LOG=self.gh_log,
                GH_PRS=self.gh_prs,
                PR_MARKER=self.pr_marker,
                PR_URL=PR_URL,
                API_FAIL=self.gh_api_fail,
            ),
        )
        # bu has its own directory, and PATH drops each directory with a real bu, so a test can remove bu from PATH.
        bu_bin = self.root / "bu-bin"
        fake_exe(
            "bu",
            fill(FAKE_BU, BU_LOG=self.bu_log, BU_HEAD_LOG=self.bu_head_log, BU_MODE=self.bu_mode),
            directory=bu_bin,
        )
        outer = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (Path(d) / "bu").exists()]
        self.path_without_bu = os.pathsep.join([str(env.bin), *outer])
        env.env["PATH"] = os.pathsep.join([str(env.bin), str(bu_bin), *outer])

        self.origin = self.root / "origin.git"

    @cached_property
    def dotfiles(self) -> Path:
        """The ~/dotfiles stand-in, with scripts/check on origin/main. Built on first use; sync-only tests skip it."""
        dotfiles = self.root / "dotfiles"
        seed = self.root / "seed"
        self.git(self.root, "init", "-q", "--bare", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.origin), str(seed))
        (seed / "README.md").write_text("hello\n")
        (seed / "scripts").mkdir()
        check = seed / "scripts" / "check"
        check.write_text(
            fill(FAKE_CHECK, CHECK_LOG=self.check_log, CHECK_STATE_LOG=self.check_state_log, CHECK_MODE=self.check_mode)
        )
        check.chmod(0o755)
        self.git(seed, "add", "README.md", "scripts/check")
        self.git(seed, "commit", "-qm", "chore: initial")
        self.git(seed, "push", "-q", "origin", "main")
        self.git(self.root, "clone", "-q", str(self.origin), str(dotfiles))
        # A pre-commit hook proves that ship does not bypass hooks.
        hook = dotfiles / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/usr/bin/env bash\necho ran >>'{self.hook_log}'\n")
        hook.chmod(0o755)
        self._origin_main_before = self.origin_rev(self.origin, "refs/heads/main")
        return dotfiles

    @property
    def origin_main_before(self) -> str:
        """origin/main as recorded when the dotfiles stand-in was built, before any tool run."""
        _ = self.dotfiles
        return self._origin_main_before

    # --- running ---------------------------------------------------------------

    def git(self, cwd: Path, *args: str) -> str:
        return self.iso.git(cwd, *args)

    def origin_rev(self, git_dir: Path, ref: str) -> str:
        return self.git(self.root, f"--git-dir={git_dir}", "rev-parse", ref)

    def ref_exists(self, cwd: Path, ref: str) -> bool:
        result = subprocess.run(["git", "show-ref", "--verify", "--quiet", ref], cwd=cwd, env=self.iso.env)
        return result.returncode == 0

    def origin_has(self, ref: str) -> bool:
        return self.ref_exists(self.origin, ref)

    def run(self, cwd: Path, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        """Run dotfiles-pr in cwd, like the bash run_tool: DOTFILES_DIR and DOTFILES_BU_CONFIG set, extras on top."""
        env = {"DOTFILES_BU_CONFIG": str(self.bu_config), **extra_env}
        if "DOTFILES_DIR" not in env:
            env["DOTFILES_DIR"] = str(self.dotfiles)
        return self._run_tool([*tool_cmd(), *args], cwd=cwd, **env)

    def start(self, slug: str, **extra_env: str) -> Path:
        result = self.run(self.root, "start", slug, **extra_env)
        assert result.returncode == 0, f"start {slug} should succeed\n{result.stderr}"
        return self.dotfiles / ".claude" / "worktrees" / slug

    def read(self, path: Path) -> str:
        return path.read_text() if path.exists() else ""

    def fake_gh_fails_api(self) -> None:
        """Make fake gh's REST call fail with a network error, so the PR lookup cannot succeed."""
        self.gh_api_fail.touch()

    def gh_calls(self) -> list[list[str]]:
        """Each fake gh call as its argument list, in call order."""
        return [json.loads(line) for line in self.read(self.gh_log).splitlines()]

    # --- sync cases --------------------------------------------------------------
    # Each case gets its own origin, a seed clone that plays GitHub merging PRs,
    # and a main checkout that stands in for ~/dotfiles.

    def new_case(self, name: str) -> Path:
        """Create <root>/<name>{-origin.git,-seed,} with README.md and shared.txt on main. Returns the checkout."""
        origin, seed = self.root / f"{name}-origin.git", self.root / f"{name}-seed"
        self.git(self.root, "init", "-q", "--bare", str(origin))
        self.git(self.root, "clone", "-q", str(origin), str(seed))
        (seed / "README.md").write_text("hello\n")
        (seed / "shared.txt").write_text("v1\n")
        self.git(seed, "add", "README.md", "shared.txt")
        self.git(seed, "commit", "-qm", "chore: initial")
        self.git(seed, "push", "-q", "origin", "main")
        self.git(self.root, "clone", "-q", str(origin), str(self.root / name))
        return self.root / name

    def land(self, name: str, file: str, content: str, message: str) -> None:
        """Commit on origin/main, as a merged PR would."""
        seed = self.root / f"{name}-seed"
        self.git(seed, "pull", "-q", "--ff-only", "origin", "main")
        (seed / file).write_text(content + "\n")
        self.git(seed, "add", file)
        self.git(seed, "commit", "-qm", message)
        self.git(seed, "push", "-q", "origin", "main")

    def pr_json(self, branch: str, state: str, head: str) -> None:
        """Set what fake gh reports for that branch."""
        (self.gh_prs / f"{branch.replace('/', '_')}.json").write_text(json.dumps({"state": state, "headRefOid": head}))

    def run_sync(self, name: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        return self.run(self.root, "sync", DOTFILES_DIR=str(self.root / name), **extra_env)

    def origin_main_of(self, name: str) -> str:
        return self.origin_rev(self.root / f"{name}-origin.git", "refs/heads/main")

    def assert_unchanged(self, checkout: Path, branch: str, head: str, status: str, what: str) -> None:
        """Assert that a refused sync left the checkout exactly as it was."""
        assert self.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == branch, (
            f"{what}: sync should stay on {branch}"
        )
        assert self.git(checkout, "rev-parse", "HEAD") == head, f"{what}: sync should not move HEAD"
        assert self.git(checkout, "status", "--porcelain") == status, f"{what}: sync should not touch uncommitted files"


@pytest.fixture
def world(isolated_env: IsolatedEnv, fake_exe: Callable[..., Path], run_tool: RunTool) -> World:
    return World(isolated_env, fake_exe, run_tool)


# --- start: prefix selection -------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "args", "env", "branch", "succeeds", "uses_prefix"),
    [
        pytest.param(
            "first-change",
            (),
            {"CLAUDECODE": "1"},
            "claude/first-change",
            "start should succeed under Claude Code",
            "start should use the claude/ prefix when CLAUDECODE is set",
            id="claude",
        ),
        pytest.param(
            "codex-change",
            (),
            {"CODEX_THREAD_ID": "abc"},
            "codex/codex-change",
            "start should succeed under Codex",
            "start should use the codex/ prefix when a CODEX_ variable is set",
            id="codex",
        ),
        pytest.param(
            "plain-change",
            (),
            {},
            "marcus/plain-change",
            "start should succeed without an agent environment",
            "start should default to the marcus/ prefix",
            id="no-agent",
        ),
        pytest.param(
            "custom-change",
            ("--prefix", "exp"),
            {"CLAUDECODE": "1"},
            "exp/custom-change",
            "start --prefix should succeed",
            "start --prefix should override the detected prefix",
            id="prefix-flag",
        ),
    ],
)
def test_start_prefix_selection(
    world: World,
    slug: str,
    args: tuple[str, ...],
    env: dict[str, str],
    branch: str,
    succeeds: str,
    uses_prefix: str,
) -> None:
    result = world.run(world.root, "start", slug, *args, **env)
    assert result.returncode == 0, f"{succeeds}\n{result.stderr}"
    wt = world.dotfiles / ".claude" / "worktrees" / slug
    assert last_line(result.stdout) == str(wt), (
        f"start should print the worktree path as the last stdout line\n{result.stdout}"
    )
    assert wt.is_dir(), "start should create the worktree directory"
    assert world.git(wt, "rev-parse", "--abbrev-ref", "HEAD") == branch, uses_prefix
    assert world.git(wt, "rev-parse", "HEAD") == world.origin_main_before, "start should branch from origin/main"
    assert "+ git fetch origin" in result.stderr, f"start should echo git commands to stderr\n{result.stderr}"


# --- start: validation ---------------------------------------------------------------


def test_start_rejects_invalid_slug(world: World) -> None:
    result = world.run(world.root, "start", "Bad_Slug")
    assert result.returncode != 0, "start should reject a slug that is not lowercase kebab-case"
    assert "dotfiles-pr: invalid slug" in result.stderr, f"start should explain an invalid slug\n{result.stderr}"
    assert not world.bu_log.exists(), f"start should never call bu\n{world.read(world.bu_log)}"


def test_start_refuses_existing_worktree(world: World) -> None:
    world.start("first-change", CLAUDECODE="1")
    result = world.run(world.root, "start", "first-change", CLAUDECODE="1")
    assert result.returncode != 0, "start should refuse an existing branch or path"
    assert "already exists" in result.stderr, f"start should explain an existing branch or path\n{result.stderr}"
    assert not world.bu_log.exists(), f"start should never call bu\n{world.read(world.bu_log)}"


def test_start_refuses_existing_branch(world: World) -> None:
    world.git(world.dotfiles, "branch", "-q", "marcus/branch-only", "origin/main")
    result = world.run(world.root, "start", "branch-only")
    assert result.returncode != 0, "start should refuse an existing branch"
    assert "branch 'marcus/branch-only' already exists" in result.stderr, (
        f"start should name the existing branch\n{result.stderr}"
    )
    assert not world.bu_log.exists(), f"start should never call bu\n{world.read(world.bu_log)}"


# --- ship: location and branch guards ---------------------------------------------


def assert_ship_refused(world: World, cwd: Path, refusal: str, expected: str, explain: str) -> None:
    """Ship from cwd; assert it fails with expected on stderr, before the checks and without gh."""
    result = world.run(cwd, "ship", "feat: nope", "--body-file", str(world.body))
    assert result.returncode != 0, refusal
    assert expected in result.stderr, f"{explain}\n{result.stderr}"
    assert not world.gh_log.exists(), f"rejected ships should not call gh\n{world.read(world.gh_log)}"
    assert not world.check_log.exists(), "ship should refuse the location before it runs the checks"


def test_ship_refuses_main_checkout(world: World) -> None:
    (world.dotfiles / "main-checkout-edit.txt").write_text("change\n")
    assert_ship_refused(
        world,
        world.dotfiles,
        "ship should refuse the main checkout",
        "dotfiles-pr: refusing to ship from the main checkout",
        "ship should explain the main checkout refusal",
    )
    assert world.git(world.dotfiles, "status", "--porcelain"), "ship should leave the main checkout untouched"


def test_ship_refuses_detached_head(world: World) -> None:
    scratch = world.root / "scratch-worktree"
    world.git(world.dotfiles, "worktree", "add", "-q", "--detach", str(scratch), "origin/main")
    assert_ship_refused(
        world,
        scratch,
        "ship should refuse a detached HEAD",
        "detached HEAD",
        "ship should explain the detached HEAD refusal",
    )


def test_ship_refuses_main_branch(world: World) -> None:
    scratch = world.root / "scratch-worktree"
    world.git(world.dotfiles, "worktree", "add", "-q", "--detach", str(scratch), "origin/main")
    world.git(scratch, "checkout", "-q", "--ignore-other-worktrees", "main")
    (scratch / "on-main.txt").write_text("change\n")
    assert_ship_refused(
        world,
        scratch,
        "ship should refuse the main branch",
        "dotfiles-pr: refusing to ship from branch 'main'",
        "ship should explain the main branch refusal",
    )


def test_ship_refuses_foreign_repo(world: World) -> None:
    other_repo = world.root / "other-repo"
    world.git(world.root, "init", "-q", str(other_repo))
    world.git(other_repo, "commit", "-q", "--allow-empty", "-m", "chore: init")
    world.git(other_repo, "switch", "-q", "-c", "feature")
    assert_ship_refused(
        world,
        other_repo,
        "ship should refuse a repository that is not the dotfiles repo",
        "not a worktree of the dotfiles repo",
        "ship should explain the foreign repository refusal",
    )


# --- ship: message and content validation --------------------------------------------


def test_ship_rejects_non_conventional_message(world: World) -> None:
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    result = world.run(wt, "ship", "added a feature", "--body-file", str(world.body))
    assert result.returncode != 0, "ship should reject a non-Conventional Commit message"
    assert "dotfiles-pr: commit message is not a Conventional Commit" in result.stderr, (
        f"ship should explain the commit message rejection\n{result.stderr}"
    )
    assert world.git(wt, "rev-parse", "HEAD") == world.origin_main_before, "ship should not commit after a bad message"
    assert not world.check_log.exists(), "ship should reject the message before it runs the checks"
    assert not world.gh_log.exists(), f"rejected ships should not call gh\n{world.read(world.gh_log)}"


def test_ship_refuses_nothing_to_ship(world: World) -> None:
    empty_wt = world.start("plain-change")
    result = world.run(empty_wt, "ship", "feat: nothing", "--body", "Body")
    assert result.returncode != 0, "ship should fail when there is nothing to ship"
    assert "dotfiles-pr: nothing to ship" in result.stderr, (
        f"ship should explain that there is nothing to ship\n{result.stderr}"
    )
    assert not world.gh_log.exists(), f"rejected ships should not call gh\n{world.read(world.gh_log)}"


# --- ship: happy path, then an idempotent re-ship after a fix -------------------------


def test_ship_happy_path_and_reship(world: World) -> None:
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    gh_calls_before = len(world.gh_calls())

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode == 0, f"first ship should succeed\n{result.stderr}"
    assert last_line(result.stdout) == PR_URL, f"ship should print the PR URL as the last stdout line\n{result.stdout}"
    assert world.git(wt, "log", "-1", "--format=%s") == "feat(tools): add a feature", (
        "ship should commit with the message"
    )
    assert world.read(world.hook_log).splitlines() == ["ran"], "ship should run the pre-commit hook"
    remote_head = world.origin_rev(world.origin, "refs/heads/claude/first-change")
    assert remote_head == world.git(wt, "rev-parse", "HEAD"), "ship should push the branch to origin"
    assert world.git(wt, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/claude/first-change", (
        "ship should set the pushed branch as upstream"
    )
    creates = [call for call in world.gh_calls() if call[:2] == ["pr", "create"]]
    assert len(creates) == 1, f"ship should call gh pr create once\n{world.read(world.gh_log)}"
    expected_create = {
        "--base": "main",
        "--head": "claude/first-change",
        "--title": "feat(tools): add a feature",
        "--body-file": str(world.body),
    }
    assert flag_values(creates[0][2:]) == expected_create, (
        f"ship should call gh pr create with the commit subject as title\n{world.read(world.gh_log)}"
    )
    # The README's contract: each git and gh command is echoed to stderr. Count the gh traces; do not match their text.
    gh_traces = [line for line in result.stderr.splitlines() if line.startswith("+ gh ")]
    assert len(gh_traces) == len(world.gh_calls()) - gh_calls_before, (
        f"ship should echo each gh command it runs to stderr as `+ gh ...`\n{result.stderr}"
    )
    assert traced(result.stderr, "git push"), f"ship should echo its git push to stderr\n{result.stderr}"

    # Re-ship after a review fix.
    with (wt / "feature.txt").open("a") as handle:
        handle.write("fix\n")
    result = world.run(wt, "ship", "fix(tools): address review", "--body", "Follow-up")
    assert result.returncode == 0, f"second ship should succeed\n{result.stderr}"
    assert last_line(result.stdout) == PR_URL, f"second ship should print the existing PR URL\n{result.stdout}"
    creates = [call for call in world.gh_calls() if call[:2] == ["pr", "create"]]
    assert len(creates) == 1, f"second ship should not create another PR\n{world.read(world.gh_log)}"
    remote_head = world.origin_rev(world.origin, "refs/heads/claude/first-change")
    assert remote_head == world.git(wt, "rev-parse", "HEAD"), "second ship should push the fix commit"
    assert world.git(wt, "log", "-1", "--format=%s") == "fix(tools): address review", (
        "second ship should commit the fix"
    )

    # Invariant.
    assert world.origin_rev(world.origin, "refs/heads/main") == world.origin_main_before, (
        "dotfiles-pr must never push to main"
    )


def test_ship_creates_a_pr_when_the_graphql_pr_view_is_blocked(world: World) -> None:
    # Protects: ship works in a Claude Code cloud session, where `gh pr view` (GraphQL) answers HTTP 403.
    # Bug caught: find_pr treated the 403 as "cannot tell whether a PR exists" and never created the PR.
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode == 0, f"ship should create a PR without GraphQL\n{result.stderr}"
    assert last_line(result.stdout) == PR_URL, f"ship should print the new PR URL\n{result.stdout}"
    calls = world.gh_calls()
    assert not any(call[:2] == ["pr", "view"] for call in calls), f"ship must not call gh pr view\n{calls}"
    assert sum(call[:2] == ["pr", "create"] for call in calls) == 1, f"ship should create one PR\n{calls}"
    assert traced(result.stderr, "gh api"), f"ship should echo its gh api call to stderr\n{result.stderr}"


def test_ship_prints_the_open_pr_even_when_a_newer_closed_one_exists(world: World) -> None:
    # Protects: find_pr picks the open PR from the REST list, not the newest one.
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    pr = {"merged_at": None, "head": {"sha": "0" * 40}}
    older_open = {**pr, "state": "open", "created_at": "2026-01-01T00:00:00Z", "html_url": PR_URL}
    newer_closed = {**pr, "state": "closed", "created_at": "2026-02-01T00:00:00Z", "html_url": "https://example.test/9"}
    (world.gh_prs / "claude_first-change.json").write_text(json.dumps([newer_closed, older_open]))

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode == 0, f"ship should reuse the open PR\n{result.stderr}"
    assert last_line(result.stdout) == PR_URL, f"ship should print the open PR URL\n{result.stdout}"
    assert not any(call[:2] == ["pr", "create"] for call in world.gh_calls()), "ship should not create a second PR"


def test_ship_refuses_when_the_pr_lookup_fails(world: World) -> None:
    # Protects: a failed REST lookup stops ship instead of creating a duplicate PR.
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    world.fake_gh_fails_api()

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode != 0, "ship should fail when it cannot look up the PR"
    errors = error_lines(result.stderr)
    assert len(errors) == 1 and "cannot tell whether a PR exists" in errors[0], f"ship should say why\n{result.stderr}"
    assert not any(call[:2] == ["pr", "create"] for call in world.gh_calls()), "ship must not create a PR blindly"


# --- ship: the scripts/check gate ------------------------------------------------------


def test_ship_runs_checks_before_committing(world: World) -> None:
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode == 0, f"ship should succeed when the checks pass\n{result.stderr}"
    assert world.read(world.check_log).splitlines() == [str(wt)], "ship should run scripts/check once, in the worktree"
    assert world.read(world.check_state_log).splitlines() == [world.origin_main_before, "?? feature.txt"], (
        "ship should run the checks before it stages or commits (HEAD, then status, as the check saw them)\n"
        f"{world.read(world.check_state_log)}"
    )
    assert "fake check: passed" in result.stderr, f"ship should stream check output to stderr\n{result.stderr}"
    assert "fake check" not in result.stdout, f"check output should stay off stdout\n{result.stdout}"
    assert last_line(result.stdout) == PR_URL, f"ship should print the PR URL as the last stdout line\n{result.stdout}"
    assert world.origin_has("refs/heads/claude/first-change"), "ship should push after the checks pass"


def test_ship_refuses_when_checks_fail(world: World) -> None:
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    world.check_mode.write_text("fail\n")
    status_before = world.git(wt, "status", "--porcelain")

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode != 0, "ship should fail when the checks fail"
    assert error_lines(result.stderr) == ["dotfiles-pr: checks failed (exit 3); fix them and re-run ship"], (
        f"ship should name the check failure in one error line\n{result.stderr}"
    )
    assert "fake check: failed" in result.stderr, f"ship should show the check output\n{result.stderr}"
    assert world.git(wt, "rev-parse", "HEAD") == world.origin_main_before, "ship should not commit when checks fail"
    assert world.git(wt, "status", "--porcelain") == status_before, "ship should leave the changes uncommitted"
    assert not world.hook_log.exists(), "ship should not reach git commit when checks fail"
    assert not world.origin_has("refs/heads/claude/first-change"), "ship should not push when checks fail"
    assert "+ git push" not in result.stderr, f"ship should not push when checks fail\n{result.stderr}"
    assert not world.gh_log.exists(), f"ship should not call gh when checks fail\n{world.read(world.gh_log)}"


@pytest.mark.parametrize(
    ("breakage", "message"),
    [("missing", "scripts/check is missing"), ("not-executable", "scripts/check is not executable")],
)
def test_ship_refuses_without_runnable_checks(world: World, breakage: str, message: str) -> None:
    wt = world.start("first-change", CLAUDECODE="1")
    (wt / "feature.txt").write_text("feature\n")
    check = wt / "scripts" / "check"
    if breakage == "missing":
        check.unlink()
    else:
        check.chmod(0o644)

    result = world.run(wt, "ship", "feat(tools): add a feature", "--body-file", str(world.body))
    assert result.returncode != 0, f"ship should fail when scripts/check is {breakage}"
    errors = error_lines(result.stderr)
    assert len(errors) == 1 and message in errors[0], f"ship should say that {message}\n{result.stderr}"
    assert not world.check_log.exists(), "ship should not run a broken scripts/check"
    assert world.git(wt, "rev-parse", "HEAD") == world.origin_main_before, "ship should not commit without checks"
    assert not world.origin_has("refs/heads/claude/first-change"), "ship should not push without checks"
    assert not world.gh_log.exists(), f"ship should not call gh without checks\n{world.read(world.gh_log)}"


# --- sync ------------------------------------------------------------------------------


def test_sync_on_main_fast_forwards(world: World) -> None:
    checkout = world.new_case("on-main")
    world.land("on-main", "shared.txt", "v2", "feat: v2 (#1)")
    result = world.run_sync("on-main")
    assert result.returncode == 0, f"sync on main should succeed\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("on-main"), (
        "sync on main should fast-forward to origin/main"
    )
    short = world.git(checkout, "rev-parse", "--short", "HEAD")
    assert f"main is at {short} (was on main)" in result.stdout, (
        f"sync should report the new HEAD and the previous branch\n{result.stdout}"
    )
    assert traced(result.stderr, "git fetch"), f"sync should echo its git fetch to stderr\n{result.stderr}"


def test_sync_leaves_branch_that_origin_main_contains(world: World) -> None:
    """Stranded on a branch whose tip origin/main contains, with no local main: switches and creates main."""
    checkout = world.new_case("ancestor")
    world.git(checkout, "switch", "-q", "-c", "claude/ancestor")
    world.git(checkout, "branch", "-q", "-D", "main")
    world.land("ancestor", "shared.txt", "v2", "feat: v2 (#2)")
    result = world.run_sync("ancestor")
    assert result.returncode == 0, f"sync should leave a branch that origin/main contains\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main", "sync should switch to main"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("ancestor"), (
        "sync should put main at origin/main"
    )
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/main", (
        "sync should create main tracking origin/main"
    )
    assert world.ref_exists(checkout, "refs/heads/claude/ancestor"), "sync must not delete the old branch"
    assert world.gh_calls() == [], (
        f"sync should not ask gh about a branch that origin/main contains\n{world.read(world.gh_log)}"
    )
    assert "(was on claude/ancestor)" in result.stdout, f"sync should report the previous branch\n{result.stdout}"


def test_sync_leaves_squash_merged_branch_and_carries_edits(world: World) -> None:
    checkout = world.new_case("squash")
    world.git(checkout, "switch", "-q", "-c", "claude/squash")
    (checkout / "feature.txt").write_text("feature\n")
    world.git(checkout, "add", "feature.txt")
    world.git(checkout, "commit", "-qm", "feat: feature")
    squash_tip = world.git(checkout, "rev-parse", "HEAD")
    world.land("squash", "feature.txt", "feature", "feat: feature (#3)")
    world.pr_json("claude/squash", "MERGED", squash_tip)
    with (checkout / "README.md").open("a") as handle:
        handle.write("app edit\n")
    (checkout / "notes.txt").write_text("notes\n")

    result = world.run_sync("squash")
    assert result.returncode == 0, f"sync should leave a squash-merged branch\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main", (
        "sync should switch to main after a squash merge"
    )
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("squash"), (
        "sync should put main at origin/main after a squash merge"
    )
    assert world.git(checkout, "rev-parse", "refs/heads/claude/squash") == squash_tip, (
        "sync must keep the squash-merged branch"
    )
    assert traced(result.stderr, "gh api"), f"sync should echo its gh api to stderr\n{result.stderr}"
    readme_lines = (checkout / "README.md").read_text().splitlines()
    assert readme_lines[-1] == "app edit" and (checkout / "notes.txt").exists(), (
        "sync should carry non-conflicting edits to main"
    )
    assert "uncommitted edits remain; ship or discard them: README.md, notes.txt" in result.stdout, (
        f"sync should report the edits that remain\n{result.stdout}"
    )


def test_sync_leaves_a_squash_merged_branch_when_the_graphql_pr_view_is_blocked(world: World) -> None:
    # Protects: sync works in a Claude Code cloud session, where `gh pr view` (GraphQL) answers HTTP 403.
    # Bug caught: "gh pr view failed (exit 1); cannot tell whether 'claude/cloud' was merged".
    checkout = world.new_case("cloud")
    world.git(checkout, "switch", "-q", "-c", "claude/cloud")
    (checkout / "feature.txt").write_text("feature\n")
    world.git(checkout, "add", "feature.txt")
    world.git(checkout, "commit", "-qm", "feat: feature")
    tip = world.git(checkout, "rev-parse", "HEAD")
    world.land("cloud", "feature.txt", "feature", "feat: feature (#4)")
    world.pr_json("claude/cloud", "MERGED", tip)

    result = world.run_sync("cloud")
    assert result.returncode == 0, f"sync should leave the merged branch without GraphQL\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main", "sync should switch to main"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("cloud"), "sync should fast-forward main"
    assert not any(call[:2] == ["pr", "view"] for call in world.gh_calls()), "sync must not call gh pr view"


@pytest.mark.parametrize(
    ("state", "message"),
    [("OPEN", "has an open PR"), ("CLOSED", "has a closed PR")],
)
def test_sync_refuses_a_branch_whose_pr_is_not_merged(world: World, state: str, message: str) -> None:
    # Protects: the REST state mapping keeps today's refusals (open stays open; closed without merged_at is closed).
    checkout = world.new_case("unmerged")
    world.git(checkout, "switch", "-q", "-c", "claude/unmerged")
    (checkout / "feature.txt").write_text("feature\n")
    world.git(checkout, "add", "feature.txt")
    world.git(checkout, "commit", "-qm", "feat: feature")
    tip = world.git(checkout, "rev-parse", "HEAD")
    world.pr_json("claude/unmerged", state, tip)

    result = world.run_sync("unmerged")
    assert result.returncode != 0, f"sync should refuse a branch with a {state.lower()} PR"
    errors = error_lines(result.stderr)
    assert len(errors) == 1 and message in errors[0], f"sync should name the PR state\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "claude/unmerged", "sync should stay put"


def test_sync_refuses_when_the_pr_lookup_fails(world: World) -> None:
    # Protects: an unreadable PR lookup never counts as "merged".
    checkout = world.new_case("lookup")
    world.git(checkout, "switch", "-q", "-c", "claude/lookup")
    (checkout / "feature.txt").write_text("feature\n")
    world.git(checkout, "add", "feature.txt")
    world.git(checkout, "commit", "-qm", "feat: feature")
    world.fake_gh_fails_api()

    result = world.run_sync("lookup")
    assert result.returncode != 0, "sync should refuse when it cannot read the PR"
    errors = error_lines(result.stderr)
    assert len(errors) == 1 and "cannot tell whether 'claude/lookup' was merged" in errors[0], (
        f"sync should say why\n{result.stderr}"
    )
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "claude/lookup", "sync should stay put"


def test_sync_uses_the_repo_that_contains_the_script_when_home_has_no_dotfiles(world: World, run_tool: RunTool) -> None:
    # Protects: a cloud session clones the repo outside ~/dotfiles, so the tool falls back to its own repo.
    # Bug caught: "dotfiles-pr: dotfiles repo not found: <HOME>/dotfiles".
    checkout = world.new_case("selfrepo")
    script = checkout / "tools" / "dotfiles-pr" / "bin" / "dotfiles-pr"
    script.parent.mkdir(parents=True)
    shutil.copy(TOOL, script)
    world.git(checkout, "add", "tools")
    world.git(checkout, "commit", "-qm", "chore: add tool")
    world.git(checkout, "push", "-q", "origin", "main")
    world.land("selfrepo", "shared.txt", "v2", "chore: change shared")
    assert not (world.iso.home / "dotfiles").exists(), "the test needs a HOME without dotfiles"

    result = run_tool([script, "sync", "--no-prune"], cwd=world.root, DOTFILES_BU_CONFIG=str(world.bu_config))
    assert result.returncode == 0, f"sync should find the repo that holds the script\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("selfrepo"), (
        "sync should fast-forward the repo that holds the script"
    )


def test_an_explicit_missing_dotfiles_dir_still_fails(world: World) -> None:
    # Protects: the script-repo fallback applies only when DOTFILES_DIR is unset.
    missing = world.root / "nowhere"
    result = world.run(world.root, "sync", DOTFILES_DIR=str(missing))
    assert result.returncode != 0, "sync should fail for a missing DOTFILES_DIR"
    assert error_lines(result.stderr) == [f"dotfiles-pr: dotfiles repo not found: {missing}"], result.stderr


def setup_refusal(world: World, name: str, branch: str, state: str | None) -> tuple[Path, str, str]:
    """Put checkout <name> on branch with one commit that origin/main lacks, plus an edit.

    Returns (checkout, tip, status).
    """
    checkout = world.new_case(name)
    world.git(checkout, "switch", "-q", "-c", branch)
    (checkout / "work.txt").write_text("work\n")
    world.git(checkout, "add", "work.txt")
    world.git(checkout, "commit", "-qm", "feat: work")
    tip = world.git(checkout, "rev-parse", "HEAD")
    if state == "OPEN":
        world.pr_json(branch, "OPEN", tip)
    elif state == "MISMATCH":
        world.pr_json(branch, "MERGED", world.git(checkout, "rev-parse", "HEAD~1"))
    with (checkout / "README.md").open("a") as handle:
        handle.write("app edit\n")
    return checkout, tip, world.git(checkout, "status", "--porcelain")


@pytest.mark.parametrize(
    ("name", "branch", "message", "state"),
    [
        ("open-pr", "claude/open-pr", "branch 'claude/open-pr' has an open PR", "OPEN"),
        ("mismatch", "claude/mismatch", "the merged PR for 'claude/mismatch' ended at", "MISMATCH"),
        (
            "no-pr",
            "claude/no-pr",
            "branch 'claude/no-pr' is not in origin/main and has no PR (it has unpushed commits)",
            None,
        ),
    ],
)
def test_sync_refuses_unmerged_branch(world: World, name: str, branch: str, message: str, state: str | None) -> None:
    """Refusals: each leaves branch, HEAD, and uncommitted files as they were."""
    checkout, tip, status = setup_refusal(world, name, branch, state)
    result = world.run_sync(name)
    assert result.returncode != 0, f"sync should refuse ({name})\n{result.stdout}"
    assert f"dotfiles-pr: {message}" in result.stderr, f"sync should explain the {name} refusal\n{result.stderr}"
    assert len(error_lines(result.stderr)) == 1, f"sync should print one error line ({name})\n{result.stderr}"
    world.assert_unchanged(checkout, branch, tip, status, name)
    assert not world.bu_log.exists(), f"a refused sync should not prune ({name})\n{world.read(world.bu_log)}"


def test_start_warns_when_sync_refuses(world: World) -> None:
    """`start` warns about the refused sync but still creates the worktree from origin/main."""
    checkout, _, _ = setup_refusal(world, "open-pr", "claude/open-pr", "OPEN")
    result = world.run(world.root, "start", "after-refusal", DOTFILES_DIR=str(checkout), CLAUDECODE="1")
    assert result.returncode == 0, f"start should succeed when sync refuses\n{result.stderr}"
    new_wt = checkout / ".claude" / "worktrees" / "after-refusal"
    assert last_line(result.stdout) == str(new_wt), f"start should still print the worktree path last\n{result.stdout}"
    warning = (
        "dotfiles-pr: warning: main checkout not synced: "
        "branch 'claude/open-pr' has an open PR; merge or close it first"
    )
    assert warning in result.stderr.splitlines(), f"start should warn in one line when sync refuses\n{result.stderr}"
    assert world.git(new_wt, "rev-parse", "HEAD") == world.origin_main_of("open-pr"), (
        "start should branch from origin/main when sync refuses"
    )
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "claude/open-pr", (
        "start should leave the main checkout on its branch when sync refuses"
    )
    assert not world.bu_log.exists(), f"start should never call bu\n{world.read(world.bu_log)}"


@pytest.mark.parametrize("staged", [False, True], ids=["unstaged", "staged"])
def test_sync_restores_edit_that_origin_main_has(world: World, staged: bool) -> None:
    """A dirty file that already matches origin/main is restored, so the switch and fast-forward succeed.

    The staged case also needs the index restored; otherwise the old content stays in the working tree.
    """
    checkout = world.new_case("restore")
    world.git(checkout, "switch", "-q", "-c", "claude/restore")
    world.land("restore", "shared.txt", "v2", "feat: v2 (#4)")
    (checkout / "shared.txt").write_text("v2\n")
    if staged:
        world.git(checkout, "add", "shared.txt")
    result = world.run_sync("restore")
    assert result.returncode == 0, f"sync should restore an edit that origin/main has\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main", (
        "sync should switch to main after the restore"
    )
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("restore"), (
        "sync should fast-forward after the restore"
    )
    status = world.git(checkout, "status", "--porcelain")
    assert status == "", f"sync should leave no edits after the restore\n{status}"
    assert traced(result.stderr, "git restore"), f"sync should echo its git restore to stderr\n{result.stderr}"
    assert "restored (already in origin/main): shared.txt" in result.stdout, (
        f"sync should report the restored path\n{result.stdout}"
    )


def test_sync_restores_only_the_literal_path(world: World) -> None:
    """Restoring data[1].txt must not touch data1.txt, which the same name matches as a glob pattern."""
    checkout = world.new_case("glob")
    world.land("glob", "data[1].txt", "v1", "feat: data (#6)")
    world.land("glob", "data1.txt", "v1", "feat: more data (#7)")
    world.git(checkout, "pull", "-q", "--ff-only", "origin", "main")
    world.git(checkout, "switch", "-q", "-c", "claude/glob")
    world.land("glob", "data[1].txt", "v2", "feat: data v2 (#8)")
    (checkout / "data[1].txt").write_text("v2\n")
    (checkout / "data1.txt").write_text("my edit\n")

    result = world.run_sync("glob")
    assert result.returncode == 0, f"sync should restore an edit that origin/main has\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("glob"), (
        "sync should fast-forward after the restore"
    )
    assert (checkout / "data[1].txt").read_text() == "v2\n", "sync should bring data[1].txt to origin/main"
    assert (checkout / "data1.txt").read_text() == "my edit\n", (
        "sync should keep the edit in data1.txt; only data[1].txt matched origin/main"
    )
    assert "restored (already in origin/main): data[1].txt" in result.stdout, (
        f"sync should report the restored path\n{result.stdout}"
    )


def test_sync_refuses_conflicting_edit(world: World) -> None:
    """A dirty file that conflicts with main blocks the switch: refuses and names the path."""
    checkout = world.new_case("conflict")
    world.git(checkout, "switch", "-q", "-c", "claude/conflict")
    world.land("conflict", "shared.txt", "v2", "feat: v2 (#5)")
    (checkout / "shared.txt").write_text("app edit\n")
    head = world.git(checkout, "rev-parse", "HEAD")
    status = world.git(checkout, "status", "--porcelain")
    local_main = world.git(checkout, "rev-parse", "refs/heads/main")
    result = world.run_sync("conflict")
    assert result.returncode != 0, f"sync should refuse when an edit conflicts with main\n{result.stdout}"
    assert "dotfiles-pr: cannot switch to main; uncommitted changes conflict in: shared.txt" in result.stderr, (
        f"sync should name the conflicting path\n{result.stderr}"
    )
    world.assert_unchanged(checkout, "claude/conflict", head, status, "conflict")
    assert world.git(checkout, "rev-parse", "refs/heads/main") == local_main, "a blocked switch should not move main"
    assert (checkout / "shared.txt").read_text() == "app edit\n", "a blocked switch should keep the edit"


def test_sync_refuses_diverged_main(world: World) -> None:
    """Local main with commits that origin/main lacks: refuses."""
    checkout = world.new_case("diverged")
    (checkout / "local.txt").write_text("local\n")
    world.git(checkout, "add", "local.txt")
    world.git(checkout, "commit", "-qm", "feat: local only")
    world.land("diverged", "shared.txt", "v2", "feat: v2 (#6)")
    head = world.git(checkout, "rev-parse", "HEAD")
    result = world.run_sync("diverged")
    assert result.returncode != 0, f"sync should refuse a diverged main\n{result.stdout}"
    assert "dotfiles-pr: local main has commits that origin/main lacks" in result.stderr, (
        f"sync should explain the diverged main\n{result.stderr}"
    )
    world.assert_unchanged(checkout, "main", head, "", "diverged")


def test_sync_refuses_detached_head(world: World) -> None:
    checkout = world.new_case("detached")
    world.git(checkout, "switch", "-q", "--detach")
    with (checkout / "README.md").open("a") as handle:
        handle.write("app edit\n")
    head = world.git(checkout, "rev-parse", "HEAD")
    status = world.git(checkout, "status", "--porcelain")
    result = world.run_sync("detached")
    assert result.returncode != 0, f"sync should refuse a detached HEAD\n{result.stdout}"
    assert "detached HEAD" in result.stderr, f"sync should explain the detached HEAD\n{result.stderr}"
    # A detached HEAD has no branch name, so --abbrev-ref prints "HEAD".
    world.assert_unchanged(checkout, "HEAD", head, status, "detached")


def test_sync_refuses_during_cherry_pick(world: World) -> None:
    checkout = world.new_case("picking")
    world.land("picking", "shared.txt", "v2", "feat: v2 (#7)")
    world.git(checkout, "fetch", "-q", "origin")
    world.git(checkout, "switch", "-q", "-c", "claude/picking")
    (checkout / "shared.txt").write_text("v3\n")
    world.git(checkout, "commit", "-qam", "feat: v3")
    subprocess.run(["git", "cherry-pick", "origin/main"], cwd=checkout, env=world.iso.env, capture_output=True)
    picking = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"], cwd=checkout, env=world.iso.env, capture_output=True
    )
    assert picking.returncode == 0, "test setup: expected a cherry-pick in progress"
    head = world.git(checkout, "rev-parse", "HEAD")
    status = world.git(checkout, "status", "--porcelain")
    result = world.run_sync("picking")
    assert result.returncode != 0, f"sync should refuse during a cherry-pick\n{result.stdout}"
    assert "a cherry-pick is in progress" in result.stderr, f"sync should explain the cherry-pick\n{result.stderr}"
    world.assert_unchanged(checkout, "claude/picking", head, status, "picking")
    still_picking = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"], cwd=checkout, env=world.iso.env, capture_output=True
    )
    assert still_picking.returncode == 0, "sync should leave the cherry-pick in progress"


# --- sync: bu prune ----------------------------------------------------------------------
# After the checkout sync, sync runs bu prune from the main checkout. bu output goes to stderr.


def test_sync_prunes_after_main_is_current(world: World) -> None:
    checkout = world.new_case("prune-ok")
    world.land("prune-ok", "shared.txt", "v2", "feat: v2 (#8)")
    result = world.run_sync("prune-ok")
    assert result.returncode == 0, f"sync with bu should succeed\n{result.stderr}"
    assert world.read(world.bu_log) == f"{checkout}\t--config {world.bu_config} prune --color never\n", (
        "sync from outside the repo should run bu --config <cfg> prune --color never once, in the main checkout\n"
        f"{world.read(world.bu_log)}"
    )
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("prune-ok"), (
        "sync should still fast-forward"
    )
    assert world.read(world.bu_head_log).splitlines() == [world.origin_main_of("prune-ok")], (
        f"sync should prune only after main is current (HEAD as bu saw it)\n{world.read(world.bu_head_log)}"
    )
    err_lines = result.stderr.splitlines()
    assert "fake bu: prune report" in err_lines, f"sync should stream bu output to stderr\n{result.stderr}"
    short = world.git(checkout, "rev-parse", "--short", "HEAD")
    assert result.stdout == f"main is at {short} (was on main)\n", (
        f"sync stdout should hold only the summary\n{result.stdout}"
    )

    # From inside a linked worktree, bu runs there, so bu keeps the caller's worktree.
    caller = checkout / ".claude" / "worktrees" / "caller"
    world.git(checkout, "worktree", "add", "-q", "-b", "claude/caller", str(caller), "origin/main")
    world.bu_log.unlink()
    result = world.run(caller, "sync", DOTFILES_DIR=str(checkout))
    assert result.returncode == 0, f"sync from a linked worktree should succeed\n{result.stderr}"
    cwds = [line.split("\t")[0] for line in world.read(world.bu_log).splitlines()]
    assert cwds == [str(caller)], f"sync should run bu in the caller's worktree\n{world.read(world.bu_log)}"


def test_sync_no_prune_skips_bu(world: World) -> None:
    world.new_case("prune-skip")
    result = world.run(world.root, "sync", "--no-prune", DOTFILES_DIR=str(world.root / "prune-skip"))
    assert result.returncode == 0, f"sync --no-prune should succeed\n{result.stderr}"
    assert not world.bu_log.exists(), f"sync --no-prune should not call bu\n{world.read(world.bu_log)}"
    mentions = [line for line in result.stderr.splitlines() if line.startswith("+ bu ") or "bu prune" in line]
    assert not mentions, f"sync --no-prune should not mention bu\n{result.stderr}"


def assert_prune_skipped(result: subprocess.CompletedProcess[str], note: str, what: str) -> None:
    """Sync succeeded, printed one note line, and printed its summary."""
    notes = [line for line in result.stderr.splitlines() if f"dotfiles-pr: note: skipped bu prune: {note}" in line]
    assert len(notes) == 1, f"sync should print one skip note when {what}\n{result.stderr}"
    assert len(error_lines(result.stderr)) == 1, f"sync should print only the note when {what}\n{result.stderr}"
    assert "main is at" in result.stdout, f"sync should still print its summary when {what}\n{result.stdout}"


def test_sync_skips_prune_without_bu(world: World) -> None:
    world.new_case("prune-skip")
    result = world.run_sync("prune-skip", PATH=world.path_without_bu)
    assert result.returncode == 0, f"sync should succeed without bu\n{result.stderr}"
    assert_prune_skipped(result, "bu is not on PATH", "bu is missing")
    assert not world.bu_log.exists(), f"sync should not call bu when it is not on PATH\n{world.read(world.bu_log)}"


def test_sync_skips_prune_without_config(world: World) -> None:
    world.new_case("prune-skip")
    missing = world.root / "missing.toml"
    result = world.run_sync("prune-skip", DOTFILES_BU_CONFIG=str(missing))
    assert result.returncode == 0, f"sync should succeed without a bu config\n{result.stderr}"
    assert_prune_skipped(result, f"config not found: {missing}", "the config is missing")
    assert not world.bu_log.exists(), f"sync should not call bu without a config\n{world.read(world.bu_log)}"


def test_sync_skips_prune_with_old_bu(world: World) -> None:
    world.new_case("prune-skip")
    world.bu_mode.write_text("unknown\n")
    result = world.run_sync("prune-skip")
    assert result.returncode == 0, f"sync should succeed when bu has no prune\n{result.stderr}"
    assert_prune_skipped(result, "the installed bu has no prune command", "bu has no prune")
    assert len(world.read(world.bu_log).splitlines()) == 1, (
        f"sync should call the old bu once\n{world.read(world.bu_log)}"
    )
    assert "unrecognized subcommand" not in result.stderr, (
        f"sync should replace the bu usage error with the note\n{result.stderr}"
    )


def test_sync_reports_failed_prune(world: World) -> None:
    """bu exits non-zero: sync fails with one error line, but the checkout sync stays done."""
    checkout = world.new_case("prune-fail")
    world.land("prune-fail", "shared.txt", "v2", "feat: v2 (#9)")
    world.bu_mode.write_text("fail\n")
    result = world.run_sync("prune-fail")
    assert result.returncode != 0, f"sync should fail when bu prune fails\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("prune-fail"), (
        "a failed prune should keep the completed checkout sync"
    )
    err_lines = result.stderr.splitlines()
    assert "dotfiles-pr: bu prune failed (exit 1); main is synced, but scratch worktrees may remain" in err_lines, (
        f"sync should name the bu failure\n{result.stderr}"
    )
    assert len(error_lines(result.stderr)) == 1, f"sync should print one error line\n{result.stderr}"
    assert "fake bu: removal failed" in err_lines, f"sync should show the bu error output\n{result.stderr}"
    assert "main is at" in result.stdout, f"a failed prune should still report the sync\n{result.stdout}"


# --- sync: Codex config -------------------------------------------------------------------
# Before the checkout moves, sync (and start) turn a ~/.codex/config.toml symlink into the checkout
# into a real file, in-process; if that fails, the checkout does not move. After the move they run
# config/codex/merge_config.py, which reports on stderr and is only a warning when it fails.

# Fake python3: merge_config.py fails like it does on Python < 3.11; anything else (the tool) runs for real.
FAKE_OLD_PYTHON = r"""case "$1" in
  *merge_config.py)
    echo 'merge_config.py: needs Python 3.11+ for tomllib' >&2
    exit 1 ;;
esac
exec "@PYTHON@" "$@"
"""
CONVERTED = "converted ~/.codex/config.toml from a symlink into a real file"
CONVERT_FAILED = "convert ~/.codex/config.toml first: "


def new_codex_case(world: World, name: str, config: str) -> tuple[Path, Path]:
    """A sync case whose origin/main tracks merge_config.py and config/codex/config.toml.

    ~/.codex/config.toml is a legacy symlink to the checkout's config. Returns (checkout, that link).
    """
    checkout = world.new_case(name)
    seed = world.root / f"{name}-seed"
    codex_dir = seed / "config" / "codex"
    codex_dir.mkdir(parents=True)
    shutil.copy(MERGE_SCRIPT, codex_dir / "merge_config.py")
    (codex_dir / "config.toml").write_text(config)
    world.git(seed, "add", "config")
    world.git(seed, "commit", "-qm", "feat: codex config")
    world.git(seed, "push", "-q", "origin", "main")
    world.git(checkout, "pull", "-q", "--ff-only")
    target = world.iso.home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(checkout / "config" / "codex" / "config.toml")
    return checkout, target


def step_order(stderr: str) -> list[str]:
    """The Codex conversion, checkout move, and merge steps, in the order sync ran them."""
    steps = {CONVERTED: "convert", "+ git merge --ff-only": "move", "+ python3": "merge"}
    return [step for line in stderr.splitlines() for prefix, step in steps.items() if line.startswith(prefix)]


def test_sync_converts_codex_link_before_the_move_and_merges_after(world: World) -> None:
    checkout, target = new_codex_case(world, "codex", 'notify = ["app"]\nmodel = "a"\n')
    linked = checkout / "config" / "codex" / "config.toml"
    linked.chmod(0o600)
    # The merged PR drops the app-written notify key and changes the model.
    world.land("codex", "config/codex/config.toml", 'model = "b"', "fix: strip app keys (#9)")

    result = world.run_sync("codex")

    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("codex"), "sync should fast-forward"
    assert not target.is_symlink(), "sync should turn the legacy Codex config symlink into a real file"
    text = target.read_text()
    assert 'notify = ["app"]' in text, f"the pre-move conversion should keep the app-written key\n{text}"
    assert 'model = "b"' in text, f"the merge after the move should apply the tracked change\n{text}"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600, "the converted file should keep the linked file's mode"
    backup = Path(f"{target}.bak")
    assert backup.is_file() and not backup.is_symlink(), "the link should be backed up as a content copy"
    assert backup.read_text() == 'notify = ["app"]\nmodel = "a"\n', "the backup should hold the pre-move contents"
    assert step_order(result.stderr) == ["convert", "move", "merge"], (
        f"sync should convert, then move, then merge\n{result.stderr}"
    )
    assert '  Codex config drift: model: "a" -> "b" (tracked value wins)' in result.stderr.splitlines(), (
        f"sync should pass the merge report through to stderr\n{result.stderr}"
    )
    assert error_lines(result.stderr) == [], f"a working merge should not warn\n{result.stderr}"
    short = world.git(checkout, "rev-parse", "--short", "HEAD")
    assert result.stdout == f"main is at {short} (was on main)\n", (
        f"stdout should hold only the summary\n{result.stdout}"
    )


# Protects: sync merges the work overlay's Codex keys as install.sh does, so they survive every sync.
# Bug caught: sync merges only the public base. Its recorded base then lacks the work project, and the work
# project that install.sh added is removed on the next sync.
def test_sync_merges_the_work_overlay_codex_keys(world: World) -> None:
    checkout, target = new_codex_case(world, "codex-work", 'model = "a"\n')
    overlay = world.root / "work-overlay"
    (overlay / "config" / "codex").mkdir(parents=True)
    (overlay / "config" / "codex" / "config.toml").write_text('[projects."/work/repo"]\ntrust_level = "trusted"\n')

    first = world.run_sync("codex-work", DOTFILES_WORK_DIR=str(overlay))
    second = world.run_sync("codex-work", DOTFILES_WORK_DIR=str(overlay))

    for result in (first, second):
        assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
        assert error_lines(result.stderr) == [], f"a working merge should not warn\n{result.stderr}"
    merged = tomllib.loads(target.read_text())
    assert merged["projects"]["/work/repo"] == {"trust_level": "trusted"}, "sync should keep the overlay's project"
    assert merged["model"] == "a"
    assert "Codex config removed" not in second.stderr, second.stderr

    without = world.run_sync("codex-work", DOTFILES_WORK_DIR=str(world.root / "no-overlay"))

    assert without.returncode == 0, f"sync should succeed\n{without.stderr}"
    assert "projects" not in tomllib.loads(target.read_text()), "without the overlay, its keys should go"


def test_sync_recovers_app_keys_that_an_old_sync_already_stripped(world: World) -> None:
    """An old dotfiles-pr pulled the strip, so the link already resolves to the stripped file."""
    checkout, target = new_codex_case(world, "codex-late", 'notify = ["app"]\nmodel = "a"\n')
    world.land("codex-late", "config/codex/config.toml", 'model = "a"', "fix: strip app keys (#12)")
    world.git(checkout, "pull", "-q", "--ff-only")  # What the old sync did.
    world.land("codex-late", "config/codex/config.toml", 'model = "b"', "feat: model b (#13)")

    result = world.run_sync("codex-late")

    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    text = target.read_text()
    assert 'notify = ["app"]' in text, f"the merge should recover notify from before the strip commit\n{text}"
    assert 'model = "b"' in text, f"the tracked change after the strip should still win\n{text}"
    assert not Path(f"{target}.dotfiles-legacy-link").exists(), "a merge should consume the conversion record"
    assert error_lines(result.stderr) == [], f"a working merge should not warn\n{result.stderr}"


def test_start_converts_codex_link_before_the_move_and_merges_after(world: World) -> None:
    checkout, target = new_codex_case(world, "codex-start", 'notify = ["app"]\nmodel = "a"\n')
    world.land("codex-start", "config/codex/config.toml", 'model = "b"', "fix: strip app keys (#11)")

    result = world.run(world.root, "start", "next-change", DOTFILES_DIR=str(checkout))

    assert result.returncode == 0, f"start should succeed\n{result.stderr}"
    assert last_line(result.stdout) == str(checkout / ".claude" / "worktrees" / "next-change"), (
        f"start should still print the worktree path last\n{result.stdout}"
    )
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("codex-start"), "start should sync main"
    assert not target.is_symlink(), "start should turn the legacy Codex config symlink into a real file"
    text = target.read_text()
    assert 'notify = ["app"]' in text, f"the pre-move conversion should keep the app-written key\n{text}"
    assert 'model = "b"' in text, f"the merge after the move should apply the tracked change\n{text}"
    assert step_order(result.stderr) == ["convert", "move", "merge"], (
        f"start should convert, then move, then merge\n{result.stderr}"
    )
    assert error_lines(result.stderr) == [], f"a working merge should not warn\n{result.stderr}"


@pytest.mark.parametrize("command", ["sync", "start"])
def test_a_failed_codex_conversion_keeps_main_and_the_link(world: World, command: str) -> None:
    """~/.codex cannot take the conversion's writes, so it fails: main must not move and the link must stay."""
    checkout, target = new_codex_case(world, f"codex-ro-{command}", 'notify = ["app"]\nmodel = "a"\n')
    link_source = os.readlink(target)
    world.land(f"codex-ro-{command}", "config/codex/config.toml", 'model = "b"', "fix: strip app keys (#14)")
    head = world.git(checkout, "rev-parse", "HEAD")
    # Root ignores the read-only mode, so a directory at the record path also makes the conversion fail.
    Path(f"{target}.dotfiles-legacy-link").mkdir()
    target.parent.chmod(0o555)
    try:
        args = ["sync"] if command == "sync" else ["start", "ro-change"]
        result = world.run(world.root, *args, DOTFILES_DIR=str(checkout))
    finally:
        target.parent.chmod(0o755)

    assert world.git(checkout, "rev-parse", "HEAD") == head, f"{command} must not move main when conversion fails"
    assert target.is_symlink() and os.readlink(target) == link_source, f"{command} should leave the link intact"
    assert not world.bu_log.exists(), f"{command} should not prune after a failed conversion"
    [error] = error_lines(result.stderr)
    if command == "sync":
        assert result.returncode != 0, f"sync should fail when the conversion fails\n{result.stderr}"
        assert error.startswith(f"dotfiles-pr: {CONVERT_FAILED}"), f"sync should say why\n{result.stderr}"
    else:
        assert result.returncode == 0, f"start should still create the worktree\n{result.stderr}"
        assert error.startswith(f"dotfiles-pr: warning: main checkout not synced: {CONVERT_FAILED}"), (
            f"start should warn in one line\n{result.stderr}"
        )
        assert (checkout / ".claude" / "worktrees" / "ro-change").is_dir(), "start should still create the worktree"


# Fake git: the conversion's `git rev-parse HEAD` runs between its read of the linked file and the final
# link replacement, so a one-shot write there stands in for the Codex app writing through the link.
FAKE_GIT_APP_WRITE = r"""if [[ "$*" == 'rev-parse HEAD' && -e "@MARKER@" ]]; then
  rm "@MARKER@"
  printf 'app_key = "set by the app"\n' >>"@RESOLVED@"
fi
exec "@GIT@" "$@"
"""


def test_sync_refuses_when_codex_writes_during_the_conversion(world: World, fake_exe: Callable[..., Path]) -> None:
    checkout, target = new_codex_case(world, "codex-race", 'notify = ["app"]\nmodel = "a"\n')
    resolved = checkout / "config" / "codex" / "config.toml"
    world.land("codex-race", "config/codex/config.toml", 'model = "b"', "fix: strip app keys (#15)")
    head = world.git(checkout, "rev-parse", "HEAD")
    marker = world.root / "app-write-pending"
    real_git = shutil.which("git")
    assert real_git, "the tests need git on PATH"
    fake_exe("git", fill(FAKE_GIT_APP_WRITE, MARKER=marker, RESOLVED=resolved, GIT=real_git))
    marker.touch()

    result = world.run_sync("codex-race")

    assert not marker.exists(), f"the simulated app write should have run\n{result.stderr}"
    assert result.returncode != 0, f"sync should fail when Codex writes during the conversion\n{result.stderr}"
    assert error_lines(result.stderr) == [
        f"dotfiles-pr: {CONVERT_FAILED}Codex wrote the config during conversion; re-run"
    ], f"sync should say why in one line\n{result.stderr}"
    assert target.is_symlink() and os.readlink(target) == str(resolved), "the link should stay intact"
    assert resolved.read_text().endswith('app_key = "set by the app"\n'), "the app's write should be kept"
    assert not Path(f"{target}.dotfiles-legacy-link").exists(), "no stale conversion record should be left"
    assert world.git(checkout, "rev-parse", "HEAD") == head, "sync must not move main"


def test_codex_conversion_needs_no_new_python_but_the_merge_warns(world: World, fake_exe: Callable[..., Path]) -> None:
    checkout, target = new_codex_case(world, "codex-old", 'notify = ["app"]\nmodel = "a"\n')
    world.land("codex-old", "config/codex/config.toml", 'model = "b"', "fix: strip app keys (#10)")
    fake_exe("python3", fill(FAKE_OLD_PYTHON, PYTHON=sys.executable))

    result = world.run_sync("codex-old")

    assert result.returncode == 0, f"a failed Codex merge should not fail sync\n{result.stderr}"
    assert world.git(checkout, "rev-parse", "HEAD") == world.origin_main_of("codex-old"), (
        "the checkout sync should still happen"
    )
    assert not target.is_symlink(), "the conversion should succeed without python3 3.11+"
    assert target.read_text() == 'notify = ["app"]\nmodel = "a"\n', "the conversion should keep the pre-move bytes"
    reason = "merge_config.py: needs Python 3.11+ for tomllib; fix it, then run install.sh"
    assert error_lines(result.stderr) == [f"dotfiles-pr: warning: Codex config not merged: {reason}"], (
        f"only the merge should warn\n{result.stderr}"
    )
    assert Path(f"{target}.dotfiles-legacy-link").is_file(), "the record should wait for a merge that succeeds"
    assert "main is at" in result.stdout, f"sync should still print its summary\n{result.stdout}"


def test_sync_skips_the_codex_merge_without_the_script(world: World) -> None:
    world.new_case("no-codex")
    result = world.run_sync("no-codex")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert "+ python3" not in result.stderr, f"a checkout without merge_config.py has nothing to merge\n{result.stderr}"
    assert not (world.iso.home / ".codex").exists(), "sync should not create a Codex config without the script"


# --- sync: skill links ---------------------------------------------------------------------------


def test_sync_links_the_skills_into_home(world: World) -> None:
    checkout = world.new_case("skills")
    seed = world.root / "skills-seed"
    (seed / "skills" / "zoom-out").mkdir(parents=True)
    (seed / "skills" / "zoom-out" / "SKILL.md").write_text("v1\n")
    (seed / "scripts").mkdir()
    shutil.copy(LINK_SCRIPT, seed / "scripts" / "link_skills.py")
    world.git(seed, "add", "skills", "scripts")
    world.git(seed, "commit", "-qm", "feat: a skill")
    world.git(seed, "push", "-q", "origin", "main")
    result = world.run_sync("skills")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    link = world.iso.home / ".agents" / "skills" / "zoom-out"
    assert link.is_symlink(), "sync should link the skill into ~/.agents/skills"
    assert link.resolve() == (checkout / "skills" / "zoom-out").resolve()
    assert (world.iso.home / ".claude" / "skills" / "zoom-out" / "SKILL.md").read_text() == "v1\n"
    assert "main is at" in result.stdout, f"sync should still print its summary\n{result.stdout}"


def test_sync_skips_the_skill_links_without_the_script(world: World) -> None:
    world.new_case("no-links")
    result = world.run_sync("no-links")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert "link_skills.py" not in result.stderr, f"a checkout without the script has nothing to link\n{result.stderr}"
    assert not (world.iso.home / ".agents").exists(), "sync should not create ~/.agents without the script"


# --- sync: global guidance links ------------------------------------------------------------

GLOBAL_RULES_TEXT = "# Global rules\n"
GUIDANCE_LINKS = (".claude/CLAUDE.md", ".codex/AGENTS.md")


def land_global_rules(world: World, name: str) -> Path:
    """Commit agents/global.md on origin/main; returns the path it has in the case checkout."""
    seed = world.root / f"{name}-seed"
    (seed / "agents").mkdir(parents=True)
    (seed / "agents" / "global.md").write_text(GLOBAL_RULES_TEXT)
    world.git(seed, "add", "agents")
    world.git(seed, "commit", "-qm", "refactor(agents): split the global rules")
    world.git(seed, "push", "-q", "origin", "main")
    return world.root / name / "agents" / "global.md"


# Protects: after the global rules moved from the root AGENTS.md to agents/global.md, the post-merge sync points
# the existing global guidance links at the new file. Bug caught: sync refreshed only the checkout, so on an
# installed machine ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md kept loading the dotfiles-only root AGENTS.md.
def test_sync_relinks_global_guidance_from_the_root_agents_file(world: World) -> None:
    world.new_case("guidance-moved")
    source = land_global_rules(world, "guidance-moved")
    for name in GUIDANCE_LINKS:
        link = world.iso.home / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(world.root / "guidance-moved" / "AGENTS.md")
    result = world.run_sync("guidance-moved")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    for name in GUIDANCE_LINKS:
        link = world.iso.home / name
        assert link.is_symlink() and link.resolve() == source.resolve(), f"sync should point {name} at global.md"
        assert link.read_text() == GLOBAL_RULES_TEXT


# Protects: sync replaces only a link to the old root AGENTS.md. A real file or a link the owner points elsewhere
# stays. Bug caught: a migration that overwrites any CLAUDE.md, which deletes machine-local guidance.
def test_sync_leaves_other_global_guidance_alone(world: World) -> None:
    world.new_case("guidance-keep")
    land_global_rules(world, "guidance-keep")
    real = world.iso.home / ".claude" / "CLAUDE.md"
    real.parent.mkdir(parents=True)
    real.write_text("machine guidance\n")
    elsewhere = world.root / "my-agents.md"
    elsewhere.write_text("mine\n")
    other = world.iso.home / ".codex" / "AGENTS.md"
    other.parent.mkdir(parents=True)
    other.symlink_to(elsewhere)
    result = world.run_sync("guidance-keep")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert not real.is_symlink() and real.read_text() == "machine guidance\n", "sync must not replace a real file"
    assert other.is_symlink() and os.readlink(other) == str(elsewhere), "sync must keep a link the owner set"


# Protects: a checkout from before the split keeps its links. Bug caught: a link repointed at a missing file.
def test_sync_keeps_the_root_agents_link_without_global_rules(world: World) -> None:
    world.new_case("guidance-old")
    link = world.iso.home / ".claude" / "CLAUDE.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(world.root / "guidance-old" / "AGENTS.md")
    result = world.run_sync("guidance-old")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert link.is_symlink() and os.readlink(link) == str(world.root / "guidance-old" / "AGENTS.md")


# --- sync: guard hook ----------------------------------------------------------------------------


# Protects: a merged guard hook goes live through the sync loop, without a new install.sh run.
# Bug caught: sync skips install_hooks.py, so Claude Code and Codex keep running without the merge guard.
def test_sync_registers_the_guard_hook(world: World) -> None:
    checkout = world.new_case("hooks")
    seed = world.root / "hooks-seed"
    shutil.copytree(
        REPO_ROOT / "config" / "agent-hooks",
        seed / "config" / "agent-hooks",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    world.git(seed, "add", "config")
    world.git(seed, "commit", "-qm", "feat: guard hook")
    world.git(seed, "push", "-q", "origin", "main")
    result = world.run_sync("hooks")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    expected = f"python3 {checkout / 'config' / 'agent-hooks' / 'guard_irreversible.py'}"
    for target in (".claude/settings.json", ".codex/hooks.json"):
        settings = json.loads((world.iso.home / target).read_text())
        commands = [hook["command"] for group in settings["hooks"]["PreToolUse"] for hook in group["hooks"]]
        assert commands == [expected], f"sync should register the guard hook in {target}"
    assert "main is at" in result.stdout, f"sync should still print its summary\n{result.stdout}"


# --- sync: ro -----------------------------------------------------------------------------

RO_REVIEWERS = '{"reviewers": []}\n'


def land_reviewers(world: World, name: str) -> Path:
    """Commit config/review-pr/reviewers.json on origin/main; returns the path it has in the case checkout."""
    seed = world.root / f"{name}-seed"
    (seed / "config" / "review-pr").mkdir(parents=True)
    (seed / "config" / "review-pr" / "reviewers.json").write_text(RO_REVIEWERS)
    world.git(seed, "add", "config")
    world.git(seed, "commit", "-qm", "feat: reviewers")
    world.git(seed, "push", "-q", "origin", "main")
    return world.root / name / "config" / "review-pr" / "reviewers.json"


# Protects: sync no longer installs or runs ro, even when the checkout still pins it.
# Bug caught: a leftover `uv tool install` of ro, or a leftover `ro record install`, in sync.
def test_sync_neither_installs_nor_runs_ro(world: World) -> None:
    world.new_case("ro-none")
    world.land(
        "ro-none",
        "pyproject.toml",
        f'[tool.uv.sources]\nro = {{ git = "https://github.com/sucramual/ro", rev = "{"a" * 40}" }}',
        "chore(ro): pin",
    )
    result = world.run_sync("ro-none")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert "main is at" in result.stdout, f"sync should print its summary\n{result.stdout}"
    assert not (world.iso.home / "uv.log").exists(), "sync should run no uv command"
    assert not (world.iso.home / "ro.log").exists(), "sync should not run ro"


def test_sync_links_the_ro_reviewers_config(world: World) -> None:
    world.new_case("ro-link")
    source = land_reviewers(world, "ro-link")
    result = world.run_sync("ro-link")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    link = world.iso.home / ".config" / "review-pr" / "reviewers.json"
    assert link.is_symlink(), "sync should link the reviewers config"
    assert link.resolve() == source.resolve()
    assert link.read_text() == RO_REVIEWERS


def test_sync_honours_an_absolute_xdg_config_home(world: World) -> None:
    world.new_case("ro-xdg")
    source = land_reviewers(world, "ro-xdg")
    xdg = world.root / "xdg"
    result = world.run_sync("ro-xdg", XDG_CONFIG_HOME=str(xdg))
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert (xdg / "review-pr" / "reviewers.json").resolve() == source.resolve()
    assert not (world.iso.home / ".config" / "review-pr").exists(), "sync should use XDG_CONFIG_HOME, not ~/.config"


def test_sync_ignores_a_relative_xdg_config_home(world: World) -> None:
    world.new_case("ro-xdg-rel")
    source = land_reviewers(world, "ro-xdg-rel")
    result = world.run_sync("ro-xdg-rel", XDG_CONFIG_HOME="relative/dir")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert (world.iso.home / ".config" / "review-pr" / "reviewers.json").resolve() == source.resolve()


def test_sync_leaves_a_different_reviewers_file_alone(world: World) -> None:
    world.new_case("ro-keep")
    land_reviewers(world, "ro-keep")
    target = world.iso.home / ".config" / "review-pr" / "reviewers.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"reviewers": ["mine"]}\n')
    result = world.run_sync("ro-keep")
    assert result.returncode == 0, f"a different reviewers file should not fail sync\n{result.stderr}"
    assert not target.is_symlink(), "sync must not replace the existing file"
    assert target.read_text() == '{"reviewers": ["mine"]}\n', "sync must not change the existing file"
    warnings = [line for line in error_lines(result.stderr) if "reviewers.json" in line]
    assert len(warnings) == 1 and "warning" in warnings[0], f"sync should warn about the file\n{result.stderr}"


# Protects: a link that points at a path the reviewers file had before it moved is pointed at config/review-pr.
# Bug caught: config/siula/reviewers.json, then config/rogue-one/reviewers.json, then config/ro/reviewers.json moved to
# config/review-pr. With "ro", the link sits at the new target path but points at config/ro. Sync left the
# old link alone as "a different file", so the ready check read no reviewers and every review ended with a gap.
@pytest.mark.parametrize("old_folder", ["siula", "rogue-one", "ro"])
def test_sync_relinks_a_reviewers_link_to_an_old_repo_path(world: World, old_folder: str) -> None:
    case = f"ro-moved-{old_folder}"
    world.new_case(case)
    source = land_reviewers(world, case)
    target = world.iso.home / ".config" / "review-pr" / "reviewers.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(source.parent.parent / old_folder / "reviewers.json")
    result = world.run_sync(case)
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert target.is_symlink() and target.resolve() == source.resolve(), "sync should point the link at the new path"
    assert target.read_text() == RO_REVIEWERS
    assert not [line for line in error_lines(result.stderr) if "reviewers.json" in line], result.stderr


# Protects: sync replaces only a link to an old repo path. A link that the owner points elsewhere stays.
# Bug caught: a relink that matches any link, or any path that ends in reviewers.json, overwrites the owner's own list.
def test_sync_leaves_a_reviewers_link_to_another_path_alone(world: World) -> None:
    world.new_case("ro-other-link")
    land_reviewers(world, "ro-other-link")
    mine = world.root / "my-reviewers.json"
    mine.write_text('{"reviewers": ["mine"]}\n')
    target = world.iso.home / ".config" / "review-pr" / "reviewers.json"
    target.parent.mkdir(parents=True)
    target.symlink_to(mine)
    result = world.run_sync("ro-other-link")
    assert result.returncode == 0, f"another link should not fail sync\n{result.stderr}"
    assert target.is_symlink() and Path(os.readlink(target)) == mine, "sync must not replace the owner's link"
    warnings = [line for line in error_lines(result.stderr) if "reviewers.json" in line]
    assert len(warnings) == 1 and "warning" in warnings[0], f"sync should warn about the link\n{result.stderr}"


# Protects: sync creates the new review-pr link and does not delete the link that an older sync made under rogue-one.
# Bug caught: sync keeps linking only ~/.config/rogue-one, which ro no longer reads, or it deletes the owner's files.
def test_sync_links_ro_and_keeps_the_old_rogue_one_link(world: World) -> None:
    world.new_case("ro-keep-old")
    source = land_reviewers(world, "ro-keep-old")
    old_link = world.iso.home / ".config" / "rogue-one" / "reviewers.json"
    old_link.parent.mkdir(parents=True)
    old_link.symlink_to(source.parent.parent / "rogue-one" / "reviewers.json")
    result = world.run_sync("ro-keep-old")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    link = world.iso.home / ".config" / "review-pr" / "reviewers.json"
    assert link.is_symlink() and link.resolve() == source.resolve(), "sync should link the review-pr path"
    assert old_link.is_symlink(), "sync should leave the old ~/.config/rogue-one link alone"


def test_sync_without_the_reviewers_source_links_nothing(world: World) -> None:
    world.new_case("ro-old")
    result = world.run_sync("ro-old")
    assert result.returncode == 0, f"sync should succeed\n{result.stderr}"
    assert not (world.iso.home / ".config" / "review-pr").exists(), "an older checkout has no reviewers config to link"
