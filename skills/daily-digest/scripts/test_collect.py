"""Black-box tests for collect.py. Each test builds a synthetic log tree in tmp_path and reads the JSON output."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import collect
import pytest

SINCE = "2026-10-27T00:00:00-07:00"
UNTIL = "2026-10-28T00:00:00-07:00"
IN_WINDOW = "2026-10-27T17:00:00.000Z"  # 10:00 Pacific on Tuesday
BEFORE_WINDOW = "2026-10-26T17:00:00.000Z"
AFTER_WINDOW = "2026-10-28T17:00:00.000Z"


class Env:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.claude = root / "claude"
        self.codex = root / "codex"
        self.state = root / "state" / "concepts.json"
        self.repos = root / "repos"

    def args(self, *extra: str) -> list[str]:
        return [
            "--claude-home",
            str(self.claude),
            "--codex-home",
            str(self.codex),
            "--state-file",
            str(self.state),
            "--since",
            SINCE,
            "--until",
            UNTIL,
            *extra,
        ]

    def repo(self, name: str) -> Path:
        path = self.repos / name
        (path / ".git").mkdir(parents=True, exist_ok=True)
        return path

    def claude_session(
        self,
        session_id: str,
        cwd: Path | str,
        records: list[dict[str, Any]],
        *,
        branch: str = "main",
        mtime: datetime | None = None,
    ) -> Path:
        project = self.claude / "projects" / str(cwd).replace("/", "-")
        project.mkdir(parents=True, exist_ok=True)
        path = project / f"{session_id}.jsonl"
        lines = []
        for rec in records:
            full = {"sessionId": session_id, "cwd": str(cwd), "gitBranch": branch, "isSidechain": False, **rec}
            lines.append(json.dumps(full))
        path.write_text("\n".join(lines) + "\n")
        stamp = (mtime or datetime.fromisoformat(IN_WINDOW.replace("Z", "+00:00"))).timestamp()
        os.utime(path, (stamp, stamp))
        return path


def user(text: str, ts: str = IN_WINDOW, **extra: Any) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
        "origin": {"kind": "human"},
        **extra,
    }


def assistant(text: str, ts: str = IN_WINDOW, **extra: Any) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        **extra,
    }


def run(env: Env, *extra: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()
    code = collect.main(env.args(*extra))
    out = capsys.readouterr().out
    assert code == 0
    return json.loads(out)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def all_prompts(result: dict[str, Any]) -> list[str]:
    return [p for ws in result["workstreams"] for p in ws["prompts"]]


def test_monday_window_covers_friday_to_monday_in_pacific(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    collect.main(
        ["--claude-home", str(env.claude), "--codex-home", str(env.codex)]
        + ["--state-file", str(env.state), "--now", "2026-10-26T06:00:00-07:00"]
    )
    window = json.loads(capsys.readouterr().out)["window"]
    assert datetime.fromisoformat(window["since"]) == datetime.fromisoformat("2026-10-23T00:00:00-07:00")
    assert datetime.fromisoformat(window["until"]) == datetime.fromisoformat("2026-10-26T00:00:00-07:00")


def test_tuesday_window_covers_only_the_previous_day(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    # 13:30 UTC is 06:30 Pacific on Tuesday.
    collect.main(
        ["--claude-home", str(env.claude), "--codex-home", str(env.codex)]
        + ["--state-file", str(env.state), "--now", "2026-10-27T13:30:00+00:00"]
    )
    window = json.loads(capsys.readouterr().out)["window"]
    assert datetime.fromisoformat(window["since"]) == datetime.fromisoformat("2026-10-26T00:00:00-07:00")
    assert datetime.fromisoformat(window["until"]) == datetime.fromisoformat("2026-10-27T00:00:00-07:00")


def test_prompts_outside_the_window_are_excluded(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    env.claude_session(
        "s1",
        repo,
        [user("before the window", BEFORE_WINDOW), user("inside the window"), user("after the window", AFTER_WINDOW)],
        mtime=datetime.fromisoformat(AFTER_WINDOW.replace("Z", "+00:00")),
    )
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["inside the window"]
    assert result["workstreams"][0]["sessions"][0]["prompt_count"] == 1


def test_session_files_untouched_since_before_the_window_are_skipped(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = env.repo("alpha")
    env.claude_session("old", repo, [user("old work")], mtime=datetime.fromisoformat("2026-10-01T00:00:00+00:00"))
    env.claude_session("new", repo, [user("new work")])
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["new work"]


def test_history_prompts_fill_in_when_a_transcript_is_missing(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    env.claude.mkdir(parents=True)
    rows = [
        {"display": "typed yesterday", "timestamp": 1792000000000, "project": str(repo), "sessionId": "gone"},
        {"display": "typed long ago", "timestamp": 1700000000000, "project": str(repo), "sessionId": "gone"},
    ]
    # 1792000000 s is 2026-10-14; pin the window around it.
    (env.claude / "history.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    capsys.readouterr()
    collect.main(env.args()[:-4] + ["--since", "2026-10-14T00:00:00-07:00", "--until", "2026-10-15T00:00:00-07:00"])
    result = json.loads(capsys.readouterr().out)
    assert all_prompts(result) == ["typed yesterday"]
    assert result["workstreams"][0]["repo"] == "alpha"


def test_pr_urls_and_linear_keys_are_extracted_and_deduplicated(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    pr = "https://github.com/acme/alpha/pull/12"
    env.claude_session(
        "s1",
        repo,
        [
            user(f"look at {pr} and ENG-123 and https://linear.app/acme/issue/COR-9/some-title"),
            assistant(f"Opened {pr}. Also see ENG-123."),
            {"type": "pr-link", "prNumber": 12, "prUrl": pr, "prRepository": "acme/alpha", "timestamp": IN_WINDOW},
        ],
        branch="feat/x",
    )
    env.claude_session("s2", repo, [user(f"again {pr}")], branch="feat/x")
    ws = run(env, capsys=capsys)["workstreams"]
    assert len(ws) == 1
    assert ws[0]["branch"] == "feat/x"
    assert len(ws[0]["sessions"]) == 2
    assert ws[0]["prs"] == [pr]
    assert sorted(ws[0]["issues"]) == ["COR-9", "ENG-123"]


def test_worktree_resolves_to_the_main_repository_name(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    main_repo = env.repo("app")
    (main_repo / ".git" / "worktrees" / "app-06").mkdir(parents=True)
    wt = env.repos / "app-06"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main_repo}/.git/worktrees/app-06\n")
    env.claude_session("s1", wt, [user("in a worktree")], branch="feat/y")
    assert run(env, capsys=capsys)["workstreams"][0]["repo"] == "app"


def test_scheduled_task_sessions_are_excluded(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    task_dir = env.claude / "scheduled-tasks" / "weekly-check"
    task_dir.mkdir(parents=True)
    env.claude_session("sched", task_dir, [user("scheduled prompt")])
    env.claude_session("real", repo, [user("real prompt")])
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["real prompt"]
    assert len(result["workstreams"]) == 1


def test_sessions_that_start_with_the_digest_marker_are_excluded(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    env.claude_session("self", repo, [user("[daily-digest] Write the digest"), user("follow-up")])
    env.claude_session("real", repo, [user("real prompt")])
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["real prompt"]


def test_sidechain_and_tool_result_records_do_not_count_as_prompts(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = env.repo("alpha")
    tool_result = {
        "type": "user",
        "timestamp": IN_WINDOW,
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "output"}]},
    }
    env.claude_session("s1", repo, [user("human prompt"), user("subagent prompt", isSidechain=True), tool_result])
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["human prompt"]
    assert result["workstreams"][0]["sessions"][0]["prompt_count"] == 1


def test_secrets_are_redacted_but_the_line_that_held_them_remains(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    secrets = [
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "xoxb-" + "1234567890-abcdefghijkl",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "Bearer " + "eyJhbGciOi.payload.sig1234567890",
        "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWo=",
        "d41d8cd98f00b204e9800998ecf8427e",
    ]
    env.claude_session("s1", repo, [user("my token is " + " then ".join(secrets) + " please help")])
    capsys.readouterr()
    collect.main(env.args())
    out = capsys.readouterr().out
    for secret in secrets:
        assert secret.removeprefix("Bearer ") not in out
    prompts = all_prompts(json.loads(out))
    assert len(prompts) == 1
    assert prompts[0].startswith("my token is [redacted]")
    assert prompts[0].endswith("please help")


def test_ordinary_paths_branches_and_uuids_survive_redaction(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    uuid = "0b2b6670-7f23-4447-9262-23076fe81b5d"
    env.claude_session(
        uuid,
        repo,
        [user("edit /Users/marcus/Documents/app/apps/billing-workflows/src/Thing.ts")],
        branch="marcus/eng-2625-preview-sign-in-router",
    )
    result = run(env, capsys=capsys)
    ws = result["workstreams"][0]
    assert ws["branch"] == "marcus/eng-2625-preview-sign-in-router"
    assert ws["sessions"][0]["id"] == uuid
    assert "Documents/app/apps/billing-workflows" in ws["prompts"][0]


def test_prompts_are_truncated_and_capped_per_workstream(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    records = [user("x" * 500 if i == 0 else f"prompt {i}") for i in range(12)]
    env.claude_session("s1", repo, records)
    ws = run(env, capsys=capsys)["workstreams"][0]
    assert len(ws["prompts"]) == 8
    assert len(ws["prompts"][0]) <= 240
    assert ws["prompt_count"] == 12


def test_missing_sources_are_listed_and_do_not_crash(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    result = run(env, capsys=capsys)
    assert set(result["missing_sources"]) >= {"claude_history", "claude_projects", "codex_sessions"}
    assert result["workstreams"] == []


def test_codex_sessions_are_summarised(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("beta")
    day = env.codex / "sessions" / "2026" / "10" / "27"
    day.mkdir(parents=True)
    rows = [
        {
            "timestamp": IN_WINDOW,
            "type": "session_meta",
            "payload": {"id": "cx1", "cwd": str(repo), "git": {"branch": "feat/c"}},
        },
        {
            "timestamp": IN_WINDOW,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {"type": "UserMessage", "content": [{"type": "text", "text": "codex prompt ENG-77"}]},
            },
        },
        {
            "timestamp": BEFORE_WINDOW,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {"type": "UserMessage", "content": [{"type": "text", "text": "old codex prompt"}]},
            },
        },
    ]
    path = day / "rollout-2026-10-27T10-00-00-cx1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    stamp = datetime.fromisoformat(IN_WINDOW.replace("Z", "+00:00")).timestamp()
    os.utime(path, (stamp, stamp))
    ws = run(env, capsys=capsys)["workstreams"][0]
    assert (ws["repo"], ws["branch"]) == ("beta", "feat/c")
    assert ws["prompts"] == ["codex prompt ENG-77"]
    assert ws["issues"] == ["ENG-77"]
    assert ws["sessions"][0]["source"] == "codex"


def all_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


def test_ro_runs_are_not_read_or_reported(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ro_home = env.root / "ro-home"
    run_dir = ro_home / "runs" / "run-in"
    run_dir.mkdir(parents=True)
    event = {"kind": "run.contract", "run": "run-in", "seq": 1, "ts": IN_WINDOW, "v": 1}
    event["data"] = {"intent_record": "ro goal marker", "lane": "full"}
    (run_dir / "events.jsonl").write_text(json.dumps(event) + "\n")
    monkeypatch.setenv("RO_HOME", str(ro_home))
    env.claude_session("s1", env.repo("alpha"), [user("claude prompt")])
    result = run(env, capsys=capsys)
    assert all_prompts(result) == ["claude prompt"]
    assert "codex_sessions" in result["missing_sources"]
    strings = list(all_strings(result))
    assert "ro goal marker" not in strings
    assert "run-in" not in strings
    assert "ro_runs" not in strings


def test_the_same_session_in_several_project_directories_counts_once(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = env.repo("alpha")
    records = [user("first prompt", ts=IN_WINDOW), user("second prompt", ts="2026-10-27T18:00:00.000Z")]
    for suffix in ("", "-01", "-02", "-03"):
        project = env.claude / "projects" / (str(repo).replace("/", "-") + suffix)
        project.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"sessionId": "dup", "cwd": str(repo), "gitBranch": "main", **rec}) for rec in records]
        (project / "dup.jsonl").write_text("\n".join(lines) + "\n")
    ws = run(env, capsys=capsys)["workstreams"]
    assert [s["id"] for w in ws for s in w["sessions"]] == ["dup"]
    assert ws[0]["sessions"][0]["prompt_count"] == 2
    assert ws[0]["prompt_count"] == 2
    assert ws[0]["prompts"] == ["first prompt", "second prompt"]


def test_issue_keys_come_from_prompts_branches_and_titles_not_assistant_text(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = env.repo("alpha")
    pr = "https://github.com/acme/alpha/pull/99"
    env.claude_session(
        "s1",
        repo,
        [
            {"type": "custom-title", "customTitle": "Fix COR-5 flake"},
            user("please look at ENG-1"),
            assistant(f"Related: ENG-404, see https://linear.app/acme/issue/OPS-8/x and {pr}"),
        ],
        branch="marcus/pay-7-thing",
    )
    ws = run(env, capsys=capsys)["workstreams"][0]
    assert sorted(ws["issues"]) == ["COR-5", "ENG-1", "PAY-7"]
    assert ws["prs"] == [pr]


def test_a_git_sha_survives_redaction_but_other_long_hex_does_not(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    repo = env.repo("alpha")
    sha = "85be95fbd7a1c2d3e4f5061728394a5b6c7d8e9f"
    other = "d41d8cd98f00b204e9800998ecf8427e"
    longer = "0123456789abcdef0123456789abcdef0123456789abcdef"
    env.claude_session("s1", repo, [user(f"revert {sha} not {other} nor {longer} ok")])
    prompt = all_prompts(run(env, capsys=capsys))[0]
    assert sha in prompt
    assert other not in prompt
    assert longer not in prompt
    assert prompt.endswith("ok")


def test_output_stays_under_the_size_limit_and_says_when_it_truncated(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    for i in range(60):
        repo = env.repo(f"repo{i}")
        env.claude_session(f"s{i}", repo, [user(f"prompt {j} " + "word " * 40) for j in range(10)])
    capsys.readouterr()
    collect.main(env.args())
    out = capsys.readouterr().out
    assert len(out.encode()) < 41_000
    result = json.loads(out)
    assert result["truncated"] is True
    assert result["workstreams"]


def test_concepts_add_and_recall_with_sixty_day_cutoff(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.state.parent.mkdir(parents=True)
    old = (datetime(2026, 10, 27) - timedelta(days=61)).date().isoformat()
    recent = (datetime(2026, 10, 27) - timedelta(days=59)).date().isoformat()
    env.state.write_text(json.dumps([{"name": "Old Idea", "date": old}, {"name": "Recent Idea", "date": recent}]))
    assert (
        collect.main(
            [
                "concepts",
                "add",
                "Idempotency Keys",
                "CRDTs",
                "--state-file",
                str(env.state),
                "--now",
                "2026-10-27T06:00:00-07:00",
            ]
        )
        == 0
    )
    stored = json.loads(env.state.read_text())
    assert {"name": "CRDTs", "date": "2026-10-27"} in stored
    result = run(env, "--now", "2026-10-27T06:00:00-07:00", capsys=capsys)
    assert sorted(result["recent_concepts"], key=str.lower) == ["CRDTs", "Idempotency Keys", "Recent Idea"]


def test_concepts_are_compared_case_insensitively(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    now = "2026-10-27T06:00:00-07:00"
    collect.main(["concepts", "add", "Two-Phase Commit", "--state-file", str(env.state), "--now", now])
    collect.main(["concepts", "add", "two-phase commit", "--state-file", str(env.state), "--now", now])
    result = run(env, "--now", now, capsys=capsys)
    assert [c.lower() for c in result["recent_concepts"]] == ["two-phase commit"]


def test_concepts_honour_xdg_state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    collect.main(["concepts", "add", "Backpressure"])
    stored = json.loads((tmp_path / "xdg" / "daily-digest" / "concepts.json").read_text())
    assert [c["name"] for c in stored] == ["Backpressure"]
