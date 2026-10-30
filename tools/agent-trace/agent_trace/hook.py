"""`agent-trace hook`: a PostToolUse hook for Claude Code and Codex that records `gh pr create` and `gh pr merge`.

Reads the hook JSON on stdin. Acts only for shell tools (Bash, shell, exec_command, local_shell) whose command holds
the tokens `gh pr create` or `gh pr merge`. Records one zero-length span `agent_trace.pr` with one event
(`pr.create` or `pr.merge`), through the same send-or-fallback path as `span` and `note`, but silently.

PR URL: the first GitHub pull URL in the tool's stdout, else in the command, else built from the `gh pr merge`
argument and `--repo/-R`. Head SHA: `--match-head-commit` for a merge; `git -C <cwd> rev-parse HEAD` for a create.
The merge commit SHA is not in the hook input; `show` asks GitHub for it.

Never fails: every error is swallowed, nothing is printed, and the exit code is 0.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from typing import Any

from agent_trace import emit, otlp, store

SHELL_TOOLS = {"Bash", "shell", "exec_command", "local_shell"}
PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&"}
# gh pr merge flags that take a value. Every other flag is a switch.
VALUE_FLAGS = {"--match-head-commit", "-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject"}
VALUE_FLAGS |= {"-A", "--author-email"}
SEARCH_LIMIT = 1_000_000
STDERR_LIMIT = 200


def tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def find_action(words: list[str]) -> tuple[str, list[str]] | None:
    """Return (create|merge, the words after it up to the next shell separator)."""
    for index in range(len(words) - 2):
        if words[index] == "gh" and words[index + 1] == "pr" and words[index + 2] in ("create", "merge"):
            rest = []
            for word in words[index + 3 :]:
                if word in SEPARATORS:
                    break
                rest.append(word)
            return words[index + 2], rest
    return None


def parse_flags(words: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    flags: dict[str, str] = {}
    index = 0
    while index < len(words):
        word = words[index]
        if word.startswith("-") and "=" in word:
            key, value = word.split("=", 1)
            flags[key] = value
        elif word in VALUE_FLAGS and index + 1 < len(words):
            flags[word] = words[index + 1]
            index += 1
        elif not word.startswith("-"):
            positional.append(word)
        index += 1
    return positional, flags


def repo_from_flag(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.removeprefix("https://").strip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def head_of(cwd: Any) -> str | None:
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def build_attrs(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("tool_name") not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        command = " ".join(shlex.quote(str(part)) for part in command)
    if not isinstance(command, str) or "gh" not in command:
        return None
    found = find_action(tokens(command))
    if found is None:
        return None
    action, rest = found
    response = payload.get("tool_response")
    if isinstance(response, dict):
        stdout, stderr = response.get("stdout"), response.get("stderr")
    else:
        stdout, stderr = response, None
    stdout = stdout if isinstance(stdout, str) else ""
    stderr = stderr if isinstance(stderr, str) else ""
    positional, flags = parse_flags(rest)
    flag_repo = repo_from_flag(flags.get("-R") or flags.get("--repo"))
    match = PR_URL.search(stdout[:SEARCH_LIMIT]) or PR_URL.search(command)
    attrs: dict[str, Any] = {"agent_trace.pr_action": action}
    if match:
        attrs["agent_trace.pr_url"] = match.group(0)
        attrs["agent_trace.repo"] = match.group(1)
        attrs["agent_trace.pr_ref"] = match.group(2)
    elif action == "merge" and positional:
        ref = positional[0]
        attrs["agent_trace.pr_ref"] = ref
        if flag_repo:
            attrs["agent_trace.repo"] = flag_repo
            if ref.isdigit():
                attrs["agent_trace.pr_url"] = f"https://github.com/{flag_repo}/pull/{ref}"
    elif flag_repo:
        attrs["agent_trace.repo"] = flag_repo
    head = flags.get("--match-head-commit") if action == "merge" else head_of(payload.get("cwd"))
    if head:
        attrs["agent_trace.head_sha"] = head
    if isinstance(payload.get("tool_use_id"), str):
        attrs["agent_trace.tool_use_id"] = payload["tool_use_id"]
    if not PR_URL.search(stdout[:SEARCH_LIMIT]) and stderr.strip():
        attrs["agent_trace.stderr"] = stderr.strip()[:STDERR_LIMIT]
    return attrs


def main() -> None:
    import json

    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else None
    if not isinstance(payload, dict):
        return
    attrs = build_attrs(payload)
    if attrs is None:
        return
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
    session = session or emit.session_id()
    base = store.state_dir()
    bound = store.read_ticket(base, session)
    ticket = bound if bound and emit.TICKET.match(bound) else None
    context = emit.Context(ticket, session, otlp.parse_traceparent(os.environ.get("TRACEPARENT")))
    if context.scope is None:
        return
    record = emit.span_record(
        context,
        span_id=otlp.random_span_id(),
        name="agent_trace.pr",
        parent=context.traceparent[1] if context.traceparent else None,
        attrs=attrs,
        event=f"pr.{attrs['agent_trace.pr_action']}",
    )
    emit.deliver([record], base, quiet=True)
