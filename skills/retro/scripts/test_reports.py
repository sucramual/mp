import json
import os
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import reports


def report(
    *,
    created: str = "2026-11-03",
    topic: str = "Matrix preview demo",
    findings: str | None = None,
    sessions: str | None = None,
) -> str:
    if sessions is None:
        sessions = (
            "| Session | App link | Transcript |\n"
            "| --- | --- | --- |\n"
            "| aaaa1111 | claude://claude.ai/epitaxy/local_aaaa | ~/.claude/projects/p/aaaa1111.jsonl |\n"
        )
    if findings is None:
        findings = (
            "### 1. The PR gate fails without a bound ticket\n\n"
            "- target: tool:agent-trace\n"
            "- kind: failure\n"
            "- cost: 10 failed calls\n"
            '- evidence: aaaa1111, 19:35:40Z, "no ticket bound"\n'
            "- fix: bind the ticket at intake\n\n"
            "### 2. The wait loop never matched\n\n"
            "- target: skill:neo\n"
            "- kind: stall\n"
            "- cost: 10 min idle\n"
            '- evidence: aaaa1111, 19:41:49Z, "test(review)"\n'
            "- fix: one tested waiter\n"
        )
    return (
        "---\n"
        f"created: {created}\n"
        f"topic: {topic}\n"
        "skills: matrix, neo\n"
        "tickets: WO-3\n"
        "sessions: aaaa1111\n"
        "---\n\n"
        f"# Retro {created}: {topic}\n\n"
        "## Sessions\n\n"
        f"{sessions}\n"
        "## Findings\n\n"
        f"{findings}"
    )


def finding(target: str, kind: str, title: str = "A finding") -> str:
    return (
        f"### 1. {title}\n\n"
        f"- target: {target}\n"
        f"- kind: {kind}\n"
        "- cost: 1 wake\n"
        '- evidence: aaaa1111, 10:00:00Z, "quote"\n'
        "- fix: change one line\n"
    )


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        code = reports.main(argv)
    return code, out.getvalue(), err.getvalue()


class ParseReportTests(unittest.TestCase):
    def test_valid_report_gives_its_fields_and_findings(self):
        parsed = reports.parse_report(report())

        self.assertEqual(parsed["created"], "2026-11-03")
        self.assertEqual(parsed["skills"], ["matrix", "neo"])
        self.assertEqual(parsed["sessions"], ["aaaa1111"])
        self.assertEqual(
            [(f["number"], f["target"], f["kind"]) for f in parsed["findings"]],
            [(1, "tool:agent-trace", "failure"), (2, "skill:neo", "stall")],
        )
        self.assertEqual(parsed["findings"][1]["title"], "The wait loop never matched")

    def test_finding_without_a_fix_is_rejected(self):
        text = report(findings=finding("skill:neo", "stall").replace("- fix: change one line\n", ""))
        with self.assertRaisesRegex(ValueError, r"finding 1: missing key: fix"):
            reports.parse_report(text)

    def test_unknown_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"finding 1: unknown kind: slow"):
            reports.parse_report(report(findings=finding("skill:neo", "slow")))

    def test_target_without_a_known_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"finding 1: target must be <type>:<name>"):
            reports.parse_report(report(findings=finding("neo", "stall")))

    def test_report_without_session_rows_is_rejected(self):
        empty_table = "| Session | App link | Transcript |\n| --- | --- | --- |\n"
        with self.assertRaisesRegex(ValueError, r"Sessions table has no rows"):
            reports.parse_report(report(sessions=empty_table))

    def test_report_without_findings_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"no findings"):
            reports.parse_report(report(findings=""))

    def test_bad_created_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"created must be YYYY-MM-DD"):
            reports.parse_report(report(created="3 Nov 2026"))


