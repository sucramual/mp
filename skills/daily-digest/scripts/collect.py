#!/usr/bin/env python3
"""Collect a compact JSON summary of one workday from local agent logs.

Sources: Claude Code history and transcripts, and Codex sessions.
The output goes to stdout and stays under about 40 KB. Secrets are redacted.
Use `collect.py concepts add "<name>"` to record a concept that the digest already explained.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_BYTES = 40_000
MAX_PROMPTS_PER_WORKSTREAM = 8
MAX_PROMPT_CHARS = 240
CONCEPT_MEMORY_DAYS = 60
SELF_MARKER = "[daily-digest]"
REDACTED = "[redacted]"

PR_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
LINEAR_TEXT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,9})-(\d{1,6})(?![A-Za-z0-9])")
LINEAR_BRANCH_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,6})(?![A-Za-z0-9])")
NOT_ISSUE_PREFIXES = frozenset(
    "UTF ISO SHA HTTP HTTPS SSE CVE RFC ADR GPT AES RSA TLS SSL MD PR IPV TCP UDP WCAG EC ES TS GA CP FIX FEAT "
    "CHORE DOCS TEST V UTC PST PDT NODE PYTHON EN ECMA OAUTH SOC HS RS ED X K".split()
)

SECRET_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])(?:ghp|gho)_[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
]
LONG_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/_.-])[A-Za-z0-9+/]{32,}={0,2}(?![A-Za-z0-9+/_.-])")
HEX_RE = re.compile(r"[0-9a-fA-F]+")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")

NOISE_PREFIXES = ("<local-command", "<system-reminder", "Caveat:", "[Request interrupted")


# --- small helpers -------------------------------------------------------------------------------------------------


def parse_ts(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def parse_user_datetime(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=PACIFIC)


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(PACIFIC).isoformat(timespec="seconds") if moment else None


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                # api-request records embed whole system prompts, so never parse them.
                if not line or line.startswith('{"type":"api-request'):
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def mtime_before(path: Path, since: datetime) -> bool:
    try:
        return path.stat().st_mtime < since.timestamp()
    except OSError:
        return True


def looks_like_secret_run(run: str) -> bool:
    if not any(ch.isdigit() for ch in run):
        return False
    if GIT_SHA_RE.fullmatch(run):
        return False
    if HEX_RE.fullmatch(run):
        return True
    return any(ch.isupper() for ch in run) and any(ch.islower() for ch in run)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return LONG_RUN_RE.sub(lambda m: REDACTED if looks_like_secret_run(m.group(0)) else m.group(0), text)


def clean_prompt(text: str) -> str:
    flat = redact(" ".join(text.split()))
    return flat if len(flat) <= MAX_PROMPT_CHARS else flat[: MAX_PROMPT_CHARS - 1] + "…"


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def add_links(text: str, prs: list[str], issues: list[str] | None) -> None:
    """Collect PR URLs from any text. Collect Linear keys only when the caller passes `issues` (Marcus's own words)."""
    for url in PR_URL_RE.findall(text):
        add_unique(prs, url)
    if issues is None:
        return
    for prefix, number in LINEAR_TEXT_RE.findall(text):
        if prefix not in NOT_ISSUE_PREFIXES:
            add_unique(issues, f"{prefix}-{number}")


def add_branch_issues(branch: str | None, issues: list[str]) -> None:
    for prefix, number in LINEAR_BRANCH_RE.findall(branch or ""):
        if prefix.upper() not in NOT_ISSUE_PREFIXES:
            add_unique(issues, f"{prefix.upper()}-{number}")


_repo_cache: dict[str, str] = {}


def repo_name(cwd: str | None) -> str:
    """Name the repository that holds cwd. A worktree resolves to its main repository."""
    if not cwd:
        return "unknown"
    cached = _repo_cache.get(cwd)
    if cached is not None:
        return cached
    start = Path(cwd)
    name = start.name or "unknown"
    for candidate in (start, *start.parents):
        git = candidate / ".git"
        if git.is_dir():
            name = candidate.name
            break
        if git.is_file():
            try:
                first_line = git.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, IndexError):
                first_line = ""
            gitdir = first_line.removeprefix("gitdir:").strip()
            marker = "/.git/worktrees/"
            name = Path(gitdir.split(marker)[0]).name if marker in gitdir else candidate.name
            break
    _repo_cache[cwd] = name
    return name


