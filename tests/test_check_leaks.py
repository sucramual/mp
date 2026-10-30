"""Black-box tests for scripts/check_leaks.py, the deny-list check for private terms.

Each test builds a scratch Git repository and runs the script as a subprocess with a clean environment.
The terms here are made up. The real terms are private and never appear in this repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "check_leaks.py"
TERM = "zorblaxcorp"
OTHER = "quuxhost.example"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "clean.md").write_text("Nothing private here.\n")
    git(root, "add", "clean.md")
    return root


def run(repo: Path, tmp_path: Path, *paths: str, **env: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    base = {"PATH": os.environ["PATH"], "HOME": str(home)}
    return subprocess.run(
        [str(SCRIPT), "--root", str(repo), *paths],
        cwd=repo,
        env=base | env,
        capture_output=True,
        text=True,
        check=False,
    )


def terms_file(tmp_path: Path, *terms: str) -> str:
    path = tmp_path / "terms.txt"
    path.write_text("# private deny list\n\n" + "\n".join(terms) + "\n")
    return str(path)


# Bug caught: a match that prints the term or the matched line, which would publish the term in a CI log.
def test_reports_path_line_and_index_but_never_the_term(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"line one\nWe work at {TERM.upper()} today.\n")  # untracked, not ignored

    result = run(repo, tmp_path, DOTFILES_LEAK_TERMS_FILE=terms_file(tmp_path, OTHER, TERM))

    assert result.returncode == 1, result.stderr
    assert "notes.md:2: matches leak term #2" in result.stdout.splitlines()
    output = (result.stdout + result.stderr).casefold()
    assert output, "the check should print its findings"
    assert TERM not in output and "today" not in output


# Bug caught: a scan of tracked files only, which misses a new file before it is staged.
def test_finds_terms_in_tracked_files_and_in_paths(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked.txt").write_text(f"{TERM}\n")
    (repo / f"{TERM}-notes").mkdir()
    (repo / f"{TERM}-notes" / "a.md").write_text("clean\n")
    git(repo, "add", "tracked.txt")

    result = run(repo, tmp_path, DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 1, result.stderr
    lines = result.stdout.splitlines()
    assert "tracked.txt:1: matches leak term #1" in lines
    assert any(line.endswith("a.md: the path matches leak term #1") for line in lines), lines


# Bug caught: an ignored build output that fails the check, although it never reaches the public repository.
def test_skips_ignored_files_and_passes_a_clean_repo(repo: Path, tmp_path: Path) -> None:
    (repo / ".gitignore").write_text("build/\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.txt").write_text(f"{TERM}\n")

    result = run(repo, tmp_path, DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Leak check OK" in result.stdout


# Bug caught: a scan that follows a symlink and reads a private file outside the repository.
def test_does_not_follow_symlinks(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.md").write_text(f"{TERM}\n")
    (repo / "link.md").symlink_to(outside / "secret.md")
    (repo / "linked-dir").symlink_to(outside)
    git(repo, "add", "link.md", "linked-dir")

    result = run(repo, tmp_path, DOTFILES_LEAK_TERMS=TERM)
    explicit = run(repo, tmp_path, "link.md", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Leak check OK (3 files" in result.stdout, "the check should list both links and clean.md"
    assert explicit.returncode == 0, explicit.stdout + explicit.stderr

    # The link text is what Git stores, so the check reads it.
    (repo / "named.md").symlink_to(tmp_path / f"{TERM}.md")
    named = run(repo, tmp_path, DOTFILES_LEAK_TERMS=TERM)
    assert named.returncode == 1
    assert "named.md:1: matches leak term #1" in named.stdout.splitlines()


# Bug caught: a laptop without the work overlay that cannot run scripts/check at all.
def test_no_terms_locally_warns_and_passes(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"{TERM}\n")

    result = run(repo, tmp_path, DOTFILES_WORK_DIR=str(tmp_path / "no-overlay"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr.count("no leak terms found") == 1, result.stderr
    assert "Leak check OK" not in result.stdout


# Bug caught: a CI run without the secret that passes, so the merge gate checks nothing.
def test_no_terms_in_ci_fails(repo: Path, tmp_path: Path) -> None:
    result = run(repo, tmp_path, CI="true", DOTFILES_LEAK_TERMS="", DOTFILES_LEAK_TERMS_OPTIONAL="")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "no leak terms in CI" in result.stderr
    assert "Leak check OK" not in result.stdout


# Bug caught: a pull request from a Git fork, which gets no secrets, that can never pass CI.
def test_optional_flag_passes_in_ci_without_terms(repo: Path, tmp_path: Path) -> None:
    result = run(repo, tmp_path, CI="true", DOTFILES_LEAK_TERMS_OPTIONAL="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no leak terms found" in result.stderr


# Bug caught: the optional flag that also turns off a check that has terms.
def test_optional_flag_still_checks_when_terms_exist(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"{TERM}\n")

    result = run(repo, tmp_path, CI="true", DOTFILES_LEAK_TERMS=TERM, DOTFILES_LEAK_TERMS_OPTIONAL="1")

    assert result.returncode == 1
    assert "notes.md:1: matches leak term #1" in result.stdout.splitlines()


# Bug caught: sources merged or read in the wrong order, so the indices do not match the one list.
def test_term_sources_in_order(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"{TERM}\n{OTHER}\n")
    overlay = tmp_path / "overlay"
    (overlay / "config").mkdir(parents=True)
    (overlay / "config" / "leak-terms.txt").write_text(f"# overlay\nfiller\n{TERM}\n")
    from_file = terms_file(tmp_path, OTHER)

    first = run(
        repo, tmp_path, DOTFILES_LEAK_TERMS_FILE=from_file, DOTFILES_LEAK_TERMS=TERM, DOTFILES_WORK_DIR=str(overlay)
    )
    second = run(repo, tmp_path, DOTFILES_LEAK_TERMS=f"alpha\nbeta\n{TERM}", DOTFILES_WORK_DIR=str(overlay))
    third = run(repo, tmp_path, DOTFILES_WORK_DIR=str(overlay))

    assert first.stdout.splitlines() == ["notes.md:2: matches leak term #1"], first.stdout
    assert second.stdout.splitlines() == ["notes.md:1: matches leak term #3"], second.stdout
    assert third.stdout.splitlines() == ["notes.md:1: matches leak term #2"], third.stdout

    # The default overlay is ~/dotfiles-work.
    home = tmp_path / "home"
    (home / "dotfiles-work").mkdir(parents=True)
    (home / "dotfiles-work" / "config").symlink_to(overlay / "config")
    default = run(repo, tmp_path)
    assert default.stdout.splitlines() == ["notes.md:1: matches leak term #2"], default.stdout


# Bug caught: a terms file that is set but missing, which would pass as "no terms" and check nothing.
def test_unreadable_terms_file_fails(repo: Path, tmp_path: Path) -> None:
    result = run(repo, tmp_path, DOTFILES_LEAK_TERMS_FILE=str(tmp_path / "missing.txt"), DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 2
    assert "cannot read $DOTFILES_LEAK_TERMS_FILE" in result.stderr
    assert "Leak check OK" not in result.stdout


# Bug caught: CI that reports the leak check only inside the long `checks` job, or without the secret.
def test_workflow_has_separate_leaks_job_with_secret() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "checks.yml").read_text()
    secret = "DOTFILES_LEAK_TERMS: ${{ secrets.DOTFILES_LEAK_TERMS }}"

    before, marker, job = text.partition("\n  leaks:\n")
    assert marker
    assert "run: python3 scripts/check_leaks.py" in job
    assert secret in job
    # The `checks` job keeps the secret, because scripts/check runs the leak check too.
    assert secret in before


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "-m", message)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


# Bug caught: a --tree check that reads the working tree, so a term that a later edit removed from disk
# still reaches the public repository in the pushed commit.
def test_tree_checks_the_commit_not_the_working_tree(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"line one\nWe work at {TERM.upper()} today.\n")
    leaky = commit_all(repo, "leaky")
    (repo / "notes.md").write_text("line one\nclean now\n")  # A clean working tree.

    result = run(repo, tmp_path, "--tree", leaky, DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["notes.md:2: matches leak term #1"]
    output = (result.stdout + result.stderr).casefold()
    assert TERM not in output and "today" not in output


# Bug caught: a --tree check that fails on a term in an uncommitted edit, which a push does not publish.
def test_tree_ignores_uncommitted_changes(repo: Path, tmp_path: Path) -> None:
    clean = commit_all(repo, "clean")
    (repo / "clean.md").write_text(f"{TERM}\n")
    (repo / "untracked.md").write_text(f"{TERM}\n")

    result = run(repo, tmp_path, "--tree", clean, DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Leak check OK (1 files" in result.stdout


# Bug caught: a --tree check that misses a term in a path, or that reads a symlink's target instead of
# the link text that Git stores.
def test_tree_checks_paths_and_link_text(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "private.md"
    outside.write_text(f"{TERM}\n")
    (repo / "link.md").symlink_to(outside)
    (repo / f"{TERM}-notes.md").write_text("clean\n")
    (repo / "named.md").symlink_to(tmp_path / f"{TERM}.md")
    commit = commit_all(repo, "links")

    result = run(repo, tmp_path, "--tree", commit, DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 1, result.stdout + result.stderr
    assert sorted(result.stdout.splitlines()) == [
        "named.md:1: matches leak term #1",
        f"{TERM}-notes.md: the path matches leak term #1",
    ]


# Bug caught: a revision that Git cannot resolve, which would pass as a tree with no files.
def test_tree_with_an_unknown_revision_fails(repo: Path, tmp_path: Path) -> None:
    result = run(repo, tmp_path, "--tree", "no-such-branch", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "cannot read the files" in result.stderr
    assert "Leak check OK" not in result.stdout


def run_commits(repo: Path, tmp_path: Path, commits: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [str(SCRIPT), "--root", str(repo), "--commits-from", "-"],
        cwd=repo,
        env={"PATH": os.environ["PATH"], "HOME": str(home)} | env,
        input="".join(f"{commit}\n" for commit in commits),
        capture_output=True,
        text=True,
        check=False,
    )


# Bug caught: a --commits-from check that reads only the final tree, so a term that a later commit removed
# is missed, or that prints the term.
def test_commits_find_a_term_that_a_later_commit_removed(repo: Path, tmp_path: Path) -> None:
    (repo / "notes.md").write_text(f"line one\nWe work at {TERM.upper()} today.\n")
    leaky = commit_all(repo, "leaky")
    (repo / "notes.md").write_text("clean\n")
    clean = commit_all(repo, "clean")

    result = run_commits(repo, tmp_path, [leaky, clean], DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.splitlines() == [f"commit {leaky[:12]}: notes.md:2: matches leak term #1"]
    output = (result.stdout + result.stderr).casefold()
    assert TERM not in output and "today" not in output


# Bug caught: a check that reads whole trees for every commit, so a term in a file that the listed commit
# did not touch blocks it. Large first pushes would also be slow.
def test_commits_check_only_the_files_that_each_commit_changes(repo: Path, tmp_path: Path) -> None:
    (repo / "old.md").write_text(f"{TERM}\n")
    commit_all(repo, "old term, not listed")
    (repo / "new.md").write_text("clean\n")
    new = commit_all(repo, "new")

    result = run_commits(repo, tmp_path, [new], DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Leak check OK (1 files" in result.stdout


# Bug caught: a check that misses a term in a changed path, follows a symlink, or skips a root commit.
def test_commits_check_paths_link_text_and_the_root_commit(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q")
    outside = tmp_path / "private.md"
    outside.write_text(f"{TERM}\n")
    (root / "link.md").symlink_to(outside)
    (root / f"{TERM}-notes.md").write_text("clean\n")
    (root / "named.md").symlink_to(tmp_path / f"{TERM}.md")
    first = commit_all(root, "root commit")

    result = run_commits(root, tmp_path, [first], DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 1, result.stdout + result.stderr
    assert sorted(result.stdout.splitlines()) == [
        f"commit {first[:12]}: named.md:1: matches leak term #1",
        f"commit {first[:12]}: {TERM}-notes.md: the path matches leak term #1",
    ]


# Bug caught: a deleted file that is read from the missing tree entry, or a commit list that fails open.
def test_commits_ignore_deletions_and_an_empty_list_passes(repo: Path, tmp_path: Path) -> None:
    commit_all(repo, "add")
    (repo / "clean.md").unlink()
    deleted = commit_all(repo, "delete")

    assert run_commits(repo, tmp_path, [deleted], DOTFILES_LEAK_TERMS=TERM).returncode == 0
    assert run_commits(repo, tmp_path, [], DOTFILES_LEAK_TERMS=TERM).returncode == 0


# Bug caught: an unknown commit that passes as a commit with no files.
def test_commits_with_an_unknown_commit_fail(repo: Path, tmp_path: Path) -> None:
    result = run_commits(repo, tmp_path, ["0" * 40], DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "cannot read the files" in result.stderr


# Bug caught: a mix of --commits-from with --tree, which would silently ignore one of them.
def test_commits_from_rejects_a_mix_with_tree(repo: Path, tmp_path: Path) -> None:
    result = run(repo, tmp_path, "--tree", "HEAD", "--commits-from", "-", DOTFILES_LEAK_TERMS=TERM)

    assert result.returncode == 2, result.stdout + result.stderr
