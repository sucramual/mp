#!/usr/bin/env python3
"""Turn saved agent transcripts into a compact timeline of the moments a retro needs.

Reads saved claude-code-remote ``list_events`` pages (the saved MCP wrapper, ``{"ccr": ...}``, or
``{"data": [...]}``) or a local Claude Code session ``.jsonl`` file. Several pages of one session may be passed;
events are deduplicated and sorted by time.

Marks: failing tool calls (grouped), permission waits, gaps between events, loops (the same call repeated),
turns that ended with "no action needed", and the ``LOG `` lines that earlier runs wrote in assistant text,
before agent-trace.
Prints compact text, or one JSON object with ``--json``.
Exits 2 with one stderr line when a file cannot be read or holds no recognisable events.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

QUOTE_LIMIT = 160
TURN_TEXT_LIMIT = 80
LOG_LINE_LIMIT = 300
LOOP_MIN = 3
MAX_GROUP_LABELS = 5
NOOP_RE = re.compile(
    r"no action (is )?(needed|required)|nothing (else )?to (do|change)|no (further )?action (is )?necessary"
    r"|needs? no action|nothing to act on|taking no action",
    re.IGNORECASE,
)
EXIT_CODE_RE = re.compile(r"^Exit code -?\d+$")
# A line of tool output that reports an error. Matched on the stripped line. Prose that only mentions a status,
# such as "GitHub returns HTTP 403 with", must not match.
ERROR_LINE_RE = re.compile(
    r"\(HTTP [45]\d\d\)|^(?:HTTP [45]\d\d:|fatal:|ERROR:|error:|gh: )|Permission for this action was denied"
)
BASH_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
# Digit runs that vary between repeats of one error, such as request numbers. A status after "HTTP " stays, so
# an HTTP 403 and an HTTP 500 are two causes.
HTTP_STATUS_OR_NUMBER_RE = re.compile(r"(?<!HTTP )\b\d+")
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A fail is recovered when one of this many next tool calls is the same call (the same tool and the same input) and
# succeeds. The label is too short to tell operations apart: `python3 -m pytest` and `python3 -m json.tool` share it.
RECOVER_WINDOW = 3
DENIED_RE = re.compile(r"^Permission for this action was denied by the (?:Claude Code |server-side )?auto mode")
DENIED_REASON_RE = re.compile(r"Reason: \[([^\]]+)\]")
HOOK_RE = re.compile(r"^(?:\w+:\w+ )?hook error: (?:\[([^\]]*)\]|([^:\n]+)):")
# One session in a linked-sessions reminder: its name and its state, such as `ch2 = local_ab12 (done, PR #7)`.
LINKED_RE = re.compile(r"([\w.-]+) = local_[\w-]+ \(([^)]*)\)")
PEER_RE = re.compile(r'<cross-session-message[^>]*\bfrom-name="([^"]*)"')
BASH_INPUT_RE = re.compile(r"^<bash-input>(.*?)</bash-input>", re.DOTALL)
# A notice that the harness queued into the same record as a prompt command, ahead of it.
NOTICE_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
BEFORE_CALLS = 3  # the tool calls kept before each event, so /retro sees what led to it


class InputError(Exception):
    """A file that cannot be read or holds no recognisable events."""


@dataclass
class Event:
    """One kept transcript event, normalised across input formats."""

    time: datetime
    kind: str  # user, assistant, result, perm_request, perm_answer
    body: dict[str, Any]
    key: str


@dataclass
class Report:
    session: str
    start: str
    end: str
    fails: list[dict[str, Any]] = field(default_factory=list)
    fail_groups: list[dict[str, Any]] = field(default_factory=list)
    perms: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    loops: list[dict[str, Any]] = field(default_factory=list)
    noops: list[dict[str, Any]] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    interventions: list[dict[str, Any]] = field(default_factory=list)  # messages and prompt commands that Marcus typed


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def short(text: str, limit: int = QUOTE_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Loading


def load_cloud_object(text: str) -> list[dict[str, Any]] | None:
    """Return the ``data`` list from a saved list_events page, or None if the text is not one."""
    candidates = []
    start = text.find('{"ccr"')
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text.strip())
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("ccr"), dict):
            obj = obj["ccr"]
        if isinstance(obj, dict) and isinstance(obj.get("data"), list):
            return obj["data"]
    return None


def cloud_events(data: list[Any], sessions: list[str]) -> list[Event]:
    events = []
    for raw in data:
        if not isinstance(raw, dict) or "created_at" not in raw:
            continue
        kinds = [key for key in raw if key != "created_at"]
        if len(kinds) != 1:
            continue
        kind = kinds[0]
        wrapper = raw[kind] if isinstance(raw[kind], dict) else {}
        body = wrapper.get("internal_anthropic_catchall") or {}
        if not isinstance(body, dict):
            continue
        uuid = wrapper.get("uuid") or body.get("uuid")
        kept = classify_cloud(kind, body)
        if kept is None:
            continue
        if kept == "result" and isinstance(body.get("session_id"), str):
            sessions.append(body["session_id"])
        key = uuid or f"{raw['created_at']}|{kind}|{json.dumps(raw, sort_keys=True)}"
        events.append(Event(parse_time(raw["created_at"]), kept, body, key))
    return events


def classify_cloud(kind: str, body: dict[str, Any]) -> str | None:
    """Map a cloud event kind to a kept kind, or None for harness noise."""
    if kind in ("user", "assistant", "result"):
        return kind
    if kind == "control_request":
        request = body.get("request") or {}
        return "perm_request" if request.get("subtype") == "can_use_tool" else None
    if kind == "control_response":
        response = body.get("response") or {}
        inner = response.get("response") or {}
        if not isinstance(inner, dict) or "pending_permission_requests" in inner:
            return None
        return "perm_answer" if "behavior" in inner and response.get("request_id") else None
    return None


def local_events(lines: list[str], sessions: list[str]) -> list[Event]:
    events = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") not in ("user", "assistant") or "timestamp" not in obj:
            continue
        if isinstance(obj.get("sessionId"), str):
            sessions.append(obj["sessionId"])
        key = obj.get("uuid") or f"{obj['timestamp']}|{obj['type']}|{json.dumps(obj, sort_keys=True)}"
        message = obj.get("message") or {}
        time = parse_time(obj["timestamp"])
        body: dict[str, Any] = {"message": message}
        origin = obj.get("turnOrigin") or (obj.get("origin") or {}).get("kind")
        if isinstance(origin, str):
            body["origin"] = origin  # who wrote a user message: human, host_synthetic, peer, task_notification
        if obj.get("isMeta") is True:
            body["meta"] = True  # text that the harness added, such as a loaded skill
        if obj.get("isApiErrorMessage") is True:
            body["api_error"] = True  # an assistant record that the harness wrote for a failed API call
        events.append(Event(time, obj["type"], body, key))
        if obj["type"] == "assistant" and message.get("stop_reason") == "end_turn":
            # A local transcript has no result event. The end of a turn is the message that stops with end_turn.
            text = "\n".join(
                str(block.get("text") or "")
                for block in message.get("content") or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
            events.append(Event(time, "result", {"result": text}, f"{key}|result"))
    return events


def is_local_line(line: str) -> bool:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict) and "type" in obj and "timestamp" in obj


def load_file(path: Path, sessions: list[str]) -> list[Event]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"cannot read {path}: {error}") from error
    events: list[Event] = []
    data = load_cloud_object(text)
    if data is not None:
        events = cloud_events(data, sessions)
    else:
        # A local file may start with lines that have no timestamp (summary), so check the first few lines.
        lines = text.splitlines()
        if any(is_local_line(line) for line in lines[:20] if line.strip()):
            events = local_events(lines, sessions)
    if not events:
        raise InputError(f"no recognisable transcript events in {path}")
    return events


# ---------------------------------------------------------------------------
# Analysis


def content_blocks(event: Event) -> list[dict[str, Any]]:
    message = event.body.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def user_text(event: Event) -> str | None:
    message = event.body.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    texts = [block.get("text", "") for block in content_blocks(event) if block.get("type") == "text"]
    return " ".join(texts) if texts else None


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return ""


def matching_error_line(text: str) -> str | None:
    """Return the first line of tool output that has an error shape, or None."""
    for line in text.splitlines():
        line = line.strip()
        if line and ERROR_LINE_RE.search(line):
            return short(line)
    return None


def error_line(text: str) -> str:
    matched = matching_error_line(text)
    if matched is not None:
        return matched
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if not EXIT_CODE_RE.match(line):
            return short(line)
    return short(lines[0]) if lines else ""


def bash_words(command: str) -> list[str]:
    """Return the words of the first segment that runs a command, skipping cd, export, and assignments."""
    for segment in BASH_SPLIT_RE.split(command):
        words = segment.split()
        while words and ASSIGNMENT_RE.match(words[0]):
            words = words[1:]
        if not words or words[0] in ("cd", "export"):
            continue
        if words[0] == "timeout" and len(words) > 2 and words[1].rstrip("smhd").replace(".", "").isdigit():
            words = words[2:]
        words[0] = words[0].rsplit("/", 1)[-1] or words[0]
        return words
    return command.split()


def tool_label(name: str, tool_input: Any) -> str:
    if name == "Bash" and isinstance(tool_input, dict):
        words = bash_words(str(tool_input.get("command", "")))[:2]
        return f"Bash({' '.join(words)})" if words else "Bash"
    return name


def block_of(output: str) -> dict[str, str] | None:
    """What blocked a failed call: an auto-mode denial (with its reason) or a hook (with its name), or None.

    Only the first line that is not an `Exit code` line counts, so output that quotes a block message later
    does not look like one.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip() and not EXIT_CODE_RE.match(line.strip())]
    first = lines[0] if lines else ""
    if DENIED_RE.match(first):
        reason = DENIED_REASON_RE.search(output)
        return {"by": "auto mode", "name": reason.group(1) if reason else ""}
    hook = HOOK_RE.match(first)
    if hook is None:
        return None
    if hook.group(2):
        return {"by": "hook", "name": hook.group(2).strip()}
    words = (hook.group(1) or "").split()
    at = next((i for i, word in enumerate(words) if "/" in word), None)
    if at is None:
        return {"by": "hook", "name": " ".join(words)}
    script = words[at].rsplit("/", 1)[-1].removesuffix(".py")
    return {"by": "hook", "name": " ".join([script, *words[at + 1 :]])}