def is_under(path_text: str | None, root: Path) -> bool:
    if not path_text:
        return False
    path = Path(path_text)
    if path.is_relative_to(root):
        return True
    return path.resolve().is_relative_to(root.resolve())


# --- data model ----------------------------------------------------------------------------------------------------


@dataclass
class Window:
    since: datetime
    until: datetime

    def contains(self, moment: datetime | None) -> bool:
        return moment is not None and self.since <= moment < self.until


@dataclass
class Session:
    id: str
    source: str
    cwd: str | None = None
    branch: str | None = None
    title: str | None = None
    custom_title: str | None = None
    first: datetime | None = None
    last: datetime | None = None
    prompts: list[tuple[datetime, str]] = field(default_factory=list)
    prs: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def touch(self, moment: datetime) -> None:
        if self.first is None or moment < self.first:
            self.first = moment
        if self.last is None or moment > self.last:
            self.last = moment

    def merge(self, other: Session) -> None:
        """Fold a second copy of the same session into this one."""
        known = set(self.prompts)
        self.prompts.extend(item for item in other.prompts if item not in known)
        for url in other.prs:
            add_unique(self.prs, url)
        for key in other.issues:
            add_unique(self.issues, key)
        for moment in (other.first, other.last):
            if moment is not None:
                self.touch(moment)
        self.cwd = self.cwd or other.cwd
        self.branch = self.branch or other.branch
        self.title = self.title or other.title
        self.custom_title = self.custom_title or other.custom_title

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "title": redact(self.custom_title or self.title or "") or None,
            "first": iso(self.first),
            "last": iso(self.last),
            "prompt_count": len(self.prompts),
        }
        return {key: value for key, value in out.items() if value is not None}


