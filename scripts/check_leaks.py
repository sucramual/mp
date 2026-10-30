#!/usr/bin/env python3
"""Fail when a repository file holds a private deny-list term, such as an employer name or host.

The terms are private, so this file and its output never show them. A match prints only
`path:line` and the 1-based index of the term in the list.

Terms come from the first of these sources that is set:
  1. the file that $DOTFILES_LEAK_TERMS_FILE names;
  2. $DOTFILES_LEAK_TERMS, one term per line (CI passes a repository secret here);
  3. ${DOTFILES_WORK_DIR:-$HOME/dotfiles-work}/config/leak-terms.txt, the private work overlay.
Each source holds one term per line. A line that starts with `#` is a comment. A match is a
case-insensitive substring match.

With no paths, the check reads every tracked file and every untracked file that Git does not ignore.
With --tree REV, it reads the files of the commit or tree REV from the Git object store instead of the
working tree. The pre-push hook in config/git-hooks uses this to check what a push publishes.
With --commits-from FILE (`-` for stdin), it reads one commit ID per line and checks only the files that
each commit adds or changes. The pre-push hook uses this to check every commit that a push newly publishes.
It never follows a symlink: for a symlink, it checks the link text only.

Exit 0: no match. Exit 1: a match. Exit 2: the terms or the files cannot be read.
With no terms, the check prints one warning and exits 0, except when CI=true. In CI it exits 2,
unless DOTFILES_LEAK_TERMS_OPTIONAL=1 (a pull request from a Git fork, which gets no secrets).
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

NO_TERMS_WARNING = "check_leaks: warning: no leak terms found, so the leak check did not run."


class TermsError(Exception):
    """A term source is set but cannot be read."""


def parse_terms(text: str) -> list[str]:
    terms = []
    for raw in text.splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            terms.append(term.casefold())
    return terms


def load_terms(env: dict[str, str]) -> tuple[str, list[str]]:
    """Return a label for the source and its terms. The label never holds a term."""
    terms_file = env.get("DOTFILES_LEAK_TERMS_FILE", "")
    if terms_file:
        try:
            return "$DOTFILES_LEAK_TERMS_FILE", parse_terms(Path(terms_file).read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            raise TermsError(f"cannot read $DOTFILES_LEAK_TERMS_FILE: {error.__class__.__name__}") from error
    if env.get("DOTFILES_LEAK_TERMS", "").strip():
        return "$DOTFILES_LEAK_TERMS", parse_terms(env["DOTFILES_LEAK_TERMS"])
    work_dir = Path(env.get("DOTFILES_WORK_DIR") or Path(env.get("HOME", str(Path.home()))) / "dotfiles-work")
    overlay = work_dir / "config" / "leak-terms.txt"
    if not overlay.is_file():
        return "none", []
    try:
        return "the work overlay leak-terms.txt", parse_terms(overlay.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise TermsError(f"cannot read the work overlay leak-terms.txt: {error.__class__.__name__}") from error


def repository_files(root: Path) -> list[str]:
    """Tracked files, and untracked files that Git does not ignore, as paths relative to root."""
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
    ).stdout
    return sorted({name.decode("utf-8", "surrogateescape") for name in output.split(b"\0") if name})


def read_without_following(path: Path, root: Path) -> str | None:
    """Return the text to check: a symlink's link text, or a regular file's content. Else None."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None  # A tracked file that the working tree deleted.
    if stat.S_ISLNK(info.st_mode):
        return os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        return None  # A directory, such as a submodule.
    if path.parent.resolve() != path.parent:
        print(f"check_leaks: skipped {path.relative_to(root)}: a parent folder is a symlink", file=sys.stderr)
        return None
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read().decode("utf-8", "replace")


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], input=stdin, check=True, capture_output=True).stdout


def _read_blobs(root: Path, blob_ids: list[str]) -> dict[str, str]:
    """Read blobs from the object store with one cat-file --batch. Never touches the working tree."""
    ids = sorted(set(blob_ids))
    output = _git(root, "cat-file", "--batch", stdin="".join(f"{object_id}\n" for object_id in ids).encode())
    blobs = {}
    position = 0
    for object_id in ids:
        header_end = output.index(b"\n", position)
        size = int(output[position:header_end].split()[2])
        blobs[object_id] = output[header_end + 1 : header_end + 1 + size].decode("utf-8", "replace")
        position = header_end + 1 + size + 1
    return blobs


