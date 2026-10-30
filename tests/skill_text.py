"""Phrase checks for agent-instruction files such as SKILL.md, matching the old bash grep helpers.

Matching is line-based and literal, like ``grep -F``: the file is split on ``\\n`` only, and a
needle matches a line when it is a substring of that line. Order checks compare the 1-based
number of the first line that contains each needle, like ``grep -nF | sed -n '1s/:.*//p'``.
"""

from __future__ import annotations

from pathlib import Path


def read_lines(path: Path) -> list[str]:
    """Return the file's lines, split on newline only (unlike str.splitlines, which also splits on \\r and more)."""
    return path.read_text(encoding="utf-8").split("\n")


def first_line_of(path: Path, needle: str) -> int | None:
    """1-based number of the first line containing needle, or None if no line does."""
    for number, line in enumerate(read_lines(path), start=1):
        if needle in line:
            return number
    return None


def assert_contains(path: Path, needle: str, message: str) -> None:
    """Fail with message unless some line of the file contains needle."""
    assert first_line_of(path, needle) is not None, message


def assert_not_contains(path: Path, needle: str, message: str) -> None:
    """Fail with message if any line of the file contains needle."""
    assert first_line_of(path, needle) is None, message


def assert_before(path: Path, first: str, second: str, message: str) -> None:
    """Fail with message unless both needles occur and first's first line is strictly before second's."""
    first_line = first_line_of(path, first)
    second_line = first_line_of(path, second)
    assert first_line is not None and second_line is not None and first_line < second_line, message
