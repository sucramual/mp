#!/usr/bin/env python3
"""Check inline local Markdown links in AGENTS.md, agents/global.md, and agents/guides/*.md.

This small checker supports plain or angle-bracket targets and optional titles.
It ignores code examples, external URLs, and fragments. It does not parse full
Markdown: reference links and targets with nested parentheses are outside scope.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>[^\s()]+))(?:\s+['\"][^\n]*?['\"])?\s*\)")
CODE = re.compile(
    r"(?P<fence>^ {0,3}(?P<marker>`{3,}|~{3,})[^\n]*\n.*?^ {0,3}(?P=marker)[ \t]*$)|`+[^`\n]*`+", re.M | re.S
)


def check_document(document: Path, root: Path) -> list[str]:
    """Return diagnostics for missing files without checking section anchors."""
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
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args().root.resolve()
    documents = [root / "AGENTS.md", root / "agents" / "global.md", *sorted((root / "agents" / "guides").glob("*.md"))]
    errors = [error for document in documents for error in check_document(document, root)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Guidance links OK ({len(documents)} documents).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