def ended_by(event: Event) -> str | None:
    """What kind of event ended a gap: a message that a person typed, a peer session, a background task, a status
    reminder about linked sessions, or the summary after a compaction. None for anything else, such as a tool result.
    """
    if event.kind != "user" or any(block.get("type") == "tool_result" for block in content_blocks(event)):
        return None
    text = (user_text(event) or "").lstrip()
    if not text:
        return None
    if "<cross-session-message" in text:
        return "peer"  # A message from another session, alone or after a linked-sessions reminder.
    if text.startswith("<task-notification>"):
        return "background"
    if text.startswith("<system-reminder>") and "Linked sessions now" in text[:200]:
        return "linked"
    if text.startswith("This session is being continued"):
        return "compaction"
    if text.startswith(("<", "[")):
        return None  # Other harness text, such as a command or a reminder.
    return "user"


def linked_states(text: str) -> dict[str, str]:
    """The state of each session in a linked-sessions reminder, by session name; empty for other text."""
    return dict(LINKED_RE.findall(text)) if "Linked sessions now" in text[:300] else {}


def woke_by(event: Event, kind: str | None, linked: dict[str, str]) -> str:
    """Who the event that ended a gap came from: the peer session's name, or the linked sessions whose state changed
    since the last reminder (`linked`). Empty when the event does not say."""
    text = user_text(event) or ""
    if kind == "peer":
        peer = PEER_RE.search(text)
        return peer.group(1) if peer else ""
    if kind == "linked":
        now = linked_states(text)
        return "; ".join(f"{name} ({state})" for name, state in now.items() if linked.get(name) != state)
    return ""