def tree_files(root: Path, rev: str) -> dict[str, str | None]:
    """Each file in the tree of rev, mapped to the text to check. Reads only the Git object store.

    A symlink's blob holds its link text, so the check reads the link text and never the target.
    A submodule entry has no blob here, so only its path is checked.
    """
    # rev-parse turns rev into a tree ID, so ls-tree never reads rev as an option.
    tree = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{tree}}").decode().strip()
    entries = {}
    for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
        if not entry:
            continue
        meta, _, name = entry.partition(b"\t")
        _mode, kind, object_id = meta.decode().split()
        entries[name.decode("utf-8", "surrogateescape")] = object_id if kind == "blob" else None
    blobs = _read_blobs(root, [object_id for object_id in entries.values() if object_id])
    return {name: blobs[object_id] if object_id else None for name, object_id in entries.items()}


def commit_changes(root: Path, commit: str) -> dict[str, str | None]:
    """Each file that commit adds or changes (not deletions), as path -> blob ID, or None for a submodule.

    For a merge commit, -m compares with each parent. Over-checking is safe. Reads only the object store.
    """
    # rev-parse turns the argument into a commit ID, so diff-tree never reads it as an option.
    sha = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit}^{{commit}}").decode().strip()
    raw = _git(
        root, "diff-tree", "--no-commit-id", "-r", "-m", "--root", "-z", "--no-renames", "--diff-filter=AMT", sha
    )
    tokens = raw.split(b"\0")
    changes: dict[str, str | None] = {}
    for meta, name in zip(tokens[0::2], tokens[1::2], strict=False):
        # Raw format: :<old mode> <new mode> <old ID> <new ID> <status>
        _old_mode, new_mode, _old_id, new_id, _status = meta.decode().lstrip(":").split()
        changes[name.decode("utf-8", "surrogateescape")] = None if new_mode == "160000" else new_id
    return changes


def commits_files(root: Path, commits: list[str]) -> list[tuple[str, dict[str, str | None]]]:
    """For each commit, the files it adds or changes, mapped to the text to check."""
    changes = [(commit, commit_changes(root, commit)) for commit in commits]
    blobs = _read_blobs(root, [oid for _, files in changes for oid in files.values() if oid])
    return [(commit, {name: blobs[oid] if oid else None for name, oid in files.items()}) for commit, files in changes]


def find_matches(names: list[str], terms: list[str], read: Callable[[str], str | None]) -> list[str]:
    findings = []
    for name in names:
        lowered_name = name.casefold()
        for index, term in enumerate(terms, start=1):
            if term in lowered_name:
                findings.append(f"{name}: the path matches leak term #{index}")
        text = read(name)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.casefold()
            for index, term in enumerate(terms, start=1):
                if term in lowered:
                    findings.append(f"{name}:{number}: matches leak term #{index}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path, help="files to check; default: the repository files")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--tree", metavar="REV", help="check the files of this commit, not the working tree")
    parser.add_argument(
        "--commits-from",
        metavar="FILE",
        help="check only the files that each commit in FILE (one ID per line, `-` for stdin) adds or changes",
    )
    args = parser.parse_args(argv)
    if sum(bool(value) for value in (args.tree, args.commits_from, args.paths)) > 1:
        parser.error("give paths, --tree, or --commits-from, not a mix")
    root = args.root.resolve()
    env = dict(os.environ)

    try:
        source, terms = load_terms(env)
    except TermsError as error:
        print(f"check_leaks: {error}", file=sys.stderr)
        return 2
    if not terms:
        if env.get("CI") == "true" and env.get("DOTFILES_LEAK_TERMS_OPTIONAL") != "1":
            print(
                "check_leaks: no leak terms in CI. Set the DOTFILES_LEAK_TERMS secret, or set "
                "DOTFILES_LEAK_TERMS_OPTIONAL=1 for a pull request from a Git fork.",
                file=sys.stderr,
            )
            return 2
        print(NO_TERMS_WARNING, file=sys.stderr)
        return 0

    try:
        if args.commits_from:
            listing = sys.stdin.read() if args.commits_from == "-" else Path(args.commits_from).read_text()
            names = []
            findings = []
            for commit, texts in commits_files(root, listing.split()):
                names.extend(texts)
                for line in find_matches(sorted(texts), terms, texts.__getitem__):
                    findings.append(f"commit {commit[:12]}: {line}")
        elif args.tree:
            texts = tree_files(root, args.tree)
            names = sorted(texts)
            findings = find_matches(names, terms, texts.__getitem__)
        else:
            if args.paths:
                # abspath, not resolve: resolve would follow a symlink.
                names = [str(Path(os.path.abspath(path)).relative_to(root)) for path in args.paths]
            else:
                names = repository_files(root)
            findings = find_matches(names, terms, lambda name: read_without_following(root / name, root))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"check_leaks: cannot read the files: {error.__class__.__name__}", file=sys.stderr)
        return 2
    if findings:
        print("\n".join(findings))
        print(f"check_leaks: {len(findings)} leak(s) of terms from {source}.", file=sys.stderr)
        return 1
    print(f"Leak check OK ({len(names)} files, {len(terms)} terms from {source}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