class SaveTests(unittest.TestCase):
    def test_save_copies_the_report_under_its_date_and_topic(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp, "draft.md")
            source.write_text(report(), encoding="utf-8")
            store = Path(tmp, "store")

            code, out, _ = run(["--dir", str(store), "save", str(source)])

            saved = store / "2026-11-03-matrix-preview-demo.md"
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), str(saved))
            self.assertEqual(saved.read_text(encoding="utf-8"), report())

    def test_second_save_with_the_same_name_keeps_the_first(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp, "store")
            first, second = Path(tmp, "a.md"), Path(tmp, "b.md")
            first.write_text(report(), encoding="utf-8")
            second.write_text(report(findings=finding("guide:shell", "failure")), encoding="utf-8")

            run(["--dir", str(store), "save", str(first)])
            code, out, _ = run(["--dir", str(store), "save", str(second)])

            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), str(store / "2026-11-03-matrix-preview-demo-2.md"))
            self.assertEqual((store / "2026-11-03-matrix-preview-demo.md").read_text(encoding="utf-8"), report())

    def test_invalid_report_is_not_saved(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp, "draft.md")
            source.write_text(report(findings=finding("skill:neo", "slow")), encoding="utf-8")
            store = Path(tmp, "store")

            code, out, err = run(["--dir", str(store), "save", str(source)])

            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("unknown kind: slow", err)
            self.assertEqual(list(store.glob("*")) if store.exists() else [], [])


class PatternTests(unittest.TestCase):
    def write(self, store: Path, name: str, created: str, findings: str) -> None:
        store.mkdir(parents=True, exist_ok=True)
        (store / name).write_text(report(created=created, topic=name, findings=findings), encoding="utf-8")

    def test_groups_findings_by_target_and_kind_across_runs(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            self.write(store, "a.md", "2026-11-01", finding("tool:agent-trace", "failure", "Gate blocks PR"))
            self.write(store, "b.md", "2026-11-02", finding("tool:agent-trace", "failure", "Gate blocks again"))
            self.write(store, "c.md", "2026-11-03", finding("guide:shell", "failure", "zsh equals"))

            code, out, _ = run(["--dir", str(store), "patterns", "--json"])

            groups = json.loads(out)
            self.assertEqual(code, 0)
            self.assertEqual(
                [(g["target"], g["kind"], g["runs"], g["seen_once"]) for g in groups],
                [("tool:agent-trace", "failure", 2, False), ("guide:shell", "failure", 1, True)],
            )
            self.assertEqual([f["title"] for f in groups[0]["findings"]], ["Gate blocks again", "Gate blocks PR"])

    def test_last_keeps_the_newest_reports_by_created_date(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            # File names sort the other way round, so only the created date can give this order.
            self.write(store, "z-old.md", "2026-10-01", finding("tool:agent-trace", "failure"))
            self.write(store, "a-new.md", "2026-11-03", finding("guide:shell", "failure"))

            code, out, _ = run(["--dir", str(store), "patterns", "--last", "1", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual([g["target"] for g in json.loads(out)], ["guide:shell"])

    def test_text_output_marks_a_one_run_pattern_as_seen_once(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            self.write(store, "a.md", "2026-11-03", finding("guide:shell", "failure", "zsh equals"))

            code, out, _ = run(["--dir", str(store), "patterns"])

            self.assertEqual(code, 0)
            row = next(line for line in out.splitlines() if "guide:shell" in line)
            self.assertIn("seen once", row)

    def test_malformed_report_in_the_store_stops_with_its_name(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            self.write(store, "good.md", "2026-11-03", finding("guide:shell", "failure"))
            (store / "bad.md").write_text("no frontmatter\n", encoding="utf-8")

            code, out, err = run(["--dir", str(store), "patterns"])

            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("bad.md", err)

    def test_empty_store_reports_no_retros(self):
        with TemporaryDirectory() as tmp:
            code, out, _ = run(["--dir", tmp, "patterns"])

            self.assertEqual(code, 0)
            self.assertIn("no retro reports", out)


class StoreDirTests(unittest.TestCase):
    def test_default_store_is_dot_retro_in_the_repository_root(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RETRO_DIR", None)
            store = reports.store_dir(None)

        self.assertEqual(store.name, ".retro")
        self.assertTrue((store.parent / "skills" / "retro" / "SKILL.md").is_file())

    def test_retro_dir_overrides_the_default(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"RETRO_DIR": tmp}):
            self.assertEqual(reports.store_dir(None), Path(tmp))


if __name__ == "__main__":
    unittest.main()
