#!/usr/bin/env python3
"""guard_irreversible: a Claude Code and Codex PreToolUse hook that blocks irreversible agent mistakes.

It reads the hook JSON on stdin and checks each simple command in a Bash tool call:

  - `gh pr merge` must pin the reviewed head with a literal `--match-head-commit <40-hex SHA>`.
    `--admin` and `--auto` are always blocked.
  - `gh api` to `repos/<owner>/<repo>/pulls/<n>/merge` with a method other than GET needs `-f sha=<40-hex SHA>`.
  - `gh api graphql` with `mergePullRequest` or `enqueuePullRequest` needs `expectedHeadOid`.
    `enablePullRequestAutoMerge` is always blocked.
  - `spacectl` may run only read commands (READ_ONLY_SPACECTL).

Allow: exit 0 with no output. Block: exit 2 with the reason on stderr; both agents read this as a block.
It fails closed: bad input or any error blocks the call.
It is a guardrail against mistakes, not a security boundary: shell tricks such as eval or variables get past it.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

PREFIX = "Blocked by the guard_irreversible hook: "
SHELL_TOOLS = frozenset({"Bash", "exec_command", "shell"})
SHA = re.compile(r"[0-9a-fA-F]{40}")
PUNCTUATION = "();<>|&\n"
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = frozenset({"command", "env", "sudo", "time", "nohup", "exec"})
RESERVED_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"})
SHELLS = frozenset({"bash", "sh", "zsh"})
MERGE_ENDPOINT = re.compile(r"(?:https://api\.github\.com)?/?repos/[^/]+/[^/]+/pulls/[^/]+/merge/?")
# gh api flags that take a value. Every other flag is a switch.
GH_API_VALUE_FLAGS = {
    "-X": "method", "--method": "method",
    "-f": "field", "-F": "field", "--field": "field", "--raw-field": "field",
    "--input": "input",
    "-H": None, "--header": None, "-q": None, "--jq": None, "-t": None, "--template": None,
    "--hostname": None, "--cache": None, "-p": None, "--preview": None,
}  # fmt: skip
# spacectl subcommand paths that only read. A command is allowed when one of these is a prefix of its path.
READ_ONLY_SPACECTL = (
    ("version",), ("whoami",), ("profile",), ("completion",),
    ("stack", "list"), ("stack", "show"), ("stack", "logs"), ("stack", "outputs"), ("stack", "changes"),
    ("stack", "open"), ("stack", "run", "list"), ("stack", "environment", "list"), ("stack", "task", "list"),
    ("stack", "resources", "list"), ("stack", "state", "pull"),
)  # fmt: skip

PIN_HINT = (
    "pin the head you reviewed: gh pr merge <number> --squash --match-head-commit "
    "<full 40-character head SHA you reviewed>. A shell variable is not accepted, so the reviewed SHA stays visible."
)


class Blocked(Exception):
    """The reason a command is blocked."""


class BadInput(Exception):
    """The hook input is not what Claude Code or Codex sends."""


def split_segments(command: str) -> list[list[str]]:
    """Split a shell command into simple commands at ;, &&, ||, |, &, parentheses, and newlines."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # A comment would swallow the newline that ends the command before it.
    segments: list[list[str]] = [[]]
    for token in lexer:
        if not token.strip(PUNCTUATION):  # An operator: a redirect such as > or 2>&1 is dropped, the rest split.
            if "<" not in token and ">" not in token:
                segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def strip_wrappers(words: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and wrappers such as env or sudo, with their flags."""
    while words:
        if ASSIGNMENT.match(words[0]) or words[0] in RESERVED_WORDS:
            words = words[1:]
        elif os.path.basename(words[0]) in WRAPPERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        else:
            break
    return words


def strip_gh_repo_flag(args: list[str]) -> list[str]:
    """Drop leading `-R <repo>`, `--repo <repo>`, and `--repo=<repo>` so the subcommand comes first."""
    while args and (args[0] in ("-R", "--repo") or args[0].startswith("--repo=")):
        args = args[1:] if "=" in args[0] else args[2:]
    return args


def option_value(args: list[str], name: str) -> str | None:
    """The value of `--name value` or `--name=value`, or None."""
    for index, arg in enumerate(args):
        if arg == name:
            return args[index + 1] if index + 1 < len(args) else ""
        if arg.startswith(name + "="):
            return arg[len(name) + 1 :]
    return None


def check_pr_merge(args: list[str]) -> None:
    for flag, why in (
        ("--admin", "--admin bypasses branch protection. Ask Marcus to merge it, or"),
        ("--auto", "--auto merges later, at a head nobody reviewed. Wait for the checks, then"),
    ):
        if any(arg == flag or arg.startswith(flag + "=") for arg in args):
            raise Blocked(f"gh pr merge {why} {PIN_HINT}")
    if "--disable-auto" in args or "--help" in args or "-h" in args:
        return
    pin = option_value(args, "--match-head-commit")
    if pin is None or not SHA.fullmatch(pin):
        raise Blocked(f"gh pr merge without a literal --match-head-commit SHA. {PIN_HINT}")


def parse_gh_api(args: list[str]) -> tuple[str, str | None, list[tuple[str, str]], list[str]]:
    """Return (endpoint, explicit method, fields as (key, value), --input files) for `gh api` args."""
    positionals: list[str] = []
    method: str | None = None
    fields: list[tuple[str, str]] = []
    inputs: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if not arg.startswith("-") or arg == "-":
            positionals.append(arg)
            continue
        if arg == "--":
            positionals += args[index:]
            break
        name, value = arg, None
        if arg.startswith("--") and "=" in arg:
            name, value = arg.split("=", 1)
        elif not arg.startswith("--") and len(arg) > 2:
            name, value = arg[:2], arg[2:]
        if name not in GH_API_VALUE_FLAGS:
            continue
        if value is None:
            value = args[index] if index < len(args) else ""
            index += 1
        kind = GH_API_VALUE_FLAGS[name]
        if kind == "method":
            method = value.upper()
        elif kind == "field":
            key, _, field_value = value.partition("=")
            fields.append((key, field_value))
        elif kind == "input":
            inputs.append(value)
    return (positionals[0] if positionals else ""), method, fields, inputs


def read_text(path: str, cwd: Path) -> str:
    """A file's text, relative to cwd, or "" when it cannot be read."""
    try:
        return (cwd / path).read_text(errors="replace")
    except (OSError, ValueError):
        return ""


def check_gh_api(args: list[str], command: str, cwd: Path) -> None:
    endpoint, method, fields, inputs = parse_gh_api(args)
    if endpoint == "graphql":
        files = [path for path in inputs if path != "-"]
        files += [value[1:] for key, value in fields if key == "query" and value.startswith("@") and value != "@-"]
        text = "\n".join([command, *(read_text(path, cwd) for path in files)])
        if "enablePullRequestAutoMerge" in text:
            raise Blocked(
                "enablePullRequestAutoMerge merges later, at a head nobody reviewed. Wait for the checks, then "
                'run mergePullRequest with expectedHeadOid: "<sha>" set to the head you reviewed.'
            )
        if ("mergePullRequest" in text or "enqueuePullRequest" in text) and (
            "expectedHeadOid" not in text or re.search(r"expectedHeadOid\s*:\s*null", text)
        ):
            raise Blocked(
                'a GraphQL merge must pin the head you reviewed: add expectedHeadOid: "<sha>" with the full '
                "40-character head SHA to the mergePullRequest or enqueuePullRequest input."
            )
        return
    if not MERGE_ENDPOINT.fullmatch(endpoint.split("?", 1)[0]):
        return
    method = method or ("POST" if fields or inputs else "GET")
    if method == "GET":
        return
    if any(key == "sha" and SHA.fullmatch(value) for key, value in fields):
        return
    if inputs:
        raise Blocked(
            "a REST merge from an --input file cannot show the pinned head: pass -f sha=<sha> inline "
            "with the full 40-character head SHA you reviewed."
        )
    raise Blocked(
        f"gh api {method} {endpoint} must pin the head you reviewed: "
        "add -f sha=<full 40-character head SHA you reviewed>."
    )


def check_spacectl(args: list[str]) -> None:
    if any(arg in ("--help", "-h", "help") for arg in args):
        return
    while args and args[0].startswith("-"):
        args = args[1:]
    path: list[str] = []
    for arg in args:
        if arg.startswith("-"):
            break
        path.append(arg)
    if not path or any(tuple(path[: len(allowed)]) == allowed for allowed in READ_ONLY_SPACECTL):
        return
    raise Blocked(
        f"spacectl {' '.join(path)} can change infrastructure. Spacelift is read-only for agents: "
        "use a read command such as `spacectl stack show`, and ask Marcus to run this one."
    )


def check_command(command: str, cwd: Path) -> None:
    try:
        segments = split_segments(command)
    except ValueError as error:
        if re.search(r"\b(gh|spacectl)\b", command):
            raise Blocked(f"could not split the command ({error}); fix the quoting and try again.") from None
        return
    for words in segments:
        words = strip_wrappers(words)
        if not words:
            continue
        program, args = os.path.basename(words[0]), words[1:]
        if program == "gh":
            args = strip_gh_repo_flag(args)
        if program in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
            check_command(args[args.index("-c") + 1], cwd)
        elif program == "gh" and args[:2] == ["pr", "merge"]:
            check_pr_merge(args[2:])
        elif program == "gh" and args[:1] == ["api"]:
            check_gh_api(args[1:], command, cwd)
        elif program == "spacectl":
            check_spacectl(args)


def read_input(raw: str) -> tuple[str, str | None, Path]:
    """Return (tool name, command or None, cwd) from the hook JSON."""
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise BadInput(f"stdin is not JSON: {error}") from None
    if not isinstance(data, dict):
        raise BadInput("stdin is not a JSON object")
    tool = data.get("tool_name")
    if not isinstance(tool, str):
        raise BadInput("tool_name is not a string")
    if tool not in SHELL_TOOLS:
        return tool, None, Path.cwd()
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        raise BadInput("tool_input is not an object")
    command = tool_input.get("command")
    if isinstance(command, list) and all(isinstance(word, str) for word in command):
        command = shlex.join(command)
    if not isinstance(command, str):
        raise BadInput("tool_input.command is not a string or a list of strings")
    cwd = data.get("cwd", os.getcwd())
    if not isinstance(cwd, str):
        raise BadInput("cwd is not a string")
    return tool, command, Path(cwd)


def main() -> int:
    try:
        _, command, cwd = read_input(sys.stdin.read())
        if command is not None:
            check_command(command, cwd)
    except BadInput as error:
        print(f"{PREFIX}the hook could not parse its input ({error}), so it blocks the call.", file=sys.stderr)
        return 2
    except Blocked as reason:
        print(f"{PREFIX}{reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as error:  # Fail closed: an exit code other than 2 lets the call through.
        print(f"{PREFIX}the hook failed ({type(error).__name__}: {error}), so it blocks the call.", file=sys.stderr)
        sys.exit(2)
