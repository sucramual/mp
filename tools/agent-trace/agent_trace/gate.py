"""`agent-trace gate`: a PreToolUse PR-creation gate for Claude Code and Codex.

In a session that ran the /neo skill, it blocks `gh pr create` until the session has a ticket bound for its trace.
A /neo worker that skipped agent-trace left its ticket with no trace and no reconcile list (retro, 2026-11-02).
A session ran /neo when its transcript holds a Skill tool call for `neo` or a `/neo` slash command.

Block: exit 2 with the reason on stderr. Allow: exit 0 with no output.
It fails open: a missing transcript, bad input, or any error allows the call, so a bug never blocks unrelated PRs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from agent_trace import emit, store
from agent_trace.hook import SHELL_TOOLS

SLASH_COMMAND = "<command-name>/neo</command-name>"
# `gh pr create` anywhere in the call, also in echoed, quoted, or commented text. A false block is cheap: it fires
# only in a /neo session with no ticket, and its fix is the step that session owes anyway. Parsing shell syntax
# missed real calls three times in review (newline, comment, comment after a newline), so the gate does not parse.
PR_CREATE = re.compile(r"\bgh\b(?:\s+(?:-R|--repo)(?:=|\s+)\S+)?\s+pr\s+create\b")
REASON = (
    "agent-trace gate: this /neo session has no ticket bound for its trace, so it cannot open a PR yet. "
    'Run `agent-trace span start --id run --name "neo run" --kind phase --ticket <ID>` first, with the ticket '
    "from the work order, or the work-order ID (such as WO-5) when it names no ticket. Then run gh pr create again."
)


def ran_neo(transcript: Path) -> bool:
    """True when the transcript holds a Skill tool call for neo or a /neo slash command."""
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if SLASH_COMMAND not in line and '"Skill"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") if isinstance(record, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            # A typed slash command is a user prompt with string content. Tool output is a list, so quoted text
            # in a file that the session read does not count.
            if record.get("type") == "user" and isinstance(content, str) and content.startswith(SLASH_COMMAND):
                return True
            for item in content if isinstance(content, list) else []:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_use"
                    and item.get("name") == "Skill"
                    and isinstance(item.get("input"), dict)
                    and item["input"].get("skill") == "neo"
                ):
                    return True
    return False


def blocks(payload: dict[str, Any]) -> bool:
    if payload.get("tool_name") not in SHELL_TOOLS:
        return False
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if not isinstance(command, str) or "gh" not in command:
        return False
    if not PR_CREATE.search(command):
        return False
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else emit.session_id()
    ticket = os.environ.get("AGENT_TRACE_TICKET") or store.read_ticket(store.state_dir(), session)
    if ticket and emit.TICKET.match(ticket):
        return False
    transcript = payload.get("transcript_path")
    return isinstance(transcript, str) and Path(transcript).is_file() and ran_neo(Path(transcript))


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else None
    if isinstance(payload, dict) and blocks(payload):
        print(REASON, file=sys.stderr)
        return 2
    return 0
