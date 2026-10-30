import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import log

RUN = "LOG run | ticket=ENG-1 | sessions=session_a | prs="
RUN_UPDATE = "LOG run | ticket=ENG-1 | sessions=session_a, session_b | prs=https://github.com/o/r/pull/1"
FRICTION = "LOG friction | category=permission | what=gh auth expired | fix=add gh to preflight | at=gh pr view"
FRICTION_PIPE = "  LOG friction | category=doc | what=grep a | b failed | fix=document rg | at=step 3"


class ParseLineTests(unittest.TestCase):
    def test_run_line_with_empty_prs(self):
        self.assertEqual(
            log.parse_line(RUN),
            {"kind": "run", "ticket": "ENG-1", "sessions": ["session_a"], "prs": []},
        )

    def test_run_update_line_lists_every_session_and_pr(self):
        self.assertEqual(
            log.parse_line(RUN_UPDATE),
            {
                "kind": "run",
                "ticket": "ENG-1",
                "sessions": ["session_a", "session_b"],
                "prs": ["https://github.com/o/r/pull/1"],
            },
        )

    def test_friction_line(self):
        self.assertEqual(
            log.parse_line(FRICTION),
            {
                "kind": "friction",
                "category": "permission",
                "what": "gh auth expired",
                "fix": "add gh to preflight",
                "at": "gh pr view",
            },
        )

    def test_pipe_inside_value_is_kept(self):
        entry = log.parse_line(FRICTION_PIPE)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["what"], "grep a | b failed")
        self.assertEqual(entry["fix"], "document rg")
        self.assertEqual(entry["at"], "step 3")

    def test_missing_field_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "missing.*at"):
            log.parse_line("LOG friction | category=doc | what=x | fix=y")

    def test_unknown_field_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "unknown.*extra"):
            log.parse_line(FRICTION + " | extra=1")

    def test_empty_required_value_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "empty.*ticket"):
            log.parse_line("LOG run | ticket= | sessions=s | prs=")

    def test_unknown_kind_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "kind.*decision"):
            log.parse_line("LOG decision | what=x")

    def test_non_log_lines_return_none(self):
        for line in ("ran the tests", "LOGGING x", "`LOG run | ticket=x | sessions=s | prs=`", ""):
            with self.subTest(line=line):
                self.assertIsNone(log.parse_line(line))


class ParseLinesTests(unittest.TestCase):
    def test_mixed_block_returns_only_log_entries_in_order(self):
        block = ["Starting work.", RUN, "Ran checks.", FRICTION, RUN_UPDATE, "done"]
        self.assertEqual(
            log.parse_lines(block),
            [log.parse_line(RUN), log.parse_line(FRICTION), log.parse_line(RUN_UPDATE)],
        )
        self.assertEqual([entry["kind"] for entry in log.parse_lines(block)], ["run", "friction", "run"])


class CliTests(unittest.TestCase):
    def test_malformed_line_exits_1_and_prints_no_entries(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.txt"
            path.write_text(f"{RUN}\nLOG friction | category=doc | what=x | fix=y\n", encoding="utf-8")
            with (
                patch("sys.stdout", new_callable=StringIO) as stdout,
                patch("sys.stderr", new_callable=StringIO) as stderr,
            ):
                exit_code = log.main([str(path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("error: line 2:", stderr.getvalue())
        self.assertIn("at", stderr.getvalue().split("error: line 2:", 1)[1])
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
