"""Black-box tests for skills/open-pr/scripts/generate-pr-description.sh.

Each test builds a temp Git repo whose origin refs are set with update-ref (no real remote),
runs the real generator in it, and checks the Markdown it prints.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from conftest import REPO_ROOT, IsolatedEnv

SCRIPT = REPO_ROOT / "skills" / "open-pr" / "scripts" / "generate-pr-description.sh"
RunTool = Callable[..., subprocess.CompletedProcess[str]]

DESCRIPTION_TEMPLATE = """## Description
<!-- summarize the change -->

## Rollout Plan
- Confirm the generated body keeps required middle sections.

## Testing
<!-- list verification -->
"""


def init_repo(env: IsolatedEnv, repo: Path, branch: str = "main") -> Path:
    """A repo with one commit on branch, and origin/<branch> plus origin/HEAD pointing at it."""
    repo.mkdir(parents=True)
    env.git(repo, "init", "-q", "-b", branch)
    (repo / "README.md").write_text("base\n")
    env.git(repo, "add", "README.md")
    env.git(repo, "commit", "-q", "-m", "initial")
    env.git(repo, "remote", "add", "origin", str(repo / "remote.git"))
    env.git(repo, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
    env.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")
    return repo


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def commit_change(env: IsolatedEnv, repo: Path, branch: str, message: str) -> None:
    """Switch to a new branch, add feature.txt, and commit everything."""
    env.git(repo, "switch", "-q", "-c", branch)
    (repo / "feature.txt").write_text("change\n")
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "-m", message)


def make_description_repo(env: IsolatedEnv) -> Path:
    """The main case: a feature branch that adds a template, a script, and a test, plus one uncommitted file."""
    repo = init_repo(env, env.root / "description")
    env.git(repo, "switch", "-q", "-c", "feature/pr-description")
    write(repo / ".github" / "PULL_REQUEST_TEMPLATE.md", DESCRIPTION_TEMPLATE)
    write(
        repo / "skills" / "open-pr" / "scripts" / "generate-pr-description.sh",
        '#!/usr/bin/env bash\necho "draft"\n',
        executable=True,
    )
    write(repo / "tests" / "generate_pr_description_test.sh", '#!/usr/bin/env bash\necho "test"\n')
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "-m", "feat(open-pr): add generator")
    (repo / "uncommitted.txt").write_text("not committed\n")
    return repo


def generate(run_tool: RunTool, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_tool([str(SCRIPT), *args], cwd=repo)


def generate_ok(run_tool: RunTool, repo: Path, *args: str) -> str:
    result = generate(run_tool, repo, *args)
    assert result.returncode == 0, f"generator should succeed with {list(args)}\n{result.stderr}"
    return result.stdout


def test_description_follows_template_and_summarizes_committed_diff(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = make_description_repo(isolated_env)
    out = generate_ok(run_tool, repo, "--base-branch", "origin/main")

    assert "## Description" in out, "description should preserve the PR template heading"
    assert "## Rollout Plan" in out, "description should preserve required template sections between HTML comments"
    assert "## Testing" in out, "description should preserve the testing template heading"
    assert "skills/open-pr/scripts/generate-pr-description.sh" in out, (
        "description should mention changed generator script"
    )
    assert "tests/generate_pr_description_test.sh" in out, "description should mention changed tests"
    assert "```text" in out, "description should include a changed-files block"
    assert "Generated from branch diff against origin/main." in out, "description should state the diff base"
    assert "implementation change" in out, "description should classify changed implementation files"
    assert "test coverage change" in out, "description should classify changed test files"
    assert "- `skills/open-pr/scripts/generate-pr-description.sh`: implementation change, status `A`, +2/-0." in out, (
        "description should render only the Git status token"
    )
    assert "<!--" not in out, "description should remove template comments"
    assert "uncommitted.txt" not in out, "description should only summarize the committed branch diff"


def test_debug_mode_reports_to_stderr_and_keeps_description_on_stdout(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = make_description_repo(isolated_env)
    result = generate(run_tool, repo, "--base-branch", "origin/main", "--debug")
    assert result.returncode == 0, f"generator should succeed in debug mode\n{result.stderr}"

    assert "Using base branch: origin/main" in result.stderr, "debug mode should report the selected base"
    assert "Changed files:" in result.stderr, "debug mode should report the changed-file list"
    assert "## Description" in result.stdout, "debug mode should keep the generated description on stdout"


def test_loads_lowercase_github_template(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "lowercase-template")
    write(
        repo / ".github" / "pull_request_template.md",
        "## Description\n\n## Release Checklist\n- Keep this checklist.\n\n## Testing\n",
    )
    commit_change(isolated_env, repo, "feature/lowercase-template", "feat: use lowercase template")

    out = generate_ok(run_tool, repo, "--base-branch", "origin/main")

    assert "## Release Checklist" in out, "description should load GitHub's lowercase .github pull request template"


def test_prefers_base_branch_template_over_feature_branch_template(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "base-template")
    template = repo / ".github" / "PULL_REQUEST_TEMPLATE.md"
    write(
        template,
        "## Description\n\n## Base Branch Checklist\n- Preserve the repository's required checklist.\n\n## Testing\n",
    )
    isolated_env.git(repo, "add", ".github/PULL_REQUEST_TEMPLATE.md")
    isolated_env.git(repo, "commit", "-q", "-m", "docs: add pull request template")
    isolated_env.git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    isolated_env.git(repo, "switch", "-q", "-c", "feature/change-template")
    write(
        template,
        "## Description\n\n## Feature Branch Checklist\n"
        "- This must not replace the base branch template.\n\n## Testing\n",
    )
    (repo / "feature.txt").write_text("change\n")
    isolated_env.git(repo, "add", ".")
    isolated_env.git(repo, "commit", "-q", "-m", "feat: change pull request template")

    out = generate_ok(run_tool, repo, "--base-branch", "origin/main")

    assert "## Base Branch Checklist" in out, "description should prefer the base branch pull request template"
    assert "## Feature Branch Checklist" not in out, (
        "description should not replace required base sections with a feature branch template"
    )


def test_infers_origin_master_and_uses_fallback_sections(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "master-default", branch="master")
    isolated_env.git(repo, "symbolic-ref", "-q", "--delete", "refs/remotes/origin/HEAD")
    commit_change(isolated_env, repo, "feature/master-default", "feat: support master default")

    out = generate_ok(run_tool, repo)

    assert "Generated from branch diff against origin/master." in out, (
        "description should infer origin/master before falling back to origin/main"
    )
    assert "## Description" in out, "description should use a fallback description section when no template exists"
    assert "## Testing" in out, "description should use a fallback testing section when no template exists"


def test_rejects_ambiguous_conventional_base_refs(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "ambiguous-default", branch="master")
    isolated_env.git(repo, "symbolic-ref", "-q", "--delete", "refs/remotes/origin/HEAD")
    isolated_env.git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    commit_change(isolated_env, repo, "feature/ambiguous-default", "feat: exercise ambiguous default")

    result = generate(run_tool, repo)

    assert result.returncode != 0, "generator should reject ambiguous conventional base refs"
    assert "Both origin/main and origin/master exist; pass --base-branch explicitly" in result.stderr, (
        "ambiguous base failure should require an explicit base ref"
    )


def test_keeps_partial_template_and_appends_missing_sections(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "partial-template")
    write(repo / ".github" / "PULL_REQUEST_TEMPLATE.md", "## Context\n\n- Preserve this custom-only template.\n")
    commit_change(isolated_env, repo, "feature/partial-template", "feat: preserve partial template")

    out = generate_ok(run_tool, repo, "--base-branch", "origin/main")

    assert "## Context" in out, "description should preserve a template without standard headings"
    assert "## Description" in out, "description should append a missing description section"
    assert "## Testing" in out, "description should append a missing testing section"


def test_fails_when_branch_has_no_committed_changes(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = init_repo(isolated_env, isolated_env.root / "empty")

    result = generate(run_tool, repo, "--base-branch", "origin/main")

    assert result.returncode != 0, "generator should fail when there are no committed changes"
    assert "No changed files found" in result.stderr, "empty branch failure should explain missing diff"


def test_rejects_base_branch_flag_without_value(isolated_env: IsolatedEnv, run_tool: RunTool):
    repo = make_description_repo(isolated_env)

    result = generate(run_tool, repo, "--base-branch")

    assert result.returncode != 0, "generator should reject --base-branch without a value"
    assert "ERROR: --base-branch requires a value" in result.stderr, (
        "missing base value should produce an actionable error"
    )
