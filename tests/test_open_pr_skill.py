"""Checks that skills/open-pr/SKILL.md keeps its key phrases, in the required order."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib

import pytest
from conftest import REPO_ROOT
from skill_text import assert_before, assert_contains, assert_not_contains, first_line_of, read_lines

SKILL = REPO_ROOT / "skills" / "open-pr" / "SKILL.md"
REFS = REPO_ROOT / "skills" / "open-pr" / "references"
SPACELIFT = REFS / "spacelift.md"
CHANGE_MAP = REFS / "change-map.md"
DOTFILES_REF = REFS / "dotfiles.md"
STACK = REFS / "stack.md"
# open-pr runs these publish steps, vendored from ro's ro-publish skill, with the changes in SKILL.md.
PUBLISH_STEPS = REFS / "publish-steps.md"

# Text that moved out of SKILL.md so that a single-PR run does not read it. The assertion follows the text.
_SPACELIFT_NEEDLES = (
    "# Spacelift PRs",
    "The repo's own guidance",
    "`auto_archive_on_close: false`",
    "Record the head SHA that `review-pr` saw as green and approved",
    "Never pass `--auto`",
    "Enqueue only with GraphQL",
    "If the mutation fails, do not merge another way and do not retry with a different command",
    "Report the error to Marcus and stop",
    "`isMergeQueueEnabled` is false",
    "Use the same GraphQL call with the new reviewed head SHA",
    "`enqueuePullRequest(input:{pullRequestId, expectedHeadOid})`",
    "If the head changed, do not merge",
    "If GitHub removes the PR from the queue",
    "Enqueue again only under the item 2 conditions",
    "Never wait without a limit",
    "Return the Spacelift run URL of every affected stack, then stop",
    "Do not enqueue the PR. Item 2 needs a head that `review-pr` saw as green and approved",
    "If the repo has no Spacelift guidance, stop and ask Marcus",
    "If a plan shows changes beyond the PR's stated intent, do not enqueue",
    "Do not retry it, confirm it, deploy the stack, or start another run",
    "Do not relay the confirmation to a worker",
    "Never approve your own PR",
    "Never enable repo-level auto-merge",
    "Never run `spacectl stack deploy`, `confirm`, or `discard`",
    "`### After the apply`",
    "relay the confirm link to Marcus at once",
)
_CHANGE_MAP_NEEDLES = (
    "### Change map",
    "`classDef`",
    "dashed node",
    "Request flow",
    "Keep bot-added footers",
    "run `<skill-dir>/scripts/check-mermaid.sh <file>`",
)
# Steps 2-4 and the step 6 map rule live in the publish steps. The assertion follows the text.
_PUBLISH_NEEDLES = (
    "Inspect `git status --short`, `git diff`, and `git diff --cached`",
    "Build the intended file list from the user's request, the current task context, and the changes made"
    " during this session",
    "If any changed or already-staged path may be unrelated or its ownership is unclear, stop and ask",
    "Stage each intended file path explicitly with `git add -- <path>...`",
    "Never use `git add .`, `git add -A`, `git add --all`, or stage a directory",
    "Verify that `git diff --cached --name-only` exactly matches the intended file list",
    "Inspect `git diff --cached`, and stop before committing if it contains unintended content",
    "LOCAL_HEAD_BEFORE_REBASE=$(git rev-parse HEAD)",
    'git merge-base --is-ancestor "$REMOTE_BRANCH_BEFORE_REBASE" "$LOCAL_HEAD_BEFORE_REBASE"',
    "touches two or more packages or services",
    "adds or moves a seam",
    "Skip the map for",
    "pure refactor with an unchanged call graph",
)
_NEEDLE_FILES = {
    **dict.fromkeys(_SPACELIFT_NEEDLES, SPACELIFT),
    **dict.fromkeys(_CHANGE_MAP_NEEDLES, CHANGE_MAP),
    **dict.fromkeys(_PUBLISH_NEEDLES, PUBLISH_STEPS),
    "is one layer of a stack": STACK,
}


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        (
            "description: Publish ready local changes as a GitHub pull request",
            "skill description should state its publication capability",
        ),
        (
            "Use when asked to open, create, publish, or send a PR",
            "skill description should include natural trigger phrases",
        ),
        (
            "Inspect `git status --short`, `git diff`, and `git diff --cached`",
            "skill should inspect staged and unstaged changes before staging",
        ),
        (
            "Build the intended file list from the user's request, the current task context, and the changes made"
            " during this session",
            "skill should infer the intended file set from task context",
        ),
        (
            "If any changed or already-staged path may be unrelated or its ownership is unclear, stop and ask",
            "skill should stop when file ownership is ambiguous",
        ),
        (
            "Stage each intended file path explicitly with `git add -- <path>...`",
            "skill should stage named files only",
        ),
        (
            "Never use `git add .`, `git add -A`, `git add --all`, or stage a directory",
            "skill should forbid broad staging commands",
        ),
        (
            "Verify that `git diff --cached --name-only` exactly matches the intended file list",
            "skill should verify the cached path set before committing",
        ),
        (
            "Inspect `git diff --cached`, and stop before committing if it contains unintended content",
            "skill should inspect the exact proposed commit",
        ),
        (
            "LOCAL_HEAD_BEFORE_REBASE=$(git rev-parse HEAD)",
            "skill should capture the local tip before rebasing",
        ),
        (
            'git merge-base --is-ancestor "$REMOTE_BRANCH_BEFORE_REBASE" "$LOCAL_HEAD_BEFORE_REBASE"',
            "skill should reject remote-only commits before rebasing",
        ),
        ("isolated worktree or checkout", "background mutation should require an isolated checkout"),
        ("pinned to the exact PR branch and head SHA", "background follow-up should pin the PR state"),
        ("invoke the installed `review-pr` skill", "background follow-up should select review-pr explicitly"),
        ("Do not substitute `/age` or `/affinage`", "background follow-up should not start a fresh review"),
        ("If isolation, a background agent facility", "skill should skip unsafe background follow-up explicitly"),
        (
            "resolve the installed skill directory from this `SKILL.md`",
            "skill should resolve its bundled generator when the repository has none",
        ),
        ("Only if neither generator is available", "manual PR-body generation should be the last fallback"),
        ("**Add a change map only when the change needs one.**", "skill should make the change map conditional"),
        ("### Change map", "the change map section should use the agreed heading"),
        ("touches two or more packages or services", "a multi-package change should get a change map"),
        ("adds or moves a seam", "a new or moved seam should get a change map"),
        ("is one layer of a stack", "a stack layer should get a change map"),
        ("Skip the map for", "skill should name the changes that need no map"),
        ("pure refactor with an unchanged call graph", "an unchanged call graph should need no map"),
        ("`classDef`", "the map should colour-code nodes with classDef"),
        ("dashed node", "the map should mark follow-up work with a dashed node"),
        ("Request flow", "the optional second diagram should use the agreed name"),
        ("Keep bot-added footers", "editing an existing body should keep bot footers"),
        ("run `<skill-dir>/scripts/check-mermaid.sh <file>`", "skill should validate Mermaid before publishing"),
        ("# Spacelift PRs", "skill should have a conditional Spacelift reference"),
        ("The repo's own guidance", "skill should defer Spacelift paths and steps to the repo"),
        ("`auto_archive_on_close: false`", "skill should keep the desktop session alive past the merge"),
        ("Record the head SHA that `review-pr` saw as green and approved", "skill should record the reviewed head"),
        ("Never pass `--auto`", "skill should forbid the --auto flag"),
        ("Enqueue only with GraphQL", "skill should enqueue only through GraphQL"),
        (
            "If the mutation fails, do not merge another way and do not retry with a different command",
            "skill should not fall back to another merge path",
        ),
        ("Report the error to Marcus and stop", "skill should stop and report when the enqueue fails"),
        ("`isMergeQueueEnabled` is false", "skill should stop when the branch has no merge queue"),
        ("Use the same GraphQL call with the new reviewed head SHA", "re-enqueue should reuse the pinned GraphQL call"),
        (
            "`enqueuePullRequest(input:{pullRequestId, expectedHeadOid})`",
            "skill should enqueue through GraphQL pinned to the reviewed head",
        ),
        ("If the head changed, do not merge", "skill should send a moved head back through review"),
        ("If GitHub removes the PR from the queue", "skill should handle merge-queue removal"),
        ("Enqueue again only under the item 2 conditions", "skill should re-enqueue only under the same conditions"),
        ("Never wait without a limit", "skill should bound the merge wait"),
        (
            "Return the Spacelift run URL of every affected stack, then stop",
            "the background agent should stop at the run URLs",
        ),
        (
            "Do not enqueue the PR. Item 2 needs a head that `review-pr` saw as green and approved",
            "the parent should not enqueue a PR that no review-pr run approved",
        ),
        (
            "If the repo has no Spacelift guidance, stop and ask Marcus",
            "skill should not guess Spacelift post-merge steps when the repo has no guidance",
        ),
        (
            "If a plan shows changes beyond the PR's stated intent, do not enqueue",
            "skill should not enqueue a PR whose plan exceeds its intent",
        ),
        (
            "Do not retry it, confirm it, deploy the stack, or start another run",
            "a failed, discarded, or canceled run should stay a decision for Marcus",
        ),
        ("Do not relay the confirmation to a worker", "the parent should own the post-confirm phase"),
        ("Never approve your own PR", "skill should forbid self-approval"),
        ("Never enable repo-level auto-merge", "skill should forbid repo-level auto-merge"),
        ("Never run `spacectl stack deploy`, `confirm`, or `discard`", "skill should keep the confirm step human"),
        ("`### After the apply`", "skill should run the PR's post-apply checks"),
        ("relay the confirm link to Marcus at once", "parent should relay the confirm link at once"),
    ],
)
def test_contains(needle: str, message: str) -> None:
    assert_contains(_NEEDLE_FILES.get(needle, SKILL), needle, message)


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        (
            "Inspect `git status --short`, `git diff`, and `git diff --cached`",
            "**Rebase onto the default branch**",
            "staging inspection should happen before rebasing",
        ),
        (
            "Verify that `git diff --cached --name-only` exactly matches the intended file list",
            "**Rebase onto the default branch**",
            "cached path verification should happen before rebasing",
        ),
        (
            'git merge-base --is-ancestor "$REMOTE_BRANCH_BEFORE_REBASE" "$LOCAL_HEAD_BEFORE_REBASE"',
            'git rebase "origin/${DEFAULT_BRANCH}"',
            "remote ancestry guard should run before rebasing",
        ),
        (
            "If `./scripts/generate-pr-description.sh` exists",
            "resolve the installed skill directory from this `SKILL.md`",
            "repository-local generator should take precedence over the bundled fallback",
        ),
        (
            "resolve the installed skill directory from this `SKILL.md`",
            "Only if neither generator is available",
            "bundled generator should take precedence over manual generation",
        ),
        (
            "Only if neither generator is available",
            "**Add a change map only when the change needs one.**",
            "the change map should be added to the generated description",
        ),
        (
            "references/change-map.md",
            'gh pr create --base "$DEFAULT_BRANCH"',
            "the change map reference should be read before the PR is created",
        ),
        (
            'gh pr create --base "$DEFAULT_BRANCH"',
            "references/spacelift.md",
            "the Spacelift reference should be read from the PR creation step",
        ),
    ],
)
def test_order(first: str, second: str, message: str) -> None:
    assert_before(PUBLISH_STEPS if first in _PUBLISH_NEEDLES else SKILL, first, second, message)


def test_does_not_use_topology() -> None:
    assert_not_contains(SKILL, "topology", "the retired /plate skill used 'topology' for PR layout; keep the word out")


LEAK_CHECK = REPO_ROOT / "scripts" / "check_leaks.py"


def test_is_repo_agnostic() -> None:
    # Bug caught: employer-specific text in the skill or its references, in any letter case, instead of the overlay.
    # The deny list is private, so scripts/check_leaks.py reads it from the overlay or the CI secret.
    paths = [SKILL, *sorted(REFS.glob("*.md"))]
    assert all(path.read_text(encoding="utf-8").strip() for path in paths), "the skill files should hold text"
    result = subprocess.run(
        [sys.executable, str(LEAK_CHECK), *map(str, paths)], capture_output=True, text=True, check=False
    )
    if result.returncode == 0 and "no leak terms found" in result.stderr:
        pytest.skip("no leak terms: install the work overlay, or set DOTFILES_LEAK_TERMS")
    assert result.returncode == 0, f"the open-pr skill holds employer-specific text:\n{result.stdout}{result.stderr}"
    assert f"Leak check OK ({len(paths)} files" in result.stdout, result.stdout


def test_parent_owns_post_confirm_phase() -> None:
    parent_item = first_line_of(SPACELIFT, "**Own the confirm step in the parent.**")
    for needle in ("wait for the run to reach `FINISHED`", "`### After the apply`"):
        assert first_line_of(SPACELIFT, needle) == parent_item, f"the parent, not the agent, should own {needle}"


def test_change_map_front_matter_widens_label_wrapping() -> None:
    # Mermaid reads this block from every change map. A bad indent or key turns it off without an error,
    # and GitHub's Mermaid 12 then wraps labels at 120 px and splits names at hyphens.
    lines = read_lines(CHANGE_MAP)
    blocks = [
        [line[len(lines[start]) - len(lines[start].lstrip()) :] for line in lines[start : start + 5]]
        for start in range(len(lines) - 4)
        if lines[start].strip() == "---" and lines[start + 1].strip() == "config:"
    ]
    assert blocks == [["---", "config:", "  flowchart:", "    wrappingWidth: 400", "---"]], (
        "the change map front matter should set flowchart.wrappingWidth to 400 as nested YAML"
    )


def test_never_runs_gh_pr_merge() -> None:
    for line in [*read_lines(SKILL), *read_lines(SPACELIFT)]:
        if "gh pr merge" in line:
            assert "Do not use `gh pr merge`" in line, f"the skill must not tell the agent to run gh pr merge: {line}"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        (
            "Start one background agent for the whole stack",
            "parallel review-pr agents on adjacent layers would race a restack of the upper branch",
        ),
        ("Do not start one agent for each layer", "parallel review-pr agents would race a restack"),
        (
            "Never edit, commit, or push to another layer's branch",
            "two writers on one branch can overwrite each other's commits",
        ),
        ("Never restack, rebase, or force-push", "the background agent must not rewrite stack branches"),
        (
            "stop the follow-up before you change the stack",
            "a parent stack change while the agent runs makes two writers on one branch",
        ),
        (
            "Fast-forward the fixed layer's local branch to its remote branch",
            "a restack from the stale local branch discards the fix that the agent pushed",
        ),
    ],
)
def test_stack_follow_up_contains(needle: str, message: str) -> None:
    assert_contains(STACK, needle, message)


def test_stack_follow_up_stops_before_upper_layers_after_a_fix() -> None:
    assert_before(
        STACK,
        "The run pushed a fix to this layer, and a layer remains above it.",
        "Never edit, commit, or push to another layer's branch",
        "the agent must stop for the parent's restack before it reviews an upper layer",
    )
    assert_before(
        STACK,
        "Fast-forward the fixed layer's local branch to its remote branch",
        "gh stack rebase --upstack --no-trunk --remote origin",
        "the fix must be in the local branch before the restack, or the restack discards it",
    )


GIT_GUIDE = REPO_ROOT / "agents" / "guides" / "git-and-worktrees.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
GLOBAL_RULES = REPO_ROOT / "agents" / "global.md"


def _line_count(path: object) -> int:
    assert isinstance(path, type(SKILL))
    return len(path.read_text(encoding="utf-8").rstrip("\n").split("\n"))


def test_context_budget() -> None:
    # A single-PR run reads SKILL.md only. Growth here is context that every run pays for.
    assert _line_count(SKILL) <= 115, "SKILL.md is the per-run context budget for a single PR"
    assert _line_count(STACK) <= 70, "stack.md is read on every stack run; keep decisions and traps only"


def test_skill_has_one_stack_trigger_line() -> None:
    body = "\n".join(read_lines(SKILL)).split("\n---\n", 1)[1].split("\n")  # skip the frontmatter description
    lines = [line for line in body if "gh stack" in line or "references/stack.md" in line]
    assert len(lines) == 1, "SKILL.md should mention stacks in exactly one trigger line"
    assert "references/stack.md" in lines[0], "the trigger line should point at references/stack.md"


@pytest.mark.parametrize(
    ("needle", "message"),
    [
        ("never `git rebase --continue`", "a plain rebase continue bypasses the stack restack"),
        ("stop if any layer's `origin/<layer>` has commits that the local branch lacks", "remote-only commits"),
        ("git merge-base --is-ancestor", "the remote-only check should use ancestry"),
        ("Never split a hunk or rewrite a commit", "a layer boundary must not rewrite history"),
        ("prints a `⚠` line has failed", "a warning line is a failure even with exit 0"),
        ("gh pr create --base <parent> --head <layer>", "each layer PR is created with its real text"),
        ("gh stack link --remote origin --base <trunk>", "link keeps the chosen trunk as the bottom PR base"),
        ("Run the replacement step 8 once, after every layer is ready", "no PR opens before every layer has its text"),
        ("Check out the layer's branch before its step 1 and step 2", "a commit must land on its own layer"),
        ("Do not use `gh stack submit --auto`", "submit --auto opens PRs with generated text"),
        ("Never merge, `gh stack modify`, `gh stack unstack`, or `gh pr merge`", "no destructive stack actions"),
        ("`autoMergeRequest` is null", "the read-back must prove auto-merge is off"),
    ],
)
def test_stack_reference_contains(needle: str, message: str) -> None:
    assert_contains(STACK, needle, message)


def test_stack_reference_orders_create_link_and_read_back() -> None:
    assert_before(STACK, "gh pr create --base <parent> --head <layer>", "gh stack link --remote origin", "create first")
    assert_before(STACK, "gh stack link --remote origin", "Read back before step 9", "link before the read-back")


def test_stack_fetches_before_the_remote_ahead_guard() -> None:
    assert_before(STACK, "git fetch origin", "git merge-base --is-ancestor", "the guard must test fresh remote refs")
    assert_before(STACK, "Read back before step 9", "## Start the follow-up", "read back before the follow-up")


def test_stack_reference_does_not_mention_plate() -> None:
    assert first_line_of(STACK, "# ") is not None, "stack.md should exist and have a heading"
    assert_not_contains(STACK, "/plate", "the skill replaces /plate; do not point at it")


def test_stack_follow_up_reference_is_merged() -> None:
    assert not (REFS / "stack-follow-up.md").exists(), "stack-follow-up.md moved into stack.md"


def test_git_guide_pins_named_path_staging() -> None:
    assert_contains(GIT_GUIDE, "git add -- <path>...", "the guide should name the staging command")
    assert_contains(GIT_GUIDE, "never `git add -A`, `git add .`, or a directory", "the guide should ban broad staging")
    assert_contains(GIT_GUIDE, "git diff --cached --name-only", "the guide should check the cached path list")


def test_global_rules_route_plate_to_open_pr() -> None:
    assert_contains(GLOBAL_RULES, "Do not invoke `/plate`", "plate must not be invoked")
    assert_contains(GLOBAL_RULES, "guides/git-and-worktrees.md", "commit-only hand-offs use the Git guide rule")
    assert_contains(GIT_GUIDE, "When a skill hands off to `/plate`, use `open-pr`", "plate hand-offs use open-pr")
    mentions = [line for path in (GLOBAL_RULES, GIT_GUIDE) for line in read_lines(path) if "--commit-only" in line]
    assert mentions, "the prohibition on a --commit-only flag must exist"
    assert all("There is no `--commit-only` flag" in line for line in mentions), "do not invent a --commit-only flag"
    for path in (ROOT_AGENTS, GLOBAL_RULES):
        assert_not_contains(path, "references/stack-follow-up.md", "the reference moved to stack.md")


def test_spacelift_keep_alive_is_verified_after_set_monitor() -> None:
    # Bug caught: a session that never called set_monitor left auto_archive_on_close true and reported the step done.
    assert_before(
        SPACELIFT,
        "`mcp__ccd_pr__set_monitor`",
        "`monitor.auto_archive_on_close` is `false`",
        "check after set_monitor",
    )
    assert_contains(SPACELIFT, "Do not report this step as done before the check passes", "the check gates the report")


def test_spacelift_parent_waits_for_the_merge_in_the_background() -> None:
    # Bug caught: with Auto-fix on, nothing woke the session at merge, so the confirm link never reached Marcus.
    assert_contains(SPACELIFT, "including Auto-fix", "Auto-fix is a reason for the parent watch")
    assert_contains(
        SPACELIFT,
        "Wait for the merge in the background.",
        "the parent starts the merge wait",
    )
    assert_contains(SPACELIFT, "report this to Marcus and stop.", "a closed PR stops")
    assert_contains(SPACELIFT, "Do not enqueue the PR", "the parent still never enqueues")
    assert_not_contains(SPACELIFT, "Wait for the merge with a time limit", "the old chat-only wait is gone")


def test_skill_step_9_sends_the_auto_fix_case_to_the_parent_watch() -> None:
    assert_contains(SKILL, "including `--no-review` or Auto-fix", "step 9 names Auto-fix")


# The wrapper: open-pr loads its publish steps and changes some of them.


def test_loads_the_local_publish_steps_before_step_1_and_stops_when_the_read_fails() -> None:
    # Bug caught: a lost load line, or a run that goes on after a failed read, publishes from memory of the steps
    # and can skip the staging and force-push guards.
    load = "references/publish-steps.md"
    assert_contains(SKILL, load, "open-pr should read its local publish steps")
    assert_contains(SKILL, "If the read fails, stop and report the error", "a failed read should stop the run")
    assert_contains(SKILL, "Do not publish from memory of the steps", "a failed read should not fall back to memory")
    assert_before(SKILL, load, "## Changes to the publish steps", "the publish steps should load before the changes")


def test_publish_steps_hold_steps_1_to_9_in_order() -> None:
    # Bug caught: a vendoring or edit that drops or reorders a step, so open-pr's changes name a step that is absent.
    steps = [int(match[1]) for line in read_lines(PUBLISH_STEPS) if (match := re.match(r"(\d+)\. \*\*", line))]
    assert steps == list(range(1, 10)), "the publish steps file should hold steps 1-9 once each, in order"


def test_makes_no_read_from_the_ro_repository() -> None:
    # Bug caught: a leftover `gh api repos/sucramual/ro/...` read. The session may not reach ro, and an ro push
    # could change the steps without a review here.
    skill_dir = SKILL.parent
    # check-mermaid's installed node_modules hold binary files and are not the skill's own text.
    texts = {
        path: path.read_bytes().decode("utf-8", errors="replace")
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and "node_modules" not in path.relative_to(skill_dir).parts
    }
    assert SKILL in texts and PUBLISH_STEPS in texts, "the skill and its publish steps should exist"
    for path, text in texts.items():
        assert "repos/sucramual/ro/" not in text, f"{path} should not read the ro repository"


def test_no_ro_dev_dependency() -> None:
    # Bug caught: a leftover ro pin that uv sync still clones, though no test reads the package.
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "dev" in project["dependency-groups"], "the dev group should exist"
    assert not any(re.match(r"ro\b", dep) for dep in project["dependency-groups"]["dev"]), "ro is not a dev dependency"
    assert "ro" not in project.get("tool", {}).get("uv", {}).get("sources", {}), "ro has no uv source"
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert lock["package"], "uv.lock should list packages"
    assert not [package for package in lock["package"] if package["name"] == "ro"], "uv.lock should not hold ro"


def test_step_1_keeps_the_bench_branch_guard_in_every_publish_guard_block() -> None:
    # Bug caught: the publish steps leave PROTECTED_BRANCH_REGEX empty, so without the change open-pr commits and
    # pushes on a work bench branch such as main-07. A third guard block would also escape a two-block change.
    assert_contains(SKILL, "set `PROTECTED_BRANCH_REGEX='^main-[0-9]+$'`", "open-pr should guard bench branches")
    assert_contains(
        SKILL, "in the step 1 block and in the block for steps 3 and 4", "the change should cover both blocks"
    )
    guards = [line for line in read_lines(PUBLISH_STEPS) if line.strip() == "PROTECTED_BRANCH_REGEX=''"]
    assert len(guards) == 2, "the change names two guard blocks; the publish steps should have exactly two"
    assert re.fullmatch(r"main-[0-9]+", "main-07") and not re.fullmatch(r"main-[0-9]+", "main"), "regex sanity"


def test_dotfiles_mode_cuts_the_publish_block_at_the_push() -> None:
    # Bug caught: in dotfiles, open-pr must not push before ship. The cut needs this marker in the steps 3-4 block.
    assert_contains(DOTFILES_REF, "Run only its part above `# Step 4: push.`", "dotfiles mode should skip the push")
    assert_contains(PUBLISH_STEPS, "# Step 4: push.", "the publish steps block should keep the push marker")
