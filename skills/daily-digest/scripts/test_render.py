"""Behaviour tests for render.py: validation refusals, escaping, link labels, and both outputs."""

from __future__ import annotations

from pathlib import Path

import pytest
import render

GOOD = """# Daily digest — Tuesday 3 November 2026

Covers: Monday 2 November to Monday 2 November (Claude, Codex, Linear)

## Yesterday

### Webhook retries
- Fixed the duplicate-event retry loop in https://github.com/acme/repo/pull/123 for https://linear.app/acme/issue/PAY-412/webhook.

## Three concepts

### 1. Idempotent handlers
A handler is idempotent when a repeat call has no extra effect.
**Why it mattered:** The webhook retried eight times.
**Check yourself:** What should the handler return on a duplicate event?

### 2. Discriminated unions
A tag field lets the type checker narrow a union.
**Why it mattered:** The `z.union` result did not narrow.
**Check yourself:** Which key does the schema select on?

### 3. Worktree pruning
Prune a worktree only after its branch merges.
**Why it mattered:** Old worktrees filled the disk.
**Check yourself:** When is it safe to delete a branch?

## Today
1. Review [#18390](https://github.com/acme/repo/pull/18390) because Alex asked on Friday.
2. Finish PAY-415 before Wednesday.
"""


def write(tmp_path: Path, text: str, name: str = "2026-11-03.md") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def outputs(path: Path) -> tuple[Path, Path]:
    return path.with_suffix(".html"), path.with_suffix(".txt")


def replace(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


def assert_refused(path: Path, capsys: pytest.CaptureFixture[str], expected: str) -> None:
    code = render.main([str(path)])
    err = capsys.readouterr().err
    assert code == 2
    assert expected in err
    assert len(err.strip().splitlines()) == 1
    for out in outputs(path):
        assert not out.exists()


def test_valid_digest_writes_html_and_text_beside_the_markdown(tmp_path: Path) -> None:
    path = write(tmp_path, GOOD)
    assert render.main([str(path)]) == 0
    html, txt = outputs(path)
    assert html.read_text().lstrip().lower().startswith("<!doctype html")
    assert "Tuesday 3 November 2026" in html.read_text()
    assert "Tuesday 3 November 2026" in txt.read_text()


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("# Daily digest — Tuesday", "# Weekly digest — Tuesday", "# Daily digest — "),
        ("Covers: Monday 2 November to Monday 2 November (Claude, Codex, Linear)\n", "", "Covers:"),
        ("## Three concepts\n", "## Ideas\n", "## Three concepts"),
        ("### 3. Worktree pruning", "### 4. Worktree pruning", "exactly three"),
        ("**Check yourself:** Which key does the schema select on?\n", "", "Check yourself"),
        ("2. Finish PAY-415 before Wednesday.\n", "2. a\n3. b\n4. c\n", "1 to 3"),
    ],
)
def test_structure_errors_are_refused_with_one_specific_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], old: str, new: str, expected: str
) -> None:
    path = write(tmp_path, replace(GOOD, old, new))
    assert_refused(path, capsys, expected)


def test_sections_out_of_order_are_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    head, rest = GOOD.split("## Yesterday", 1)
    yesterday, rest = rest.split("## Three concepts", 1)
    concepts, today = rest.split("## Today", 1)
    swapped = f"{head}## Three concepts{concepts}## Yesterday{yesterday}## Today{today}"
    assert_refused(write(tmp_path, swapped), capsys, "order")


def test_today_with_no_items_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = GOOD[: GOOD.index("1. Review")]
    assert_refused(write(tmp_path, text), capsys, "1 to 3")


def pad_to_words(text: str, total: int) -> str:
    current = render.count_words(text)
    return text + "\n" + " ".join(["word"] * (total - current)) + "\n"