def compute_window(args: argparse.Namespace, now: datetime) -> Window:
    today = now.astimezone(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    default_since = today - timedelta(days=3 if today.weekday() == 0 else 1)
    since = parse_user_datetime(args.since) if args.since else default_since
    until = parse_user_datetime(args.until) if args.until else today
    return Window(since, until)


# --- Claude Code ---------------------------------------------------------------------------------------------------


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"] for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def human_prompt_text(rec: dict[str, Any]) -> str | None:
    if rec.get("isMeta"):
        return None
    origin = rec.get("origin")
    if origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human"):
        return None
    message = rec.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    text = text_of(content).strip()
    if not text or text.startswith(NOISE_PREFIXES):
        return None
    return text


def read_claude_session(path: Path, window: Window, scheduled_root: Path) -> Session | None:
    session = Session(id=path.stem, source="claude")
    seen_first_prompt = False
    for rec in iter_jsonl(path):
        kind = rec.get("type")
        if rec.get("isSidechain"):
            continue
        if kind in ("custom-title", "ai-title"):
            if kind == "custom-title" and isinstance(rec.get("customTitle"), str):
                session.custom_title = rec["customTitle"]
            elif kind == "ai-title" and isinstance(rec.get("aiTitle"), str):
                session.title = rec["aiTitle"]
            continue
        moment = parse_ts(rec.get("timestamp"))
        if session.cwd is None and isinstance(rec.get("cwd"), str):
            session.cwd = rec["cwd"]
            if is_under(session.cwd, scheduled_root):
                return None
        if kind == "pr-link":
            if window.contains(moment) and isinstance(rec.get("prUrl"), str):
                add_unique(session.prs, rec["prUrl"])
            continue
        if kind not in ("user", "assistant"):
            continue
        prompt = human_prompt_text(rec) if kind == "user" else None
        if prompt is not None and not seen_first_prompt:
            seen_first_prompt = True
            if prompt.startswith(SELF_MARKER):
                return None
        if not window.contains(moment) or moment is None:
            continue
        if session.branch is None and isinstance(rec.get("gitBranch"), str):
            session.branch = rec["gitBranch"]
        session.touch(moment)
        if prompt is not None:
            session.prompts.append((moment, clean_prompt(prompt)))
            add_links(prompt, session.prs, session.issues)
        elif kind == "assistant":
            message = rec.get("message")
            add_links(text_of(message.get("content")) if isinstance(message, dict) else "", session.prs, None)
    if session.last is None:
        return None
    add_branch_issues(session.branch, session.issues)
    add_links(f"{session.custom_title or ''} {session.title or ''}", session.prs, session.issues)
    return session


def read_claude_history(path: Path, window: Window, scheduled_root: Path, covered: set[str]) -> list[Session]:
    rows: dict[tuple[str, str], list[tuple[datetime, str]]] = {}
    all_first: dict[tuple[str, str], str] = {}
    for rec in iter_jsonl(path):
        display, project = rec.get("display"), rec.get("project")
        moment = parse_ts(rec.get("timestamp"))
        if not isinstance(display, str) or moment is None:
            continue
        sid = rec.get("sessionId") if isinstance(rec.get("sessionId"), str) else ""
        key = (str(sid), str(project or ""))
        all_first.setdefault(key, display)
        if window.contains(moment):
            rows.setdefault(key, []).append((moment, display))
    sessions: list[Session] = []
    for (sid, project), entries in rows.items():
        if sid in covered or is_under(project, scheduled_root) or all_first[(sid, project)].startswith(SELF_MARKER):
            continue
        session = Session(id=sid or f"history:{len(sessions)}", source="claude-history", cwd=project or None)
        for moment, display in entries:
            if not display.strip():
                continue
            session.touch(moment)
            session.prompts.append((moment, clean_prompt(display)))
            add_links(display, session.prs, session.issues)
        if session.prompts:
            sessions.append(session)
    return sessions


# --- Codex ---------------------------------------------------------------------------------------------------------


def read_codex_session(path: Path, window: Window, scheduled_root: Path) -> Session | None:
    session = Session(id=path.stem, source="codex")
    seen_first_prompt = False
    for rec in iter_jsonl(path):
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = rec.get("type")
        if kind == "session_meta":
            if isinstance(payload.get("id"), str):
                session.id = payload["id"]
            if isinstance(payload.get("cwd"), str):
                session.cwd = payload["cwd"]
                if is_under(session.cwd, scheduled_root):
                    return None
            git = payload.get("git")
            if isinstance(git, dict) and isinstance(git.get("branch"), str):
                session.branch = git["branch"]
            continue
        if kind != "event_msg":
            continue
        moment = parse_ts(rec.get("timestamp"))
        prompt: str | None = None
        other_text = ""
        item = payload.get("item")
        if payload.get("type") == "user_message" and isinstance(payload.get("message"), str):
            prompt = payload["message"]
        elif payload.get("type") == "item_completed" and isinstance(item, dict):
            text = text_of(item.get("content")) or (item.get("text") if isinstance(item.get("text"), str) else "")
            if item.get("type") == "UserMessage":
                prompt = text
            else:
                other_text = text
        prompt = prompt.strip() if prompt else None
        if prompt and not seen_first_prompt:
            seen_first_prompt = True
            if prompt.startswith(SELF_MARKER):
                return None
        if not window.contains(moment) or moment is None:
            continue
        if prompt:
            session.touch(moment)
            session.prompts.append((moment, clean_prompt(prompt)))
            add_links(prompt, session.prs, session.issues)
        elif other_text:
            add_links(other_text, session.prs, None)
    if session.last is None:
        return None
    add_branch_issues(session.branch, session.issues)
    return session


# --- concept memory ------------------------------------------------------------------------------------------------


def default_state_file() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "daily-digest" / "concepts.json"


def load_concepts(path: Path) -> list[dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {"name": item["name"], "date": item["date"]}
        for item in data
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("date"), str)
    ]


def recent_concepts(path: Path, today: str) -> list[str]:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=CONCEPT_MEMORY_DAYS)).date().isoformat()
    seen: dict[str, str] = {}
    for item in load_concepts(path):
        if item["date"] >= cutoff:
            seen.setdefault(item["name"].casefold(), item["name"])
    return list(seen.values())


def run_concepts(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="collect.py concepts")
    parser.add_argument("action", choices=["add"])
    parser.add_argument("names", nargs="+")
    parser.add_argument("--state-file")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = parse_user_datetime(args.now) if args.now else datetime.now(PACIFIC)
    today = now.astimezone(PACIFIC).date().isoformat()
    path = Path(args.state_file) if args.state_file else default_state_file()
    items = load_concepts(path)
    for name in args.names:
        if not any(i["name"].casefold() == name.casefold() and i["date"] == today for i in items):
            items.append({"name": name, "date": today})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    return 0


# --- assembly ------------------------------------------------------------------------------------------------------