def pointer(event: Event) -> str:
    """The transcript UUID of an event, or "" when its record has none."""
    return "" if "|" in event.key else event.key


def prompt_command(text: str) -> dict[str, str] | None:
    """A command that Marcus ran from the prompt (`! cmd`): its program, its PR for `gh pr merge`, and the first
    output line. Command text past the program is never kept. None for any other text."""
    found = BASH_INPUT_RE.match(NOTICE_RE.sub("", text).lstrip())
    if found is None:
        return None
    words = bash_words(found.group(1))
    program = " ".join(words[:3]) if words[:1] == ["gh"] else " ".join(words[:1])
    command = {"program": program}
    if program == "gh pr merge":
        args = [w for w in words[3:] if not w.startswith("-")]
        repo = next((words[i + 1] for i, w in enumerate(words[:-1]) if w in ("--repo", "-R")), "")
        target = next((a for a in args if a != repo), "")
        if target.startswith("https://github.com/"):
            command["pr"] = target
        elif target.isdigit() and repo:
            command["pr"] = f"https://github.com/{repo}/pull/{target}"
        head = next((words[i + 1] for i, w in enumerate(words[:-1]) if w == "--match-head-commit"), "")
        if re.fullmatch(r"[0-9a-f]{7,40}", head):
            command["head"] = head
    stdout = re.search(r"<bash-stdout>(.*?)</bash-stdout>", text, re.DOTALL)
    stderr = re.search(r"<bash-stderr>(.*?)</bash-stderr>", text, re.DOTALL)
    out = stdout.group(1).strip() if stdout else ""
    err = stderr.group(1).strip() if stderr else ""
    if out:
        command["result"] = short(out.splitlines()[0])
    elif err:
        command["error"] = short(err.splitlines()[0])  # no output but an error: the command failed
    return command