def test_word_cap_allows_1000_and_refuses_1001(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = write(tmp_path, pad_to_words(GOOD, 1000), "ok.md")
    assert render.main([str(ok)]) == 0
    big = write(tmp_path, pad_to_words(GOOD, 1001), "big.md")
    assert_refused(big, capsys, "1001")


def test_urls_do_not_count_as_words() -> None:
    assert render.count_words("see https://example.com/a/very/long/path here") == 2


def test_script_tags_are_escaped_in_both_outputs(tmp_path: Path) -> None:
    path = write(tmp_path, replace(GOOD, "- Fixed", "- <script>alert(1)</script> Fixed"))
    assert render.main([str(path)]) == 0
    html = outputs(path)[0].read_text()
    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html


def test_javascript_links_are_not_rendered_as_links(tmp_path: Path) -> None:
    text = replace(GOOD, "- Fixed", "- [click](javascript:alert(1)) and [data](data:text/html,x) Fixed")
    path = write(tmp_path, text)
    assert render.main([str(path)]) == 0
    html = outputs(path)[0].read_text().lower()
    assert "javascript:" not in html.replace("&#x3a;", ":") or 'href="javascript' not in html
    assert 'href="javascript' not in html
    assert 'href="data' not in html
    assert "click" in html


def test_pr_and_linear_urls_get_short_labels(tmp_path: Path) -> None:
    path = write(tmp_path, GOOD)
    assert render.main([str(path)]) == 0
    html, txt = (p.read_text() for p in outputs(path))
    assert ">acme/repo#123</a>" in html
    assert ">PAY-412</a>" in html
    assert 'href="https://github.com/acme/repo/pull/123"' in html
    assert "acme/repo#123 (https://github.com/acme/repo/pull/123)" in txt
    assert "PAY-412 (https://linear.app/acme/issue/PAY-412/webhook)" in txt


def test_markdown_links_become_text_with_url_in_plain_output(tmp_path: Path) -> None:
    path = write(tmp_path, GOOD)
    assert render.main([str(path)]) == 0
    html, txt = (p.read_text() for p in outputs(path))
    assert 'href="https://github.com/acme/repo/pull/18390"' in html
    assert "#18390 (https://github.com/acme/repo/pull/18390)" in txt


def test_every_section_heading_appears_in_both_outputs(tmp_path: Path) -> None:
    path = write(tmp_path, GOOD)
    assert render.main([str(path)]) == 0
    html, txt = (p.read_text() for p in outputs(path))
    for heading in ("Yesterday", "Three concepts", "Today", "Webhook retries", "Idempotent handlers"):
        assert heading.lower() in html.lower()
        assert heading.lower() in txt.lower()
    assert "Check yourself" in html
    assert "Check yourself" in txt


def test_html_is_email_safe(tmp_path: Path) -> None:
    path = write(tmp_path, GOOD)
    assert render.main([str(path)]) == 0
    html = outputs(path)[0].read_text().lower()
    for banned in ("<style", "<script", "<img", "<link", "@import", "@font-face"):
        assert banned not in html
    assert "<table" in html
    assert "#f7f7f5" in html
    assert "#cfe3f5" in html


def test_bold_and_code_render_and_inline_html_is_escaped(tmp_path: Path) -> None:
    path = write(tmp_path, replace(GOOD, "- Fixed", "- **bold** `a<b` Fixed"))
    assert render.main([str(path)]) == 0
    html = outputs(path)[0].read_text()
    assert "<strong" in html
    assert "<code" in html
    assert "a&lt;b" in html


def test_missing_file_is_refused_without_a_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = render.main([str(tmp_path / "nope.md")])
    assert code == 2
    assert "nope.md" in capsys.readouterr().err


def test_bare_urls_in_parentheses_keep_the_closing_parenthesis_outside_the_link() -> None:
    html_out, text_out = render.inline(
        "Merged (https://github.com/acme/repo/pull/241). Next (https://linear.app/acme/issue/PAY-420/backfill)."
    )
    assert ">acme/repo#241</a>)." in html_out
    assert ">PAY-420</a>)." in html_out
    assert 'href="https://github.com/acme/repo/pull/241"' in html_out
    assert "(acme/repo#241 (https://github.com/acme/repo/pull/241))." in text_out