def build_workstreams(sessions: list[Session]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Session]] = {}
    for session in sessions:
        groups.setdefault((repo_name(session.cwd), session.branch or ""), []).append(session)
    workstreams: list[dict[str, Any]] = []
    for (repo, branch), members in groups.items():
        members.sort(key=lambda s: s.first or datetime.min.replace(tzinfo=UTC))
        prs: list[str] = []
        issues: list[str] = []
        prompts: list[tuple[datetime, str]] = []
        for member in members:
            for url in member.prs:
                add_unique(prs, url)
            for key in member.issues:
                add_unique(issues, key)
            prompts.extend(member.prompts)
        prompts.sort(key=lambda p: p[0])
        workstreams.append(
            {
                "repo": repo,
                "branch": branch or None,
                "sessions": [m.summary() for m in members],
                "prs": prs,
                "issues": issues,
                "prompts": [text for _, text in prompts[:MAX_PROMPTS_PER_WORKSTREAM]],
                "prompt_count": len(prompts),
            }
        )
    workstreams.sort(key=lambda w: (-w["prompt_count"], -len(w["sessions"]), w["repo"]))
    return workstreams


def render(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def fit_to_size(result: dict[str, Any]) -> None:
    """Cut prompts first, then the smallest workstreams, until the output fits."""

    def too_big() -> bool:
        return len(render(result).encode("utf-8")) > MAX_BYTES

    if not too_big():
        return
    result["truncated"] = True
    workstreams: list[dict[str, Any]] = result["workstreams"]
    for cap in (6, 4, 3, 2, 1, 0):
        for workstream in workstreams:
            workstream["prompts"] = workstream["prompts"][:cap]
        if not too_big():
            return
    omitted = 0
    while workstreams and too_big():
        workstreams.pop()
        omitted += 1
        result["omitted_workstreams"] = omitted


def run_digest(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Summarise one workday of agent activity as JSON.")
    parser.add_argument("--since", help="ISO 8601 window start (default: previous workday, Pacific)")
    parser.add_argument("--until", help="ISO 8601 window end")
    parser.add_argument("--now", help="ISO 8601 current time, for tests")
    parser.add_argument("--claude-home", default=str(Path.home() / ".claude"))
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    parser.add_argument(
        "--state-file", help="Concept memory file (default: $XDG_STATE_HOME/daily-digest/concepts.json)"
    )
    args = parser.parse_args(argv)

    now = parse_user_datetime(args.now) if args.now else datetime.now(PACIFIC)
    window = compute_window(args, now)
    claude_home, codex_home = Path(args.claude_home), Path(args.codex_home)
    scheduled_root = claude_home / "scheduled-tasks"
    missing: list[str] = []
    sessions: list[Session] = []
    covered: set[str] = set()
    claude_by_id: dict[str, Session] = {}

    projects = claude_home / "projects"
    if projects.is_dir():
        for path in sorted(projects.glob("*/*.jsonl")):
            covered.add(path.stem)
            if mtime_before(path, window.since):
                continue
            session = read_claude_session(path, window, scheduled_root)
            if not session:
                continue
            # Claude Code keeps copies of one session under several project directories.
            twin = claude_by_id.get(session.id)
            if twin:
                twin.merge(session)
            else:
                claude_by_id[session.id] = session
                sessions.append(session)
    else:
        missing.append("claude_projects")

    history = claude_home / "history.jsonl"
    if history.is_file():
        sessions.extend(read_claude_history(history, window, scheduled_root, covered))
    else:
        missing.append("claude_history")

    codex_sessions = codex_home / "sessions"
    if codex_sessions.is_dir():
        for path in sorted(codex_sessions.rglob("*.jsonl")):
            if mtime_before(path, window.since):
                continue
            session = read_codex_session(path, window, scheduled_root)
            if session:
                sessions.append(session)
    else:
        missing.append("codex_sessions")

    state_file = Path(args.state_file) if args.state_file else default_state_file()
    result: dict[str, Any] = {
        "window": {
            "since": iso(window.since),
            "until": iso(window.until),
            "timezone": "America/Los_Angeles",
        },
        "workstreams": build_workstreams(sessions),
        "recent_concepts": recent_concepts(state_file, now.astimezone(PACIFIC).date().isoformat()),
        "missing_sources": sorted(missing),
        "truncated": False,
    }
    fit_to_size(result)
    print(render(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "concepts":
        return run_concepts(args[1:])
    return run_digest(args)


if __name__ == "__main__":
    raise SystemExit(main())
