import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import replay_file


def call(name: str, result: str | None = "ok", call_id: str = "c", **args: object) -> str:
    """One transcript line. `result` is "ok", "error", or None for a call with no tool_result."""
    content: list[dict] = [{"type": "tool_use", "id": call_id, "name": name, "input": args}]
    if result is not None:
        content.append({"type": "tool_result", "tool_use_id": call_id, "is_error": result == "error"})
    return json.dumps({"message": {"role": "assistant", "content": content}})


class ReplayTests(unittest.TestCase):
    def test_write_then_edits_give_the_last_version(self):
        lines = [
            call("Write", file_path="/tmp/s/plan.md", content="a\nb\nb\n"),
            call("Edit", file_path="/tmp/s/plan.md", old_string="a", new_string="A"),
            call("Edit", file_path="/tmp/s/plan.md", old_string="b", new_string="B", replace_all=True),
        ]
        result = replay_file.replay(lines, "plan.md")
        self.assertEqual(result.text, "A\nB\nB\n")
        self.assertEqual((result.applied, result.unmatched), (3, 0))

    def test_a_later_write_replaces_the_text(self):
        lines = [
            call("Write", file_path="/x/plan.md", content="old"),
            call("Write", file_path="/x/plan.md", content="new"),
        ]
        self.assertEqual(replay_file.replay(lines, "plan.md").text, "new")

    def test_an_edit_that_does_not_match_is_counted(self):
        lines = [
            call("Write", file_path="/x/plan.md", content="one"),
            call("Edit", file_path="/x/plan.md", old_string="two", new_string="2"),
        ]
        result = replay_file.replay(lines, "plan.md")
        self.assertEqual(result.text, "one")
        self.assertEqual(result.unmatched, 1)

    def test_a_failed_or_unanswered_call_is_not_replayed(self):
        lines = [
            call("Write", call_id="w", file_path="/x/plan.md", content="Status: pending\nStatus: pending\n"),
            call(
                "Edit",
                result="error",
                call_id="e1",
                file_path="/x/plan.md",
                old_string="Status: pending",
                new_string="Status: complete",
            ),
            call(
                "Edit",
                result=None,
                call_id="e2",
                file_path="/x/plan.md",
                old_string="Status: pending",
                new_string="Status: done",
            ),
        ]
        result = replay_file.replay(lines, "plan.md")
        self.assertEqual(result.text, "Status: pending\nStatus: pending\n")
        self.assertEqual((result.applied, result.unmatched, result.unconfirmed), (1, 0, 2))

    def test_other_files_and_bad_lines_are_ignored(self):
        lines = [
            "not json",
            json.dumps(["a list"]),
            call("Write", file_path="/x/other.md", content="no"),
            call("Write", file_path="/x/plan.md", content="yes"),
        ]
        self.assertEqual(replay_file.replay(lines, "plan.md").text, "yes")

    def test_no_write_returns_none_and_main_exits_1(self):
        with TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text(call("Edit", file_path="/x/plan.md", old_string="a", new_string="b") + "\n")
            self.assertIsNone(replay_file.replay(transcript.read_text().splitlines(), "plan.md").text)
            self.assertEqual(replay_file.main([str(transcript), "plan.md"]), 1)

    def test_main_writes_the_out_file(self):
        with TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "t.jsonl"
            out = Path(tmp) / "plan.md"
            transcript.write_text(call("Write", file_path="/s/plan.md", content="body") + "\n")
            self.assertEqual(replay_file.main([str(transcript), "plan.md", "--out", str(out)]), 0)
            self.assertEqual(out.read_text(), "body")


if __name__ == "__main__":
    unittest.main()