def assistant_text(event: Event) -> str:
    """The text of an assistant message, or of a turn's result, without its tool calls."""
    if event.kind == "result":
        return str(event.body.get("result") or "")
    if event.kind != "assistant":
        return ""
    return user_text(event) or ""


def same_call(one: tuple[str, Any] | None, other: tuple[str, Any] | None) -> bool:
    """The same tool with the same input, such as a test run that is run again after a fix."""
    if one is None or other is None:
        return False
    return one[0] == other[0] and json.dumps(one[1], sort_keys=True) == json.dumps(other[1], sort_keys=True)


def analyse(events: list[Event], session: str, gap_minutes: float) -> Report:
    report = Report(session=session, start=iso(events[0].time), end=iso(events[-1].time))
    tool_uses: dict[str, tuple[str, Any]] = {}
    calls: list[str] = []  # tool_use ids in call order
    errored: dict[str, bool] = {}  # tool_use id -> its result was an error
    # The current run of identical consecutive tool calls in this turn: (name, canonical input, times).
    run: list[Any] = [None, None, []]

    def flush_run() -> None:
        name, canonical, times = run
        if name is not None and len(times) >= LOOP_MIN:
            report.loops.append(
                {
                    "label": tool_label(name, json.loads(canonical)),
                    "tool": name,
                    "count": len(times),
                    "input": short(canonical),
                    "first": iso(times[0]),
                    "last": iso(times[-1]),
                }
            )
        run[:] = [None, None, []]

    answers = {
        str((event.body.get("response") or {}).get("request_id")): event
        for event in events
        if event.kind == "perm_answer"
    }
    open_perms: dict[str, datetime] = {}  # request_id -> time the wait ends
    in_turn = False
    previous: Event | None = None
    said = ""  # the last assistant text so far: what a message from Marcus after it answers
    linked: dict[str, str] = {}  # the session states of the last linked-sessions reminder

    def before(ident: str | None = None) -> list[str]:
        """The labels of the last tool calls before a call (`ident`), or before now."""
        upto = calls.index(ident) if ident in calls else len(calls)
        return [tool_label(*tool_uses[c]) for c in calls[max(0, upto - BEFORE_CALLS) : upto]]

    for index, event in enumerate(events):
        if event.kind == "user":
            typed = user_text(event) or ""
            origin = event.body.get("origin")
            # The transcript says who wrote a message (`turnOrigin`); older transcripts do not, so the kind of text
            # decides there. A brief that another session sent to start this one is not Marcus's.
            # A record that Marcus wrote can also hold a notice that the harness queued, which makes it look like
            # another kind of event; `turnOrigin` decides.
            command = prompt_command(typed) if origin == "human" or (origin is None and not ended_by(event)) else None
            human = origin == "human" if origin else ended_by(event) == "user" and not event.body.get("meta")
            if command or (human and ended_by(event) == "user"):
                item: dict[str, Any] = {"time": iso(event.time), "uuid": pointer(event)}
                item["kind"] = "command" if command else "message"
                item.update(command or {"text": short(typed)})
                item["asked"] = short(said) if said else ""
                item["wait_seconds"] = (event.time - previous.time).total_seconds() if previous else 0
                item["before"] = before()
                report.interventions.append(item)
        if previous is not None:
            seconds = (event.time - previous.time).total_seconds()
            if seconds > gap_minutes * 60:
                pending = any(started_end > previous.time for started_end in open_perms.values())
                report.gaps.append(
                    {
                        "start": iso(previous.time),
                        "end": iso(event.time),
                        "gap_seconds": seconds,
                        "in_turn": in_turn,
                        "cause": "permission" if pending else None,
                        # The gap follows a tool call: the time is the call running, not idle.
                        "after_tool_use": previous.kind == "assistant"
                        and any(block.get("type") == "tool_use" for block in content_blocks(previous)),
                        "quote": describe(previous),
                        "ended_by": ended_by(event),
                        "woke_by": woke_by(event, ended_by(event), linked),
                        "end_uuid": pointer(event),
                        "before": before(),
                    }
                )

        if event.kind == "user":
            text = user_text(event)
            if text is not None and not any(b.get("type") == "tool_result" for b in content_blocks(event)):
                in_turn = True
                flush_run()
                report.turns.append({"time": iso(event.time), "quote": short(text, TURN_TEXT_LIMIT)})
            for block in content_blocks(event):
                if block.get("type") != "tool_result":
                    continue
                output = result_text(block.get("content"))
                errored[str(block.get("tool_use_id"))] = block.get("is_error") is True
                soft = block.get("is_error") is not True
                if soft:
                    error = matching_error_line(output)
                    if error is None:
                        continue
                else:
                    error = error_line(output)
                name, tool_input = tool_uses.get(str(block.get("tool_use_id")), ("?", None))
                report.fails.append(
                    {
                        "time": iso(event.time),
                        "uuid": pointer(event),
                        "before": before(str(block.get("tool_use_id"))),
                        "tool": name,
                        "label": tool_label(name, tool_input),
                        "tool_use_id": block.get("tool_use_id"),
                        "input": short(json.dumps(tool_input, sort_keys=True)) if tool_input is not None else "",
                        "error": error,
                        "soft": soft,
                        "block": None if soft else block_of(output),
                    }
                )
        elif event.kind == "assistant":
            for block in content_blocks(event):
                if block.get("type") == "tool_use":
                    name = str(block.get("name", "?"))
                    tool_input = block.get("input")
                    tool_uses[str(block.get("id"))] = (name, tool_input)
                    calls.append(str(block.get("id")))
                    canonical = json.dumps(tool_input, sort_keys=True)
                    if (run[0], run[1]) != (name, canonical):
                        flush_run()
                        run[0], run[1] = name, canonical
                    run[2].append(event.time)
                elif block.get("type") == "text":
                    # Tagged lines that earlier runs wrote, before agent-trace. Another tool parses them.
                    for line in str(block.get("text") or "").splitlines():
                        line = line.strip()
                        if line.startswith("LOG "):
                            report.logs.append({"time": iso(event.time), "line": line[:LOG_LINE_LIMIT]})
        elif event.kind == "result":
            in_turn = False
            flush_run()
            text = str(event.body.get("result") or "")
            if NOOP_RE.search(text):
                report.noops.append({"time": iso(event.time), "quote": short(text)})
        elif event.kind == "perm_request":
            request = event.body.get("request") or {}
            request_id = str(event.body.get("request_id"))
            answer = answers.get(request_id)
            if answer is not None and answer.time >= event.time:
                inner = (answer.body.get("response") or {}).get("response") or {}
                ends, answered_at, behavior = answer.time, iso(answer.time), inner.get("behavior")
            else:
                later = events[index + 1 :]
                ends = later[0].time if later else event.time
                answered_at, behavior = None, None
            open_perms[request_id] = ends
            report.perms.append(
                {
                    "time": iso(event.time),
                    "tool": request.get("tool_name"),
                    "tool_use_id": request.get("tool_use_id"),
                    "request_id": request_id,
                    "answered_at": answered_at,
                    "behavior": behavior,
                    "unanswered": answered_at is None,
                    "wait_seconds": (ends - event.time).total_seconds(),
                    "quote": short(f"{request.get('tool_name')} {json.dumps(request.get('input'), sort_keys=True)}"),
                }
            )
        if not event.body.get("api_error"):
            said = assistant_text(event).strip() or said
        if ended_by(event) in ("user", "peer"):
            said = ""  # A reply answered it, so a later message does not answer the same text.
        if event.kind == "user":
            linked = linked_states(user_text(event) or "") or linked
        previous = event

    flush_run()
    order = {ident: index for index, ident in enumerate(calls)}
    for fail in report.fails:
        ident = str(fail["tool_use_id"])
        call = tool_uses.get(ident)
        later = calls[order[ident] + 1 :] if ident in order and call is not None else []
        fail["recovered"] = any(
            same_call(tool_uses[other], call) and other in errored and not errored[other]
            for other in later[:RECOVER_WINDOW]
        )
    report.fail_groups = group_fails(report.fails)
    report.loops.sort(key=lambda loop: (-loop["count"], loop["first"]))
    return report


