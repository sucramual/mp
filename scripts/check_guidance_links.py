#!/usr/bin/env python3
"""Check inline local Markdown links in AGENTS.md, agents/global.md, and agents/guides/*.md.

It also checks that each skill in skills/<name>/ works when installed alone:
- A relative link must stay inside the skill's own folder.
- A raw.githubusercontent.com or github.com/blob URL to this repository on main
  must name a file in the working tree, which becomes main after the merge.
- A skill must not read a dotfiles checkout path (~/dotfiles/, ~/.agent-guidance/guides/).
Skill dependencies in node_modules are not checked.

This small checker supports plain or angle-bracket targets and optional titles.
It ignores code examples, external URLs, and fragments in link checks. It does not
parse full Markdown: reference links and targets with nested parentheses are outside scope.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>[^\s()]+))(?:\s+['\"][^\n]*?['\"])?\s*\)")
CODE = re.compile(
    r"(?P<fence>^ {0,3}(?P<marker>`{3,}|~{3,})[^\n]*\n.*?^ {0,3}(?P=marker)[ \t]*$)|`+[^`\n]*`+", re.M | re.S
)

# Repository files that a skill reads from GitHub. The URL ends at whitespace, a quote, or Markdown punctuation.
REPO_URL = re.compile(
    r"https://(?:raw\.githubusercontent\.com/sucramual/mp/main|github\.com/sucramual/mp/blob/main)/"
    r"(?P<path>[^\s)>`'\"#?]+)"
)
# Paths that exist only on a machine with the dotfiles checkout. ~/.agent-guidance/ files outside
# guides/, such as vocabulary.md, are optional personal config that a skill reads only when it exists.
CHECKOUT_PATH = re.compile(r"~/(?:dotfiles|\.agent-guidance/guides)(?:/[^\s)>`'\"]*)?")


def check_document(document: Path, root: Path, skill: Path | None = None) -> list[str]:
    """Return diagnostics for missing files without checking section anchors.

    With `skill`, also apply the self-contained skill rules from the module docstring.
    """
    label = document.relative_to(root)
    try:
        contents = document.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"{label}: cannot read document: {error}"]
    # Keep line positions when removing code, so diagnostics refer to the source.
    prose = CODE.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), contents)
    errors: list[str] = []
    for match in LINK.finditer(prose):
        target = match.group("angle") or match.group("plain")
        line = prose.count("\n", 0, match.start()) + 1
        try:
            url = urlsplit(target)
        except ValueError as error:
            errors.append(f"{label}:{line}: invalid link target {target!r}: {error}")
            continue
        if url.scheme or url.netloc or not url.path:
            continue
        resolved = document.parent / unquote(url.path)
        if not resolved.is_file():
            errors.append(f"{label}:{line}: local link target is not a file: {target}")
        elif skill is not None and not is_inside(resolved, skill):
            errors.append(
                f"{label}:{line}: link leaves the skill folder, outside {skill.relative_to(root)}/: {target}; "
                "use a raw.githubusercontent.com URL on main"
            )
    if skill is not None:
        errors.extend(check_skill_text(contents, label, root))
    return errors


def is_inside(path: Path, folder: Path) -> bool:
    """Return whether the normalized path is in the folder. Symlinks count where they point."""
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(folder))


def check_skill_text(contents: str, label: Path, root: Path) -> list[str]:
    """Check repository URLs and checkout paths everywhere, code included, because skills run commands from code."""
    errors: list[str] = []
    for match in REPO_URL.finditer(contents):
        line = contents.count("\n", 0, match.start()) + 1
        path = unquote(match.group("path"))
        if not (root / path).is_file():
            errors.append(f"{label}:{line}: repository URL names no file in the working tree: {path}")
    for match in CHECKOUT_PATH.finditer(contents):
        line = contents.count("\n", 0, match.start()) + 1
        errors.append(
            f"{label}:{line}: skill reads a dotfiles checkout path: {match.group()}; "
            "use a raw.githubusercontent.com URL on main"
        )
    return errors


def skill_documents(root: Path) -> list[tuple[Path, Path]]:
    """Return (document, skill folder) for each Markdown file in skills/<name>/, without node_modules."""
    skills = root / "skills"
    return [
        (document, skills / document.relative_to(skills).parts[0])
        for document in sorted(skills.glob("*/**/*.md"))
        if "node_modules" not in document.relative_to(skills).parts
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args().root.resolve()
    documents = [root / "AGENTS.md", root / "agents" / "global.md", *sorted((root / "agents" / "guides").glob("*.md"))]
    errors = [error for document in documents for error in check_document(document, root)]
    skill_docs = skill_documents(root)
    errors += [error for document, skill in skill_docs for error in check_document(document, root, skill)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Guidance links OK ({len(documents)} documents, {len(skill_docs)} skill documents).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