def group_fails(fails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group fails by error text with digit runs replaced, across tools: one cause often breaks many commands."""
    groups: dict[str, dict[str, Any]] = {}
    for fail in fails:
        key = HTTP_STATUS_OR_NUMBER_RE.sub("N", fail["error"])
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "labels": [fail["label"]],
                "error": fail["error"],
                "pattern": key,
                "count": 1,
                "first": fail["time"],
                "last": fail["time"],
                "repeated": False,
            }
        else:
            group["count"] += 1
            group["last"] = fail["time"]
            if fail["label"] not in group["labels"] and len(group["labels"]) < MAX_GROUP_LABELS:
                group["labels"].append(fail["label"])
            group["repeated"] = True
    return sorted(groups.values(), key=lambda group: (-group["count"], group["first"]))


def describe(event: Event) -> str:
    if event.kind == "user":
        text = user_text(event)
        if text is not None:
            return short(text)
        ids = [str(b.get("tool_use_id")) for b in content_blocks(event) if b.get("type") == "tool_result"]
        return short("tool_result " + " ".join(ids))
    if event.kind == "assistant":
        parts = []
        for block in content_blocks(event):
            if block.get("type") == "tool_use":
                parts.append(f"tool_use {block.get('name')}")
            elif block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
        return short(" | ".join(parts) or "assistant")
    if event.kind == "result":
        return short(f"result: {event.body.get('result') or ''}")
    if event.kind == "perm_request":
        return short(f"permission request {(event.body.get('request') or {}).get('tool_name')}")
    return short(f"permission answer {(event.body.get('response') or {}).get('request_id')}")


# ---------------------------------------------------------------------------
# Output


def as_json(report: Report) -> dict[str, Any]:
    return {
        "session": report.session,
        "start": report.start,
        "end": report.end,
        "fail_groups": report.fail_groups,
        "fails": report.fails,
        "perms": report.perms,
        "gaps": report.gaps,
        "interventions": report.interventions,
        "loops": report.loops,
        "noops": report.noops,
        "logs": report.logs,
    }


def clock(value: str) -> str:
    return value[11:19] + "Z"


def minutes(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.0f}m" if seconds < 3600 else f"{seconds / 3600:.1f}h"


def as_text(report: Report, gap_minutes: float) -> str:
    out = [
        f"session {report.session}  {report.start} -> {report.end}  "
        f"fails={len(report.fails)} groups={len(report.fail_groups)} perms={len(report.perms)} "
        f"gaps={len(report.gaps)} loops={len(report.loops)} noops={len(report.noops)} logs={len(report.logs)}",
        "",
        "Summary",
    ]
    for group in report.fail_groups:
        tag = "REPEATED " if group["repeated"] else ""
        out.append(
            f"  {tag}fail x{group['count']} {', '.join(group['labels'])}: {group['error']}"
            f"  ({clock(group['first'])}..{clock(group['last'])})"
        )
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for perm in report.perms:
        by_tool.setdefault(str(perm["tool"]), []).append(perm)
    for tool, perms in sorted(by_tool.items(), key=lambda item: -sum(p["wait_seconds"] for p in item[1])):
        waits = [perm["wait_seconds"] for perm in perms]
        unanswered = sum(1 for perm in perms if perm["unanswered"])
        out.append(
            f"  perms {tool} x{len(perms)} total {minutes(sum(waits))} longest {minutes(max(waits))}"
            f" unanswered {unanswered}"
        )
        for perm in perms:
            if perm["wait_seconds"] >= gap_minutes * 60:
                state = "UNANSWERED" if perm["unanswered"] else perm["behavior"]
                out.append(f"    perm {tool} waited {minutes(perm['wait_seconds'])} {state} at {clock(perm['time'])}")
    for loop in report.loops:
        out.append(f"  loop x{loop['count']} {loop['label']} {loop['input']}")
    out.append(f"  noops: {len(report.noops)}")
    out.extend(["", "Timeline"])

    rows: list[tuple[str, str, str]] = []
    rows += [(turn["time"], "TURN", turn["quote"]) for turn in report.turns]
    rows += [(fail["time"], "FAIL", f"{fail['label']}: {fail['error']}") for fail in report.fails]
    for perm in report.perms:
        state = "unanswered" if perm["unanswered"] else f"{perm['behavior']} at {clock(perm['answered_at'])}"
        rows.append((perm["time"], "PERM", f"{perm['tool']} waited {minutes(perm['wait_seconds'])}, {state}"))
    for gap in report.gaps:
        where = "stall in turn" if gap["in_turn"] else "idle between turns"
        cause = ", waiting on permission" if gap["cause"] == "permission" else ""
        rows.append((gap["start"], "GAP", f"{minutes(gap['gap_seconds'])} {where}{cause}; last before: {gap['quote']}"))
    rows += [(loop["first"], "LOOP", f"x{loop['count']} {loop['label']} {loop['input']}") for loop in report.loops]
    rows += [(noop["time"], "NOOP", noop["quote"]) for noop in report.noops]
    rows += [(log["time"], "LOG", log["line"]) for log in report.logs]
    for time, kind, details in sorted(rows, key=lambda row: row[0]):
        out.append(f"{clock(time)}  {kind:<4}  {details}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    parser.add_argument("--session", help="label for the report (default: session id from the data)")
    parser.add_argument("--gap-minutes", type=float, default=10.0, help="report gaps longer than this (default 10)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)

    sessions: list[str] = []
    merged: dict[str, Event] = {}
    try:
        for path in args.files:
            for event in load_file(path, sessions):
                merged.setdefault(event.key, event)
    except InputError as error:
        print(f"timeline.py: {error}", file=sys.stderr)
        return 2

    events = sorted(merged.values(), key=lambda event: event.time)
    session = args.session or (sessions[0] if sessions else args.files[0].stem)
    report = analyse(events, session, args.gap_minutes)
    if args.json:
        print(json.dumps(as_json(report), indent=1))
    else:
        print(as_text(report, args.gap_minutes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
