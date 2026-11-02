"""Black-box tests for skills/eval-skill/scripts/eval_skill.py, run as a command.

``run`` tests put a fake ``claude`` and a fake ``codex`` on PATH. Both are Python scripts that read
$HOME/scenario.json and append one JSON line per call to $HOME/claude-calls.jsonl or
$HOME/codex-calls.jsonl. The fake ``claude plugin eval`` writes the run JSON that the scenario holds,
shaped like the real samples (cases[].arms.with/without, aggregates.delta). ``gate`` and ``summary``
tests write a results directory directly and run the script on it.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_HEADER, REPO_ROOT, IsolatedEnv

SCRIPT = REPO_ROOT / "skills" / "eval-skill" / "scripts" / "eval_skill.py"
RunTool = Callable[..., subprocess.CompletedProcess[str]]
Json = dict[str, Any]

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import fcntl, json, os, sys, time

home = os.environ["HOME"]
args = sys.argv[1:]
scenario_path = os.path.join(home, "scenario.json")
sc = json.load(open(scenario_path)) if os.path.exists(scenario_path) else {}


def log(record):
    with open(os.path.join(home, "claude-calls.jsonl"), "a") as handle:
        handle.write(json.dumps(record) + "\n")


def counter(key):
    path = os.path.join(home, "counters.json")
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counts = json.load(open(path)) if os.path.exists(path) else {}
        value = counts.get(key, 0)
        counts[key] = value + 1
        json.dump(counts, open(path, "w"))
    return value


def opt(flag):
    return args[args.index(flag) + 1] if flag in args else None


if args == ["--version"]:
    print(sc.get("claude_version", "2.1.295 (Claude Code)"))
    sys.exit(0)

if args[:2] == ["plugin", "eval"]:
    wrapper = args[2]
    arm = "previous" if opt("--ablation") == "none" else "isolated"
    files = []
    for base, _dirs, names in os.walk(wrapper):
        files += [os.path.relpath(os.path.join(base, n), wrapper) for n in names]
    skill_md = ""
    for rel in files:
        if rel.startswith("skills/") and rel.endswith("/SKILL.md"):
            skill_md = open(os.path.join(wrapper, rel)).read()
    plugin_json = os.path.join(wrapper, ".claude-plugin", "plugin.json")
    log({
        "kind": "eval", "arm": arm, "argv": args, "wrapper": wrapper, "files": sorted(files), "skill_md": skill_md,
        "plugin_json": json.load(open(plugin_json)) if os.path.exists(plugin_json) else None,
    })
    doc = sc.get("eval", {}).get(arm)
    batches = sc.get("eval", {}).get("isolated_batches")
    if arm == "isolated" and batches:
        doc = batches[min(counter("eval:isolated"), len(batches) - 1)]
    if doc is not None:
        with open(opt("--json"), "w") as handle:
            json.dump(doc, handle)
    sys.exit(sc.get("eval_exit", {}).get(arm, 0))

if "-p" in args and "--json-schema" in args:
    votes = sc.get("votes", ["PASS", "PASS", "PASS"])
    verdict = votes[counter("vote") % len(votes)]
    prompt = sys.stdin.read()
    log({"kind": "judge", "argv": args, "model": opt("--model"), "prompt": prompt})
    if sc.get("judge_fail_on") and sc["judge_fail_on"] in prompt:
        verdict = "FAIL"
    if verdict == "ERROR":
        sys.exit(3)
    if verdict == "CAPACITY":
        print("API Error: rate limit exceeded (429)", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.03,
                      "structured_output": {"verdict": verdict}, "result": json.dumps({"verdict": verdict})}))
    sys.exit(0)

if "-p" in args:
    prompt = args[-1]
    plugin_dir = opt("--plugin-dir")
    log({"kind": "realenv", "argv": args, "prompt": prompt, "cwd": os.getcwd(), "files": sorted(os.listdir(".")),
         "max_turns": opt("--max-turns")})
    mode = "plain"
    for entry in sc.get("realenv", []):
        if entry["match"] in prompt:
            mode = entry["modes"][counter("realenv:" + entry["match"]) % len(entry["modes"])]
            time.sleep(entry.get("sleep", 0))
    plugin = os.path.basename(plugin_dir.rstrip("/"))
    [skill_name] = os.listdir(os.path.join(plugin_dir, "skills"))
    qualified = plugin + ":" + skill_name
    if mode == "fired-bare":
        qualified, mode = skill_name, "fired"
    elif mode == "fired-other-prefix":
        qualified, mode = "other-plugin:" + skill_name, "fired"
    events = [{"type": "system", "subtype": "init"}]
    if mode == "crash":
        sys.exit(3)
    if mode == "overloaded-once":
        mode = "fired" if counter("overloaded:" + prompt) else "overloaded"
    if mode == "overloaded":
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "result": "API Error: 529 Overloaded", "total_cost_usd": 0.0}))
        sys.exit(1)
    if mode == "fired":
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": qualified}}]}})
        events.append({"type": "result", "subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.16,
                       "terminal_reason": "max_turns"})
        code = 1
    elif mode == "other-skill-then-ours":
        for index, called in enumerate(("unrelated-skill", qualified), start=1):
            events.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"t{index}", "name": "Skill", "input": {"skill": called}}]}})
        events.append({"type": "result", "subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.15,
                       "terminal_reason": "max_turns"})
        code = 1
    elif mode == "other-then-skill":
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x"}}]}})
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Skill", "input": {"skill": qualified}}]}})
        events.append({"type": "result", "subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.15,
                       "terminal_reason": "max_turns"})
        code = 1
    elif mode == "other-tool":
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x"}}]}})
        events.append({"type": "result", "subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.15,
                       "terminal_reason": "max_turns"})
        code = 1
    else:
        events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Plain answer"}]}})
        events.append({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.14,
                       "terminal_reason": "completed"})
        code = 0
    for event in events:
        print(json.dumps(event))
    sys.exit(code)

sys.exit(9)
"""

FAKE_CODEX = r"""#!/usr/bin/env python3
import fcntl, json, os, re, sys, time

home = os.environ["HOME"]
args = sys.argv[1:]
scenario_path = os.path.join(home, "scenario.json")
sc = json.load(open(scenario_path)) if os.path.exists(scenario_path) else {}


def log(record):
    with open(os.path.join(home, "codex-calls.jsonl"), "a") as handle:
        handle.write(json.dumps(record) + "\n")


if args == ["--version"]:
    log({"kind": "version"})
    print("codex-cli 0.157.0")
    sys.exit(0)

if args[:1] == ["exec"]:
    config = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
    disabled = set()
    for value in config:
        for found in re.findall(r'path\s*=\s*"([^"]+)"', value):
            disabled.add(os.path.realpath(found))
    name = sc.get("skill_name", "demo")
    cwd = os.getcwd()
    candidates = [
        ("workspace", os.path.join(cwd, ".agents", "skills", name, "SKILL.md")),
        ("installed", os.path.join(home, ".agents", "skills", name, "SKILL.md")),
    ]
    visible = [label for label, path in candidates if os.path.exists(path) and os.path.realpath(path) not in disabled]
    # A skill copy anywhere in the workspace .agents tree can be found with find and read with cat.
    workspace_copy = os.path.exists(candidates[0][1])
    mode = sc.get("codex", {}).get("mode", "ok")
    if mode == "capacity_first":
        path = os.path.join(home, "codex-count")
        with open(path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            seen = int(open(path).read()) if os.path.exists(path) else 0
            open(path, "w").write(str(seen + 1))
        mode = "capacity" if seen < sc["codex"]["fail_first"] else "ok"
    if mode == "snoop" and workspace_copy and "workspace" not in visible:
        visible.append("workspace")
    log({"kind": "exec", "prompt": args[-1], "argv": args, "cwd": cwd, "files": sorted(os.listdir(".")),
         "visible": visible, "stdin_tty": os.isatty(0), "workspace_copy": workspace_copy})
    time.sleep(sc.get("codex", {}).get("sleep", 0))
    print(json.dumps({"type": "thread.started", "thread_id": "t"}))
    print(json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "error",
                                                         "message": "Under-development features enabled: chronicle."}}))
    print(json.dumps({"type": "turn.started"}))
    if visible:
        print(json.dumps({"type": "item.completed", "item": {
            "id": "i1", "type": "command_execution", "status": "completed", "exit_code": 0,
            "command": "/bin/zsh -lc 'cat " + candidates[0][1] + "'", "aggregated_output": "x"}}))
    text = "visible: " + (",".join(visible) if visible else "none")
    arm_messages = sc.get("codex", {}).get("with_messages" if workspace_copy else "without_messages")
    if arm_messages:
        key = "with-count" if workspace_copy else "without-count"
        path = os.path.join(home, key)
        with open(path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            seen = int(open(path).read()) if os.path.exists(path) else 0
            open(path, "w").write(str(seen + 1))
        text = arm_messages[min(seen, len(arm_messages) - 1)]
    print(json.dumps({"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": text}}))
    if mode == "capacity":
        print(json.dumps({"type": "error", "message": "Selected model is at capacity. Please try a different model."}))
        print(json.dumps({"type": "turn.failed", "error": {"message": "Selected model is at capacity."}}))
        sys.exit(1)
    if mode == "turn_failed":
        print(json.dumps({"type": "turn.failed", "error": {"message": "HTTP 400"}}))
    elif mode == "error_event":
        print(json.dumps({"type": "error", "message": "stream closed"}))
    if mode != "no_completed":
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1000, "output_tokens": 50}}))
    sys.exit(3 if mode == "nonzero" else 0)

sys.exit(9)
"""


# --- builders for run JSON shaped like `claude plugin eval --json` ---------------------------------------------------


def spec(name: str, type_: str = "regex", config: Json | None = None, weight: int = 1) -> Json:
    """A grader spec, as in cases[].graders."""
    if config is None:
        config = {"tool": "Skill"} if type_ == "tool_used" else {"target": "last_message", "pattern": "x"}
    return {"name": name, "type": type_, "weight": weight, "config": config}


def grader_result(
    name: str, type_: str, passed: bool, *, scored: bool = True, with_only: bool = False, weight: int = 1
) -> Json:
    """One grader result inside a run."""
    return {
        "name": name,
        "passed": passed,
        "weight": weight,
        "explanation": "",
        "withOnly": with_only,
        "scored": scored,
    }


def run_entry(graders: list[Json], *, error: str | None = None, skipped: bool = False, cost: float = 0.1) -> Json:
    scored = [g for g in graders if g["scored"]]
    total = sum(g["weight"] for g in scored)
    score = sum(g["weight"] for g in scored if g["passed"]) / total if total else 0
    return {
        "score": score,
        "passed": score == 1,
        "turns": 1,
        "costUsd": cost,
        "judgeCostUsd": 0.001,
        "error": error,
        "skippedPaidGraders": skipped,
        "graders": graders,
    }


def case_doc(
    kind: str,
    name: str,
    specs: list[Json],
    with_runs: list[Json],
    without_runs: list[Json] | None = None,
    *,
    delta: float | None | str = "auto",
    prompt: str | None = None,
) -> Json:
    def mean(runs: list[Json]) -> float:
        return sum(r["score"] for r in runs) / len(runs)

    aggregates: Json = {"score": mean(with_runs), "passRate": 1}
    arms: Json = {"with": with_runs}
    if without_runs is not None:
        arms["without"] = without_runs
        aggregates["scoreWithout"] = mean(without_runs)
        if delta == "auto":
            aggregates["delta"] = mean(with_runs) - mean(without_runs)
    if delta != "auto" and delta is not None:
        aggregates["delta"] = delta
    return {
        "name": name,
        "dir": f"evals/{kind}/{name}",
        "source": "prose",
        "promptMarkdown": prompt or f"{kind} prompt {name}",
        "runsPerCase": len(with_runs),
        "timeoutSeconds": 300,
        "maxTurns": 4,
        "graders": specs,
        "arms": arms,
        "aggregates": aggregates,
    }


def eval_doc(cases: list[Json], *, partial: bool = False, ablation: str = "with-without") -> Json:
    return {
        "schemaVersion": 1,
        "claudeVersion": "2.1.295",
        "startedAt": "2026-10-19T02:07:54.235Z",
        "costUsd": 0.5,
        "partial": partial,
        "suite": {"ablation": ablation, "threshold": 0},
        "cases": cases,
        "aggregates": {"casesTotal": len(cases)},
    }


def n_runs(n: int, make: Callable[[int], Json]) -> list[Json]:
    return [make(i) for i in range(n)]


# --- a passing results directory for gate and summary tests ----------------------------------------------------------

JUDGE = "quality"
DET = "five-lines"


def base_cases(n: int = 3) -> list[Json]:
    """behaviour, trigger, near-miss and explicit cases that all pass on Claude."""
    behaviour_specs = [spec(DET), spec(JUDGE, "llm", {"criteria": "c", "focus": "last_message"})]
    behaviour = case_doc(
        "behaviour",
        "b1",
        behaviour_specs,
        n_runs(n, lambda _: run_entry([grader_result(DET, "regex", True), grader_result(JUDGE, "llm", True)])),
        n_runs(n, lambda _: run_entry([grader_result(DET, "regex", False), grader_result(JUDGE, "llm", False)])),
    )
    trigger_specs = [spec("skill-fired", "tool_used")]
    trigger = case_doc(
        "trigger",
        "t1",
        trigger_specs,
        n_runs(n, lambda _: run_entry([grader_result("skill-fired", "tool_used", True, scored=False, with_only=True)])),
        n_runs(
            n, lambda _: run_entry([grader_result("skill-fired", "tool_used", False, scored=False, with_only=True)])
        ),
    )
    near_specs = [spec("never-fires", "tool_used", {"tool": "Skill", "min": 0, "max": 0})]
    near = case_doc(
        "near-miss",
        "n1",
        near_specs,
        n_runs(n, lambda _: run_entry([grader_result("never-fires", "tool_used", True)])),
        n_runs(n, lambda _: run_entry([grader_result("never-fires", "tool_used", True)])),
    )
    explicit_specs = [spec("skill-fired", "tool_used"), spec("shape")]
    explicit = case_doc(
        "explicit",
        "e1",
        explicit_specs,
        n_runs(
            n,
            lambda _: run_entry(
                [
                    grader_result("skill-fired", "tool_used", False, scored=False, with_only=True),
                    grader_result("shape", "regex", True),
                ]
            ),
        ),
        n_runs(n, lambda _: run_entry([grader_result("shape", "regex", True)])),
        delta=None,
    )
    return [behaviour, trigger, near, explicit]


def base_parts(n: int = 3, *, harnesses: tuple[str, ...] = ("claude",)) -> Json:
    cases = base_cases(n)
    manifest: Json = {
        "skill": "demo",
        "date": "2026-10-19",
        "runs": n,
        "harnesses": list(harnesses),
        "models": {"claude": "claude-opus-5-5", "codex": "gpt-6-sol", "judge": "claude-sonnet-5-5"},
        "versions": {"claude": "2.1.295 (Claude Code)", "codex": "codex-cli 0.157.0"},
        "gitSha": None,
        "cases": ["behaviour/b1", "trigger/t1", "near-miss/n1", "explicit/e1"],
        "arms": ["claude-isolated", "claude-real-env"],
        "armErrors": {},
        "warnings": [],
        "wrapperPlugin": "eval-demo-1a2b3c4d",
    }
    real_env: Json = {
        "maxTurns": 1,
        "cases": {
            "trigger/t1": {"runs": n_runs(n, lambda _: {"fired": True, "error": None, "costUsd": 0.16})},
            "near-miss/n1": {"runs": n_runs(n, lambda _: {"fired": False, "error": None, "costUsd": 0.14})},
        },
    }
    parts: Json = {"manifest": manifest, "claude-isolated": eval_doc(cases), "claude-real-env": real_env}
    if "codex" in harnesses:
        manifest["arms"].append("codex")
        parts["codex"] = base_codex(n)
    return parts


def codex_run(graders: list[Json], *, error: str | None = None) -> Json:
    scored = [g for g in graders if g["scored"] and g["applicable"]]
    total = sum(g["weight"] for g in scored)
    score = sum(g["weight"] for g in scored if g["passed"]) / total if total else None
    return {
        "score": score,
        "error": error,
        "lastMessage": "m",
        "tokens": {"input": 1000, "output": 50},
        "graders": graders,
    }


def codex_grader(name: str, type_: str, passed: bool | None, *, scored: bool = True, applicable: bool = True) -> Json:
    return {
        "name": name,
        "type": type_,
        "passed": passed,
        "weight": 1,
        "scored": scored,
        "applicable": applicable,
    }


def base_codex(n: int) -> Json:
    def scored_case(with_pass: bool, without_pass: bool) -> Json:
        without = n_runs(n, lambda _: codex_run([codex_grader(DET, "regex", without_pass)]))
        return {
            "status": "scored",
            "with": n_runs(n, lambda _: codex_run([codex_grader(DET, "regex", with_pass)])),
            "without": without,
            "delta": (1.0 if with_pass else 0.0) - (1.0 if without_pass else 0.0),
        }

    def not_run_case() -> Json:
        return {"status": "not-run", "with": [], "without": [], "delta": None}

    def mixed_case(with_pass: bool, without_pass: bool) -> Json:
        """An explicit case: a tool_used grader Codex cannot grade, and a regex it can."""

        def one(passed: bool) -> Json:
            return codex_run(
                [
                    codex_grader("skill-fired", "tool_used", None, scored=False, applicable=False),
                    codex_grader("shape", "regex", passed),
                ]
            )

        return {
            "status": "scored",
            "with": n_runs(n, lambda _: one(with_pass)),
            "without": n_runs(n, lambda _: one(without_pass)),
            "delta": (1.0 if with_pass else 0.0) - (1.0 if without_pass else 0.0),
        }

    return {
        "model": "gpt-6-sol",
        "judgeModel": "claude-sonnet-5-5",
        "tokens": {"input": 12000, "output": 600},
        "cases": {
            "behaviour/b1": scored_case(True, False),
            "trigger/t1": not_run_case(),
            "near-miss/n1": not_run_case(),
            "explicit/e1": mixed_case(True, False),
        },
    }


def claude_case(parts: Json, key: str) -> Json:
    kind, name = key.split("/")
    for case in parts["claude-isolated"]["cases"]:
        if case["dir"] == f"evals/{kind}/{name}":
            return case
    raise KeyError(key)


def write_results(root: Path, parts: Json) -> Path:
    results = root / "state" / "demo" / "2026-10-19T00-00-00Z"
    results.mkdir(parents=True)
    for name, doc in parts.items():
        (results / f"{name}.json").write_text(json.dumps(doc))
    return results


# --- gate ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def run_script(run_tool: RunTool, isolated_env: IsolatedEnv) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*args: str | os.PathLike[str], cwd: Path | None = None, **extra_env: str):
        return run_tool([sys.executable, SCRIPT, *args], cwd=cwd or isolated_env.root, **extra_env)

    return run


def gate(run_script: Callable[..., subprocess.CompletedProcess[str]], root: Path, parts: Json):
    return run_script("gate", write_results(root, parts))


def fail_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith("FAIL")]


def test_gate_passes_a_fully_passing_results_directory(run_script, isolated_env):
    result = gate(run_script, isolated_env.root, base_parts())
    assert (result.returncode, fail_lines(result)) == (0, [])
    assert "PASS" in result.stdout


def test_gate_fails_a_deterministic_grader_that_passes_two_of_three_runs(run_script, isolated_env):
    """AC-1. A flaky regex grader is a regression even when most runs pass."""
    parts = base_parts()
    claude_case(parts, "behaviour/b1")["arms"]["with"][1]["graders"][0]["passed"] = False
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    lines = fail_lines(result)
    assert len(lines) == 1
    assert all(token in lines[0] for token in ("claude-isolated", "behaviour/b1", DET, "2/3", "3/3"))


def test_gate_accepts_a_judge_grader_at_two_of_three_and_rejects_one_of_three(run_script, isolated_env):
    """AC-2. Judge graders are noisy, so ceil(2N/3) runs are enough."""
    parts = base_parts()
    judge_runs = claude_case(parts, "behaviour/b1")["arms"]["with"]
    judge_runs[1]["graders"][1]["passed"] = False
    two_of_three = gate(run_script, isolated_env.root, parts)
    assert (two_of_three.returncode, fail_lines(two_of_three)) == (0, [])
    assert "PASS" in two_of_three.stdout

    judge_runs[2]["graders"][1]["passed"] = False
    one_of_three = gate(run_script, isolated_env.root / "again", parts)
    assert one_of_three.returncode == 1
    assert any(JUDGE in line and "1/3" in line for line in fail_lines(one_of_three))


@pytest.mark.parametrize("delta", ["no-gain", None, "missing"])
def test_gate_fails_a_behaviour_case_without_a_proven_gain(run_script, isolated_env, delta):
    """AC-3. A skill that does not beat the no-skill arm changes nothing, and a missing delta is not a pass."""
    parts = base_parts()
    case = claude_case(parts, "behaviour/b1")
    if delta == "missing":
        del case["aggregates"]["delta"]
    elif delta is None:
        case["aggregates"]["delta"] = None
    else:
        for run in case["arms"]["without"]:
            run["score"] = 1.0
        case["aggregates"]["delta"] = 0
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("behaviour/b1" in line and "delta" in line.lower() for line in fail_lines(result))


def mark_error(parts: Json) -> None:
    claude_case(parts, "behaviour/b1")["arms"]["with"][0]["error"] = "boom"


def mark_without_error(parts: Json) -> None:
    claude_case(parts, "behaviour/b1")["arms"]["without"][2]["error"] = "api 500"


def mark_aborted(parts: Json) -> None:
    claude_case(parts, "behaviour/b1")["arms"]["with"][0]["aborted"] = {"reason": "cost ceiling"}


def mark_skipped_judge(parts: Json) -> None:
    claude_case(parts, "behaviour/b1")["arms"]["with"][0]["skippedPaidGraders"] = True


def mark_partial(parts: Json) -> None:
    parts["claude-isolated"]["partial"] = True


def drop_field(parts: Json) -> None:
    del claude_case(parts, "behaviour/b1")["arms"]["with"][0]["graders"][0]["passed"]


def drop_run(parts: Json) -> None:
    claude_case(parts, "behaviour/b1")["arms"]["with"].pop()


def arm_error(parts: Json) -> None:
    parts["manifest"]["armErrors"] = {"claude-isolated": "exit 2"}


@pytest.mark.parametrize(
    "mutate",
    [
        mark_error,
        mark_without_error,
        mark_aborted,
        mark_skipped_judge,
        mark_partial,
        drop_field,
        drop_run,
        arm_error,
    ],
)
def test_gate_fails_closed_on_an_unreliable_run(run_script, isolated_env, mutate):
    """AC-4. Every other grader still passes, so only the unreliable evidence can fail the gate."""
    parts = base_parts()
    mutate(parts)
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert fail_lines(result), result.stdout


def test_gate_fails_when_an_arm_file_is_missing(run_script, isolated_env):
    parts = base_parts()
    del parts["claude-real-env"]
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("claude-real-env" in line for line in fail_lines(result))


def test_gate_fails_when_the_codex_file_is_missing_but_codex_was_planned(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    assert gate(run_script, isolated_env.root / "ok", parts).returncode == 0
    del parts["codex"]
    result = gate(run_script, isolated_env.root / "missing", parts)
    assert result.returncode == 1
    assert any("codex" in line for line in fail_lines(result))


def test_gate_fails_a_near_miss_case_that_fires_in_one_of_three_real_runs(run_script, isolated_env):
    """AC-7. The skill must never fire on a near miss."""
    parts = base_parts()
    parts["claude-real-env"]["cases"]["near-miss/n1"]["runs"][1]["fired"] = True
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    lines = fail_lines(result)
    assert len(lines) == 1 and "claude-real-env" in lines[0] and "near-miss/n1" in lines[0]


def test_gate_fails_a_trigger_case_that_fires_in_two_of_three_real_runs(run_script, isolated_env):
    parts = base_parts()
    parts["claude-real-env"]["cases"]["trigger/t1"]["runs"][0]["fired"] = False
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("claude-real-env" in line and "trigger/t1" in line and "2/3" in line for line in fail_lines(result))


def test_gate_fails_a_real_env_run_that_errored(run_script, isolated_env):
    parts = base_parts()
    parts["claude-real-env"]["cases"]["trigger/t1"]["runs"][0]["error"] = "exit 3"
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("trigger/t1" in line for line in fail_lines(result))


def test_gate_requires_the_skill_indicator_on_trigger_cases_but_ignores_it_on_explicit_cases(run_script, isolated_env):
    parts = base_parts()
    claude_case(parts, "trigger/t1")["arms"]["with"][0]["graders"][0]["passed"] = False
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("trigger/t1" in line and "skill-fired" in line for line in fail_lines(result))
    # The explicit case already has a failing Skill indicator in the passing base; it never fails the gate.
    assert not any("explicit/e1" in line for line in fail_lines(result))


def test_gate_fails_a_near_miss_case_whose_isolated_grader_saw_the_skill_fire(run_script, isolated_env):
    parts = base_parts()
    claude_case(parts, "near-miss/n1")["arms"]["with"][0]["graders"][0]["passed"] = False
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("near-miss/n1" in line and "never-fires" in line for line in fail_lines(result))


def test_gate_fails_a_near_miss_skill_indicator_that_the_cli_left_unscored(run_script, isolated_env):
    """If the CLI reports the near-miss grader as with-only (unscored), the gate must still enforce it."""
    parts = base_parts()
    grader = claude_case(parts, "near-miss/n1")["arms"]["with"][0]["graders"][0]
    grader.update({"scored": False, "withOnly": True, "passed": False})
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("near-miss/n1" in line for line in fail_lines(result))


def test_gate_fails_a_case_in_an_unknown_kind_folder(run_script, isolated_env):
    parts = base_parts()
    claude_case(parts, "near-miss/n1")["dir"] = "evals/mystery/n1"
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert fail_lines(result)


def test_gate_applies_the_codex_delta_and_pass_rules(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    assert gate(run_script, isolated_env.root / "ok", parts).returncode == 0

    flat = copy.deepcopy(parts)
    for run in flat["codex"]["cases"]["behaviour/b1"]["without"]:
        run["score"] = 1.0
    flat["codex"]["cases"]["behaviour/b1"]["delta"] = 0.0
    result = gate(run_script, isolated_env.root / "flat", flat)
    assert result.returncode == 1
    assert any(line.startswith("FAIL codex") and "behaviour/b1" in line for line in fail_lines(result))

    flaky = copy.deepcopy(parts)
    flaky["codex"]["cases"]["explicit/e1"]["with"][0]["graders"][1]["passed"] = False
    result = gate(run_script, isolated_env.root / "flaky", flaky)
    assert result.returncode == 1
    assert any(
        "codex" in line and "explicit/e1" in line and "shape" in line and "2/3" in line for line in fail_lines(result)
    )

    errored = copy.deepcopy(parts)
    errored["codex"]["cases"]["behaviour/b1"]["without"][0]["error"] = "turn.failed"
    result = gate(run_script, isolated_env.root / "errored", errored)
    assert result.returncode == 1
    assert any("codex" in line and "behaviour/b1" in line for line in fail_lines(result))


def test_gate_fails_a_codex_case_that_no_grader_can_grade_and_names_the_fix(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    parts["codex"]["cases"]["behaviour/b1"] = {"status": "ungradable", "with": [], "without": [], "delta": None}
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    [line] = fail_lines(result)
    assert line.startswith("FAIL codex behaviour/b1")
    assert "final reply" in line and "evals/eval-skill.json" in line


@pytest.mark.parametrize("status", ["n/a", "mystery"])
def test_gate_fails_a_codex_case_with_an_unknown_or_legacy_status(run_script, isolated_env, status):
    parts = base_parts(harnesses=("claude", "codex"))
    parts["codex"]["cases"]["behaviour/b1"] = {"status": status, "with": [], "without": [], "delta": None}
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any(line.startswith("FAIL codex behaviour/b1") and status in line for line in fail_lines(result))


def test_gate_ignores_the_previous_version_arm(run_script, isolated_env):
    parts = base_parts()
    parts["manifest"]["arms"].append("claude-previous")
    broken = eval_doc(base_cases(), partial=True)
    broken["cases"][0]["arms"]["with"][0]["error"] = "boom"
    parts["claude-previous"] = broken
    result = gate(run_script, isolated_env.root, parts)
    assert (result.returncode, fail_lines(result)) == (0, [])
    assert "PASS" in result.stdout


def test_gate_on_a_directory_without_a_manifest_fails_with_one_clear_line(run_script, isolated_env):
    empty = isolated_env.root / "empty"
    empty.mkdir()
    result = run_script("gate", empty)
    assert result.returncode == 1
    assert "manifest" in (result.stdout + result.stderr)


# --- summary ---------------------------------------------------------------------------------------------------------


def row_for(summary: str, case: str) -> list[str]:
    for line in summary.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells and cells[0] == case:
            return cells
    raise AssertionError(f"no table row for {case} in:\n{summary}")


HEADER = ["Case", "Kind", "Claude with", "Claude without", "Δ", "Codex with", "Codex without", "Codex Δ"]


def test_summary_marks_the_codex_arm_as_skipped_when_only_claude_ran(run_script, isolated_env):
    results = write_results(isolated_env.root, base_parts())
    result = run_script("summary", results)
    assert result.returncode == 0
    header = next(line for line in result.stdout.splitlines() if line.startswith("| Case"))
    cells = [c.strip() for c in header.strip().strip("|").split("|")]
    assert cells[:8] == HEADER and cells[-1] == "Verdict" and "Previous" in cells and "Real env fired" in cells
    row = row_for(result.stdout, "b1")
    assert row[1] == "behaviour"
    assert row[5:8] == ["skipped (harnesses: claude)"] * 3
    assert "skipped (harnesses: claude)" in result.stdout


def test_summary_shows_scores_deltas_real_env_counts_and_the_verdict(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    parts["claude-real-env"]["cases"]["near-miss/n1"]["runs"][1]["fired"] = True
    results = write_results(isolated_env.root, parts)
    summary = run_script("summary", results).stdout
    b1 = row_for(summary, "b1")
    assert b1[2:5] == ["1.00", "0.00", "+1.00 [+1.00, +1.00] (3 runs)"]
    assert b1[5:8] == ["1.00", "0.00", "+1.00 [+1.00, +1.00] (3 runs)"]
    assert row_for(summary, "t1")[8] == "3/3"
    assert row_for(summary, "n1")[8] == "1/3"
    assert row_for(summary, "n1")[-1].startswith("FAIL") and row_for(summary, "b1")[-1].startswith("PASS")
    assert row_for(summary, "e1")[5:8] == ["1.00", "0.00", "+1.00"]  # explicit cases show no interval
    assert "near-miss/n1" in summary.split("Gate verdict", 1)[1]


def test_summary_header_shows_models_versions_runs_cost_tokens_and_date(run_script, isolated_env):
    """AC-9 (the summary half)."""
    parts = base_parts(harnesses=("claude", "codex"))
    parts["claude-isolated"]["costUsd"] = 1.25
    results = write_results(isolated_env.root, parts)
    summary = run_script("summary", results).stdout
    for expected in (
        "2026-10-19",
        "demo",
        "claude-opus-5-5",
        "gpt-6-sol",
        "claude-sonnet-5-5",
        "2.1.295 (Claude Code)",
        "codex-cli 0.157.0",
        "12,600",
    ):
        assert expected in summary, expected
    cost_line = next(line for line in summary.splitlines() if "cost" in line.lower())
    # 1.25 (run JSON) + 24 judge costs of 0.001 + 3 x 0.16 and 3 x 0.14 (real-env runs) = 2.174
    assert "$2.17" in cost_line


def test_summary_shows_the_previous_version_score_and_warns_when_that_arm_failed(run_script, isolated_env):
    parts = base_parts()
    parts["manifest"]["arms"].append("claude-previous")
    previous_cases = base_cases()
    for run in previous_cases[0]["arms"]["with"]:
        run["graders"][0]["passed"] = False
        run["score"] = 0.5
    parts["claude-previous"] = eval_doc(previous_cases, ablation="none")
    summary = run_script("summary", write_results(isolated_env.root / "a", parts)).stdout
    assert row_for(summary, "b1")[-2] == "0.50"

    failed = base_parts()
    failed["manifest"]["armErrors"] = {"claude-previous": "exit 1: load error"}
    summary = run_script("summary", write_results(isolated_env.root / "b", failed)).stdout
    assert "claude-previous" in summary and "load error" in summary
    assert row_for(summary, "b1")[-2] in {"n/a", "error"}


# --- run -------------------------------------------------------------------------------------------------------------


def calls(home: Path, tool: str) -> list[Json]:
    path = home / f"{tool}-calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def opt(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


class Project:
    """A skill under test in a temp tree, plus the fakes and scenario for ``run``."""

    def __init__(self, env: IsolatedEnv, run_script: Callable[..., subprocess.CompletedProcess[str]]):
        self.env = env
        self.run_script = run_script
        self.skill = env.root / "repo" / "skills" / "demo"
        self.state = env.root / "state-out"
        self.scenario: Json = {"skill_name": "demo"}
        (env.bin / "claude").write_text(FAKE_CLAUDE)
        (env.bin / "codex").write_text(FAKE_CODEX)
        for tool in ("claude", "codex"):
            (env.bin / tool).chmod(0o755)
        assert FAKE_HEADER.startswith("#!")

    def make_skill(self, cases: dict[str, str | None], config: Json | None = None) -> None:
        """cases maps "kind/name" to an optional scaffold.sh body."""
        (self.skill).mkdir(parents=True, exist_ok=True)
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nNEW skill body\n")
        (self.skill / "evals" / "results" / "old").mkdir(parents=True, exist_ok=True)
        (self.skill / "evals" / "results" / "old" / "stale.json").write_text("{}")
        for key, scaffold in cases.items():
            case_dir = self.skill / "evals" / key
            (case_dir / "graders").mkdir(parents=True)
            (case_dir / "prompt.md").write_text(f"prompt for {key}\n")
            (case_dir / "graders" / "g.md").write_text("---\ntype: regex\npattern: x\n---\n")
            if scaffold is not None:
                (case_dir / "scaffold.sh").write_text("#!/usr/bin/env bash\n" + scaffold)
                (case_dir / "case.yaml").write_text("context:\n  scaffold_script: scaffold.sh\n")
        if config is not None:
            (self.skill / "evals" / "eval-skill.json").write_text(json.dumps(config))

    def write_scenario(self) -> None:
        (self.env.home / "scenario.json").write_text(json.dumps(self.scenario))

    def run(self, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
        self.write_scenario()
        # One batch by default: a test that wants extra batches passes --runs and --max-runs itself.
        batching = [] if "--runs" in extra or "--max-runs" in extra else ["--runs", "1", "--max-runs", "1"]
        return self.run_script(
            "run", self.skill, *batching, "--state-dir", self.state, *extra, cwd=self.skill.parent, **env
        )

    def results_dir(self, completed: subprocess.CompletedProcess[str]) -> Path:
        return Path(completed.stdout.strip().splitlines()[-1])

    def snapshot(self) -> list[tuple[str, int, int]]:
        entries = []
        for path in sorted(self.skill.rglob("*")):
            stat = path.stat()
            entries.append((str(path.relative_to(self.skill)), stat.st_size, stat.st_mtime_ns))
        return entries


@pytest.fixture
def project(isolated_env: IsolatedEnv, run_script) -> Project:
    return Project(isolated_env, run_script)


def simple_eval(kind: str = "behaviour", name: str = "c1", *, graders: list[Json] | None = None) -> Json:
    specs = graders or [spec("shape", "regex", {"target": "last_message", "pattern": "visible", "match": "contains"})]
    with_runs = [run_entry([grader_result(s["name"], s["type"], True) for s in specs])]
    without_runs = [run_entry([grader_result(s["name"], s["type"], False) for s in specs])]
    return eval_doc([case_doc(kind, name, specs, with_runs, without_runs)])


def test_run_builds_a_wrapper_and_never_touches_the_live_skill_folder(project):
    """AC-13 and the live-folder rule. --no-publish keeps the report off claude.ai, so the flag is the contract."""
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    before = project.snapshot()
    result = project.run()
    assert result.returncode == 0, result.stderr
    assert project.snapshot() == before

    evals = [c for c in calls(project.env.home, "claude") if c["kind"] == "eval"]
    assert len(evals) == 1
    argv = evals[0]["argv"]
    # Contract flags: --no-publish keeps the report off claude.ai. --judge-model pins the judge.
    assert "--no-publish" in argv
    assert opt(argv, "--judge-model") == "claude-sonnet-5-5"
    results = project.results_dir(result)
    assert (results / "claude-isolated.json").exists()
    manifest = json.loads((results / "manifest.json").read_text())
    assert manifest["models"]["claude"] == "claude-opus-5-5"
    plugin = evals[0]["plugin_json"]["name"]
    assert re.fullmatch(r"eval-demo-[0-9a-f]{8}", plugin)
    assert manifest["wrapperPlugin"] == plugin
    assert "skills/demo/SKILL.md" in evals[0]["files"]
    assert not any(f.startswith("skills/demo/evals") for f in evals[0]["files"])
    assert "evals/behaviour/c1/prompt.md" in evals[0]["files"]
    assert not any(f.startswith("evals/results") for f in evals[0]["files"])
    assert not Path(evals[0]["wrapper"]).exists()


def test_run_writes_results_under_the_xdg_state_home_with_a_manifest(project, isolated_env):
    """AC-9 (the run half)."""
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    project.write_scenario()
    xdg = isolated_env.root / "xdg"
    before = datetime.now(UTC).strftime("%Y-%m-%d")
    result = project.run_script(
        "run", project.skill, "--runs", "1", "--max-runs", "1", cwd=project.skill.parent, XDG_STATE_HOME=str(xdg)
    )
    after = datetime.now(UTC).strftime("%Y-%m-%d")
    assert result.returncode == 0, result.stderr
    results = project.results_dir(result)
    assert results.parent == xdg / "eval-skill" / "demo"
    manifest = json.loads((results / "manifest.json").read_text())
    assert manifest["skill"] == "demo" and manifest["runs"] == 1
    assert manifest["date"] in {before, after}
    assert manifest["versions"]["claude"] == "2.1.295 (Claude Code)"
    assert manifest["models"] == {"claude": "claude-opus-5-5", "codex": "gpt-6-sol", "judge": "claude-sonnet-5-5"}
    assert (results / "claude-isolated.json").exists()


def test_run_with_claude_only_harness_never_calls_codex_and_the_summary_says_so(project):
    """AC-6."""
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    assert result.returncode == 0, result.stderr
    assert calls(project.env.home, "codex") == []
    manifest = json.loads((project.results_dir(result) / "manifest.json").read_text())
    assert manifest["harnesses"] == ["claude"] and "codex" not in manifest["arms"]
    summary = project.run_script("summary", project.results_dir(result)).stdout
    assert "skipped (harnesses: claude)" in summary


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"harnesses": ["claude", "gemini"]}, "gemini"),
        ({"harnesses": ["claude"], "extra": 1}, "extra"),
        ({"harnesses": []}, "harnesses"),
        ({"harness": ["claude"]}, "harness"),
    ],
)
def test_run_rejects_an_invalid_eval_skill_json_before_calling_anything(project, config, message):
    project.make_skill({"behaviour/c1": None}, config)
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    assert result.returncode == 1
    assert "eval-skill.json" in result.stderr and message in result.stderr
    assert calls(project.env.home, "claude") == [] and calls(project.env.home, "codex") == []
    assert not project.state.exists()


@pytest.mark.parametrize(
    ("case_path", "message"),
    [("mystery/c1", "mystery"), ("c1", "c1"), ("behaviour/group/c1", "group")],
)
def test_run_rejects_a_case_at_the_wrong_depth_or_in_an_unknown_kind(project, case_path, message):
    project.make_skill({case_path: None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    assert result.returncode == 1
    assert message in result.stderr
    assert calls(project.env.home, "claude") == []


def test_run_stops_when_codex_config_already_sets_skills_config(project):
    (project.env.home / ".codex").mkdir()
    (project.env.home / ".codex" / "config.toml").write_text(
        'model = "x"\n\n[[skills.config]]\npath = "/a"\nenabled = false\n'
    )
    project.make_skill({"behaviour/c1": None})
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    assert result.returncode == 1
    assert "skills.config" in result.stderr
    assert calls(project.env.home, "claude") == [] and calls(project.env.home, "codex") == []


def test_codex_without_arm_hides_the_workspace_and_installed_copies_and_with_arm_hides_only_the_installed_one(project):
    """AC-5. The fake codex decides from its own -c arguments which copies the agent can see."""
    project.make_skill({"behaviour/c1": "echo scaffolded > marker.txt\n"}, {"harnesses": ["claude", "codex"]})
    installed = project.env.home / ".agents" / "skills" / "demo"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("installed copy\n")
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    assert result.returncode == 0, result.stderr
    codex = json.loads((project.results_dir(result) / "codex.json").read_text())
    case = codex["cases"]["behaviour/c1"]
    assert [r["lastMessage"] for r in case["with"]] == ["visible: workspace"]
    assert [r["lastMessage"] for r in case["without"]] == ["visible: none"]
    execs = [c for c in calls(project.env.home, "codex") if c["kind"] == "exec"]
    assert len(execs) == 2
    assert all("marker.txt" in c["files"] for c in execs)
    assert all(not c["stdin_tty"] for c in execs)
    for call in execs:
        assert opt(call["argv"], "-m") == "gpt-6-sol"
        assert opt(call["argv"], "-s") == "read-only"
    assert (installed / "SKILL.md").read_text() == "installed copy\n"
    # Codex scoring: with-arm 1.0, without-arm 1.0 (same regex matches "visible" in both), so delta is 0.
    assert case["delta"] == 0


def test_codex_scores_the_with_arm_against_the_without_arm_using_the_regex_grader(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    specs = [spec("shape", "regex", {"target": "last_message", "pattern": "workspace", "match": "contains"})]
    with_runs = [run_entry([grader_result("shape", "regex", True)])]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("behaviour", "c1", specs, with_runs, with_runs)])}
    result = project.run()
    assert result.returncode == 0, result.stderr
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert (case["with"][0]["score"], case["without"][0]["score"], case["delta"]) == (1.0, 0.0, 1.0)
    assert case["with"][0]["tokens"] == {"input": 1000, "output": 50}


@pytest.mark.parametrize("mode", ["nonzero", "turn_failed", "error_event", "no_completed"])
def test_codex_run_errors_are_recorded_and_fail_the_run_and_the_gate(project, mode):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    project.scenario["codex"] = {"mode": mode}
    result = project.run()
    assert result.returncode == 1
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["error"]
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1 and any(line.startswith("FAIL") for line in gated.stdout.splitlines())
    assert "arm failed" not in gated.stdout and "malformed" not in gated.stdout


def test_codex_under_development_warning_item_is_not_a_run_error(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run()
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert result.returncode == 0 and case["with"][0]["error"] is None


@pytest.mark.parametrize(
    ("votes", "with_passes"),
    [(["PASS", "FAIL", "PASS"], True), (["PASS", "FAIL", "FAIL"], False)],
)
def test_codex_llm_grader_passes_on_two_of_three_votes_with_the_pinned_judge(project, votes, with_passes):
    """AC-8. The judge model pin is the contract, because it fixes what the Codex llm grader means."""
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    specs = [spec("quality", "llm", {"criteria": "Be brief.", "focus": "last_message"})]
    with_runs = [run_entry([grader_result("quality", "llm", True)])]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("behaviour", "c1", specs, with_runs, with_runs)])}
    project.scenario["votes"] = votes
    # The fake hands out votes in call order, so run serially for a fixed vote sequence.
    result = project.run("--concurrency", "1")
    assert result.returncode == 0, result.stderr
    judge_calls = [c for c in calls(project.env.home, "claude") if c["kind"] == "judge"]
    assert len(judge_calls) == 6
    assert {c["model"] for c in judge_calls} == {"claude-sonnet-5-5"}
    assert all("Be brief." in c["prompt"] and "visible" in c["prompt"] for c in judge_calls)
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["graders"][0]["passed"] is with_passes
    assert case["with"][0]["graders"][0]["judgeVotes"] == [v == "PASS" for v in votes]


def test_codex_judge_vote_failure_is_a_run_error_not_a_fail_vote(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    specs = [spec("quality", "llm", {"criteria": "Be brief."})]
    with_runs = [run_entry([grader_result("quality", "llm", True)])]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("behaviour", "c1", specs, with_runs, with_runs)])}
    project.scenario["votes"] = ["ERROR"]
    result = project.run()
    assert result.returncode == 1
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["error"] and "judge" in case["with"][0]["error"]


def test_codex_spends_no_runs_on_a_case_without_a_grader_that_reads_the_reply_and_the_gate_fails_it(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    specs = [spec("made", "file_exists", {"path": "out.txt"})]
    with_runs = [run_entry([grader_result("made", "file_exists", True)])]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("behaviour", "c1", specs, with_runs, with_runs)])}
    result = project.run()
    assert result.returncode == 0, result.stderr
    results = project.results_dir(result)
    case = json.loads((results / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert (case["status"], case["with"], case["without"]) == ("ungradable", [], [])
    assert codex_execs(project) == []
    gated = project.run_script("gate", results)
    assert gated.returncode == 1
    assert any("codex behaviour/c1" in line and "evals/eval-skill.json" in line for line in fail_lines(gated))
    summary = project.run_script("summary", results).stdout
    assert row_for(summary, "c1")[5:8] == ["ungradable"] * 3


def test_codex_grades_a_mixed_case_on_the_regex_only(project):
    project.make_skill({"explicit/e1": None}, {"harnesses": ["claude", "codex"]})
    specs = [
        spec("skill-fired", "tool_used"),
        spec("shape", "regex", {"target": "last_message", "pattern": "workspace", "match": "contains"}),
    ]
    runs = [
        run_entry(
            [
                grader_result("skill-fired", "tool_used", True, scored=False, with_only=True),
                grader_result("shape", "regex", True),
            ]
        )
    ]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("explicit", "e1", specs, runs, runs)])}
    result = project.run()
    assert result.returncode == 0, result.stderr
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["explicit/e1"]
    assert case["status"] == "scored" and len(case["with"]) == 1 and len(case["without"]) == 1
    by_name = {g["name"]: g for g in case["with"][0]["graders"]}
    assert (by_name["skill-fired"]["applicable"], by_name["skill-fired"]["scored"]) == (False, False)
    assert (by_name["shape"]["applicable"], by_name["shape"]["scored"], by_name["shape"]["passed"]) == (
        True,
        True,
        True,
    )
    assert (case["with"][0]["score"], case["without"][0]["score"], case["delta"]) == (1.0, 0.0, 1.0)


def trigger_and_near_miss_eval() -> Json:
    t_specs = [spec("skill-fired", "tool_used")]
    t_with = [run_entry([grader_result("skill-fired", "tool_used", True, scored=False, with_only=True)])]
    n_specs = [spec("never", "tool_used", {"tool": "Skill", "min": 0, "max": 0})]
    n_with = [run_entry([grader_result("never", "tool_used", True)])]
    return eval_doc(
        [case_doc("trigger", "t1", t_specs, t_with, t_with), case_doc("near-miss", "n1", n_specs, n_with, n_with)]
    )


def test_real_env_arm_runs_trigger_and_near_miss_cases_in_a_fresh_directory(project):
    project.make_skill({"trigger/t1": "echo here > fixture.txt\n", "near-miss/n1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": trigger_and_near_miss_eval()}
    project.scenario["realenv"] = [
        {"match": "prompt t1", "modes": ["fired"]},
        {"match": "prompt n1", "modes": ["plain"]},
    ]
    result = project.run()
    assert result.returncode == 0, result.stderr
    real = [c for c in calls(project.env.home, "claude") if c["kind"] == "realenv"]
    assert len(real) == 2
    for call in real:
        assert opt(call["argv"], "--max-turns") == "2"
        assert opt(call["argv"], "--allowedTools") == "Skill"
        assert json.loads(opt(call["argv"], "--settings")) == {"disableAllHooks": True}
        assert not Path(call["cwd"]).exists()
    by_prompt = {c["prompt"]: c for c in real}
    assert "fixture.txt" in by_prompt["trigger prompt t1"]["files"]
    assert "fixture.txt" not in by_prompt["near-miss prompt n1"]["files"]
    doc = json.loads((project.results_dir(result) / "claude-real-env.json").read_text())
    trigger_run = doc["cases"]["trigger/t1"]["runs"][0]
    assert (trigger_run["fired"], trigger_run["error"], trigger_run["costUsd"]) == (True, None, 0.16)
    near_run = doc["cases"]["near-miss/n1"]["runs"][0]
    assert (near_run["fired"], near_run["error"]) == (False, None)
    assert project.run_script("gate", project.results_dir(result)).returncode == 0


def test_real_env_arm_records_a_near_miss_that_fires_and_the_gate_rejects_it(project):
    project.make_skill({"near-miss/n1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": trigger_and_near_miss_eval()}
    project.scenario["eval"]["isolated"]["cases"].pop(0)
    project.scenario["realenv"] = [{"match": "prompt n1", "modes": ["fired"]}]
    result = project.run()
    assert result.returncode == 0, result.stderr
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1
    assert any("claude-real-env" in line and "near-miss/n1" in line for line in gated.stdout.splitlines())


@pytest.mark.parametrize("mode", ["crash", "other-tool"])
def test_real_env_run_that_ends_without_a_trigger_decision_is_an_error(project, mode):
    project.make_skill({"trigger/t1": None}, {"harnesses": ["claude"]})
    doc = trigger_and_near_miss_eval()
    doc["cases"].pop(1)
    project.scenario["eval"] = {"isolated": doc}
    project.scenario["realenv"] = [{"match": "prompt t1", "modes": [mode]}]
    result = project.run()
    run = json.loads((project.results_dir(result) / "claude-real-env.json").read_text())["cases"]["trigger/t1"]["runs"][
        0
    ]
    if mode == "crash":
        assert run["error"] and result.returncode == 1
    else:
        # A first tool call other than Skill is still a recorded decision: the skill did not fire.
        assert run["error"] is None and run["fired"] is False
    assert project.run_script("gate", project.results_dir(result)).returncode == 1


def init_repo(env: IsolatedEnv, repo: Path) -> None:
    env.git(repo, "init", "-q")
    env.git(repo, "add", "-A")
    env.git(repo, "commit", "-q", "-m", "old skill")


def test_previous_arm_runs_the_old_skill_with_the_current_evals_and_fills_the_previous_column(project):
    """AC-10."""
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    (project.skill / "SKILL.md").write_text("---\nname: demo\n---\nOLD skill body\n")
    (project.skill / ".gitignore").write_text("")
    repo = project.skill.parent.parent
    (repo / ".gitignore").write_text("evals/results/\n")
    init_repo(project.env, repo)
    (project.skill / "SKILL.md").write_text("---\nname: demo\n---\nNEW skill body\n")
    # A new case that exists only in the working tree proves the previous arm uses the CURRENT evals.
    new_case = project.skill / "evals" / "behaviour" / "fresh"
    (new_case / "graders").mkdir(parents=True)
    (new_case / "prompt.md").write_text("fresh\n")
    (new_case / "graders" / "g.md").write_text("---\ntype: regex\npattern: x\n---\n")

    current = simple_eval()
    specs = current["cases"][0]["graders"]
    previous_runs = [run_entry([grader_result("shape", "regex", False)])]
    previous_case = case_doc("behaviour", "c1", specs, previous_runs)
    project.scenario["eval"] = {"isolated": current, "previous": eval_doc([previous_case], ablation="none")}
    result = project.run("--previous-ref", "HEAD")
    assert result.returncode == 0, result.stderr
    evals = [c for c in calls(project.env.home, "claude") if c["kind"] == "eval"]
    assert [c["arm"] for c in evals] == ["isolated", "previous"]
    assert "NEW skill body" in evals[0]["skill_md"] and "OLD skill body" in evals[1]["skill_md"]
    assert "evals/behaviour/fresh/prompt.md" in evals[1]["files"]
    assert "--no-publish" in evals[1]["argv"]
    results = project.results_dir(result)
    assert (results / "claude-previous.json").exists()
    manifest = json.loads((results / "manifest.json").read_text())
    assert evals[1]["plugin_json"]["name"] != manifest["wrapperPlugin"] == evals[0]["plugin_json"]["name"]
    summary = project.run_script("summary", results).stdout
    header = next(line for line in summary.splitlines() if line.startswith("| Case"))
    cells = [c.strip() for c in header.strip().strip("|").split("|")]
    assert cells[-2] == "Previous"
    assert row_for(summary, "c1")[-2] == "0.00"


def test_previous_arm_is_skipped_when_the_ref_does_not_contain_the_skill(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    repo = project.skill.parent.parent
    project.env.git(repo, "init", "-q")
    (repo / "README.md").write_text("x")
    project.env.git(repo, "add", "README.md")
    project.env.git(repo, "commit", "-q", "-m", "init")
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run("--previous-ref", "HEAD")
    assert result.returncode == 0, result.stderr
    assert [c["arm"] for c in calls(project.env.home, "claude") if c["kind"] == "eval"] == ["isolated"]
    summary = project.run_script("summary", project.results_dir(result)).stdout
    assert row_for(summary, "c1")[-2] == "n/a"


def test_run_reports_an_arm_error_when_claude_plugin_eval_exits_non_zero(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    project.scenario["eval_exit"] = {"isolated": 2}
    result = project.run()
    assert result.returncode == 1
    assert "claude-isolated" in result.stderr
    manifest = json.loads((project.results_dir(result) / "manifest.json").read_text())
    assert "claude-isolated" in manifest["armErrors"]
    assert project.run_script("gate", project.results_dir(result)).returncode == 1


def test_run_passes_the_case_filter_and_cost_ceiling_to_claude_plugin_eval(project):
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude"]})
    project.scenario["eval"] = {"isolated": simple_eval()}
    result = project.run("--case", "c*", "--max-cost-usd", "3", "--model", "m-1", "--judge-model", "j-1")
    assert result.returncode == 0, result.stderr
    argv = next(c for c in calls(project.env.home, "claude") if c["kind"] == "eval")["argv"]
    assert opt(argv, "--case") == "c*" and opt(argv, "--max-cost-usd") == "3"
    assert opt(argv, "--model") == "m-1" and opt(argv, "--judge-model") == "j-1"
    assert opt(argv, "--runs") == "1"


def test_ceil_two_thirds_matches_the_gate_rule():
    assert [math.ceil(2 * n / 3) for n in (1, 2, 3, 5)] == [1, 2, 2, 4]


def test_real_env_detects_a_skill_call_in_the_second_turn_so_a_late_near_miss_fire_fails_the_gate(project):
    project.make_skill({"near-miss/n1": None}, {"harnesses": ["claude"]})
    doc = trigger_and_near_miss_eval()
    doc["cases"].pop(0)
    project.scenario["eval"] = {"isolated": doc}
    project.scenario["realenv"] = [{"match": "prompt n1", "modes": ["other-then-skill"]}]
    result = project.run()
    assert result.returncode == 0, result.stderr
    [call] = [c for c in calls(project.env.home, "claude") if c["kind"] == "realenv"]
    assert opt(call["argv"], "--max-turns") == "2"
    run = json.loads((project.results_dir(result) / "claude-real-env.json").read_text())["cases"]["near-miss/n1"][
        "runs"
    ][0]
    assert (run["fired"], run["error"]) == (True, None)
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1
    assert any("claude-real-env" in line and "near-miss/n1" in line for line in gated.stdout.splitlines())


def test_codex_gets_dollar_name_for_an_explicit_case_and_other_prompts_unchanged(project):
    project.make_skill(
        {"explicit/e1": None, "behaviour/b1": None, "explicit/e2": None}, {"harnesses": ["claude", "codex"]}
    )
    graders = [spec("shape", "regex", {"target": "last_message", "pattern": "visible", "match": "contains"})]

    def one(kind: str, name: str, prompt: str) -> Json:
        runs = [run_entry([grader_result("shape", "regex", True)])]
        return case_doc(kind, name, graders, runs, runs, prompt=prompt)

    doc = eval_doc(
        [
            one("explicit", "e1", "/demo\n\nDo the thing"),
            one("explicit", "e2", "/demonstrate this"),
            one("behaviour", "b1", "/demo in a behaviour prompt"),
        ]
    )
    project.scenario["eval"] = {"isolated": doc}
    result = project.run()
    assert result.returncode == 0, result.stderr
    prompts = {c["prompt"] for c in codex_execs(project)}
    assert prompts == {"$demo\n\nDo the thing", "/demonstrate this", "/demo in a behaviour prompt"}
    for call in codex_execs(project):
        assert call["argv"][-2] == "--"


def codex_project(project) -> None:
    project.make_skill({"behaviour/c1": None}, {"harnesses": ["claude", "codex"]})
    project.scenario["eval"] = {"isolated": simple_eval()}


def test_codex_without_arm_has_no_skill_copy_in_its_workspace_to_find_and_read(project):
    codex_project(project)
    project.scenario["codex"] = {"mode": "snoop"}
    result = project.run()
    assert result.returncode == 0, result.stderr
    execs = [c for c in calls(project.env.home, "codex") if c["kind"] == "exec"]
    assert sorted(c["workspace_copy"] for c in execs) == [False, True]
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["lastMessage"] == "visible: workspace"
    assert case["without"][0]["lastMessage"] == "visible: none"


def test_concurrency_reaches_claude_and_keeps_case_and_run_order(project):
    project.make_skill({"trigger/t1": None, "trigger/t2": None, "trigger/t3": None}, {"harnesses": ["claude", "codex"]})
    t_specs = [spec("skill-fired", "tool_used")]
    runs = [run_entry([grader_result("skill-fired", "tool_used", True, scored=False, with_only=True)])] * 2
    project.scenario["eval"] = {
        "isolated": eval_doc([case_doc("trigger", f"t{i}", t_specs, runs, runs) for i in (1, 2, 3)])
    }
    # The first case is the slowest, so a result list built in finish order would be out of order.
    project.scenario["realenv"] = [
        {"match": "prompt t1", "modes": ["fired"], "sleep": 0.6},
        {"match": "prompt t2", "modes": ["fired"], "sleep": 0.3},
        {"match": "prompt t3", "modes": ["fired"]},
    ]
    result = project.run("--runs", "2", "--max-runs", "2", "--concurrency", "3")
    assert result.returncode == 0, result.stderr
    results = project.results_dir(result)
    for call in (c for c in calls(project.env.home, "claude") if c["kind"] == "eval"):
        assert opt(call["argv"], "-j") == "3"
    real = json.loads((results / "claude-real-env.json").read_text())
    assert list(real["cases"]) == ["trigger/t1", "trigger/t2", "trigger/t3"]
    assert all(len(entry["runs"]) == 2 for entry in real["cases"].values())
    codex = json.loads((results / "codex.json").read_text())
    assert list(codex["cases"]) == ["trigger/t1", "trigger/t2", "trigger/t3"]
    assert all(c["status"] == "not-run" for c in codex["cases"].values())
    assert codex_execs(project) == []


def test_concurrency_outside_one_to_eight_is_refused_before_anything_runs(project):
    codex_project(project)
    result = project.run("--concurrency", "9")
    assert result.returncode == 1
    assert "--concurrency" in result.stderr
    assert calls(project.env.home, "claude") == []


FAST = {"EVAL_SKILL_RETRY_DELAYS": "0,0"}


def codex_execs(project) -> list[Json]:
    return [c for c in calls(project.env.home, "codex") if c["kind"] == "exec"]


def test_codex_retries_a_capacity_error_and_records_the_retry_count(project):
    codex_project(project)
    project.scenario["codex"] = {"mode": "capacity_first", "fail_first": 2}
    result = project.run("--concurrency", "1", **FAST)
    assert result.returncode == 0, result.stderr
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert (case["with"][0]["error"], case["with"][0]["retries"], case["without"][0]["retries"]) == (None, 2, 0)
    assert case["with"][0]["lastMessage"] == "visible: workspace"
    assert len(codex_execs(project)) == 4


def test_codex_capacity_error_stands_after_two_retries_and_fails_the_gate(project):
    codex_project(project)
    project.scenario["codex"] = {"mode": "capacity"}
    result = project.run("--concurrency", "1", **FAST)
    assert result.returncode == 1
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert "at capacity" in case["with"][0]["error"] and case["with"][0]["retries"] == 2
    assert len(codex_execs(project)) == 6
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1 and "at capacity" in gated.stdout


def test_codex_error_that_is_not_transient_is_not_retried(project):
    codex_project(project)
    project.scenario["codex"] = {"mode": "turn_failed"}
    result = project.run("--concurrency", "1", **FAST)
    assert result.returncode == 1
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["retries"] == 0
    assert len(codex_execs(project)) == 2


def test_real_env_retries_an_overloaded_run(project):
    project.make_skill({"trigger/t1": None}, {"harnesses": ["claude"]})
    doc = trigger_and_near_miss_eval()
    doc["cases"].pop(1)
    project.scenario["eval"] = {"isolated": doc}
    project.scenario["realenv"] = [{"match": "prompt t1", "modes": ["overloaded-once"]}]
    result = project.run(**FAST)
    assert result.returncode == 0, result.stderr
    run = json.loads((project.results_dir(result) / "claude-real-env.json").read_text())["cases"]["trigger/t1"]["runs"][
        0
    ]
    assert (run["fired"], run["error"], run["retries"]) == (True, None, 1)


def test_judge_call_is_retried_after_a_rate_limit(project):
    codex_project(project)
    specs = [spec("quality", "llm", {"criteria": "Be brief."})]
    with_runs = [run_entry([grader_result("quality", "llm", True)])]
    project.scenario["eval"] = {"isolated": eval_doc([case_doc("behaviour", "c1", specs, with_runs, with_runs)])}
    project.scenario["votes"] = ["CAPACITY", "PASS", "PASS", "PASS"]
    result = project.run("--concurrency", "1", **FAST)
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert case["with"][0]["error"] is None
    assert case["with"][0]["graders"][0]["judgeVotes"] == [True, True, True]


def test_gate_keeps_the_run_error_lines_when_a_run_has_no_grader_results(run_script, isolated_env):
    """An errored run has no graders. That must not turn into an empty 'malformed' failure."""
    parts = base_parts(harnesses=("claude", "codex"))
    broken = parts["codex"]["cases"]["behaviour/b1"]["with"][1]
    broken.update(error="error event: Selected model is at capacity.", graders=[], score=None)
    claude_run = claude_case(parts, "behaviour/b1")["arms"]["with"][0]
    claude_run.update(error="boom", graders=[])
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    lines = fail_lines(result)
    assert any(line.startswith("FAIL codex behaviour/b1") and "at capacity" in line for line in lines)
    assert any(line.startswith("FAIL claude-isolated behaviour/b1") and "boom" in line for line in lines)
    assert "malformed" not in result.stdout


def test_gate_does_not_fail_trigger_and_near_miss_cases_that_codex_did_not_run(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    for key in ("trigger/t1", "near-miss/n1"):
        assert parts["codex"]["cases"][key]["status"] == "not-run"
    result = gate(run_script, isolated_env.root, parts)
    assert (result.returncode, fail_lines(result)) == (0, [])
    assert "PASS" in result.stdout
    # The Claude arms still gate these kinds.
    parts["claude-real-env"]["cases"]["trigger/t1"]["runs"][0]["fired"] = False
    broken = gate(run_script, isolated_env.root / "broken", parts)
    assert broken.returncode == 1 and any("trigger/t1" in line for line in fail_lines(broken))


def test_gate_fails_a_behaviour_case_that_codex_marked_not_run(run_script, isolated_env):
    """not-run is valid only for kinds that Codex skips. A skipped behaviour case is a hole in the evidence."""
    parts = base_parts(harnesses=("claude", "codex"))
    parts["codex"]["cases"]["behaviour/b1"] = {"status": "not-run", "with": [], "without": [], "delta": None}
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any(line.startswith("FAIL codex behaviour/b1") for line in fail_lines(result))


def test_gate_still_requires_the_codex_without_arm_for_a_behaviour_case(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    parts["codex"]["cases"]["behaviour/b1"]["without"] = []
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    assert any("codex" in line and "behaviour/b1" in line and "without" in line for line in fail_lines(result))


def test_summary_says_not_run_for_codex_trigger_and_near_miss_cases(run_script, isolated_env):
    results = write_results(isolated_env.root, base_parts(harnesses=("claude", "codex")))
    summary = run_script("summary", results).stdout
    for name in ("t1", "n1"):
        assert row_for(summary, name)[5:8] == ["not run"] * 3


def test_summary_says_ungradable_for_a_codex_case_without_a_grader_that_reads_the_reply(run_script, isolated_env):
    parts = base_parts(harnesses=("claude", "codex"))
    parts["codex"]["cases"]["behaviour/b1"] = {"status": "ungradable", "with": [], "without": [], "delta": None}
    summary = run_script("summary", write_results(isolated_env.root, parts)).stdout
    assert row_for(summary, "b1")[5:8] == ["ungradable"] * 3
    assert "FAIL" in row_for(summary, "b1")[-1]


def test_codex_runs_only_behaviour_and_explicit_cases_and_gives_the_without_arm_no_skill_copy(project):
    keys = ["behaviour/b1", "explicit/e1", "trigger/t1", "near-miss/n1"]
    project.make_skill({key: None for key in keys}, {"harnesses": ["claude", "codex"]})
    shape = [spec("shape", "regex", {"target": "last_message", "pattern": "visible", "match": "contains"})]
    runs = [run_entry([grader_result("shape", "regex", True)])]
    project.scenario["eval"] = {
        "isolated": eval_doc([case_doc(kind, name, shape, runs, runs) for kind, name in (k.split("/") for k in keys)])
    }
    result = project.run()
    assert result.returncode == 0, result.stderr
    # workspace_copy is False exactly for without-arm runs, which get no skill copy.
    by_prompt: dict[str, list[bool]] = {}
    for call in codex_execs(project):
        by_prompt.setdefault(call["prompt"], []).append(call["workspace_copy"])
    assert {k: sorted(v) for k, v in by_prompt.items()} == {
        "behaviour prompt b1": [False, True],
        "explicit prompt e1": [False, True],
    }
    results = project.results_dir(result)
    codex = json.loads((results / "codex.json").read_text())["cases"]
    for key in ("trigger/t1", "near-miss/n1"):
        assert (codex[key]["status"], codex[key]["with"], codex[key]["without"]) == ("not-run", [], [])
    assert len(codex["behaviour/b1"]["without"]) == 1 and len(codex["explicit/e1"]["without"]) == 1
    summary = project.run_script("summary", results).stdout
    for name in ("t1", "n1"):
        assert row_for(summary, name)[5:8] == ["not run"] * 3


REAL_ENV_MODES = [
    ("fired", True, None),
    ("other-skill-then-ours", True, None),
    ("fired-bare", None, "another copy of demo fired: demo"),
    ("fired-other-prefix", None, "another copy of demo fired: other-plugin:demo"),
]


@pytest.mark.parametrize(("mode", "fired", "error"), REAL_ENV_MODES)
def test_real_env_counts_only_the_wrapper_copy_of_the_skill_as_fired(project, mode, fired, error):
    project.make_skill({"trigger/t1": None}, {"harnesses": ["claude"]})
    doc = trigger_and_near_miss_eval()
    doc["cases"].pop(1)
    project.scenario["eval"] = {"isolated": doc}
    project.scenario["realenv"] = [{"match": "prompt t1", "modes": [mode]}]
    result = project.run()
    results = project.results_dir(result)
    run = json.loads((results / "claude-real-env.json").read_text())["cases"]["trigger/t1"]["runs"][0]
    if error is None:
        assert (run["fired"], run["error"]) == (fired, None)
    else:
        assert run["error"] and error in run["error"]
        assert run["fired"] is not True
        assert result.returncode == 1
        assert project.run_script("gate", results).returncode == 1


# --- sequential batches and the bootstrap gate for behaviour cases ---------------------------------------------------


REGEX = spec("shape", "regex", {"target": "last_message", "pattern": "visible", "match": "contains"})
LLM = spec("quality", "llm", {"criteria": "c", "focus": "last_message"})


def batch_eval(with_scores: list[int], without_scores: list[int], *, judged: bool = False) -> Json:
    """One `claude plugin eval` document for behaviour/c1. judged=True scores through an llm grader."""
    spec_ = LLM if judged else REGEX
    make = lambda s: run_entry([grader_result(spec_["name"], spec_["type"], bool(s))])  # noqa: E731
    return eval_doc(
        [case_doc("behaviour", "c1", [spec_], [make(s) for s in with_scores], [make(s) for s in without_scores])]
    )


def batch_project(project, batches: list[Json], *, harnesses: tuple[str, ...] = ("claude",)) -> None:
    project.make_skill({"behaviour/c1": None}, {"harnesses": list(harnesses)})
    project.scenario["eval"] = {"isolated_batches": batches}


def eval_calls(project) -> list[Json]:
    return [c for c in calls(project.env.home, "claude") if c["kind"] == "eval"]


def behaviour_runs(project, result, arm: str = "claude-isolated") -> tuple[int, int]:
    case = json.loads((project.results_dir(result) / f"{arm}.json").read_text())["cases"][0]
    return len(case["arms"]["with"]), len(case["arms"]["without"])


def test_a_clear_gain_in_the_first_batch_passes_without_an_extra_batch(project):
    batch_project(project, [batch_eval([1, 1, 1], [0, 0, 0])])
    result = project.run("--runs", "3", "--max-runs", "9")
    assert result.returncode == 0, result.stderr
    assert len(eval_calls(project)) == 1
    assert behaviour_runs(project, result) == (3, 3)
    gated = project.run_script("gate", project.results_dir(result))
    assert (gated.returncode, fail_lines(gated)) == (0, [])


def test_a_close_first_batch_runs_a_second_batch_and_passes_on_six_runs(project):
    batch_project(project, [batch_eval([1, 1, 1], [1, 1, 0]), batch_eval([1, 1, 1], [0, 0, 0])])
    result = project.run("--runs", "3", "--max-runs", "9")
    assert result.returncode == 0, result.stderr
    assert len(eval_calls(project)) == 2
    assert behaviour_runs(project, result) == (6, 6)
    gated = project.run_script("gate", project.results_dir(result))
    assert (gated.returncode, fail_lines(gated)) == (0, [])


def test_a_case_that_stays_close_at_max_runs_fails_the_gate_as_still_uncertain(project):
    # with scores [1,1,0] against without [1,0,0] each batch: delta +0.33, but the interval keeps spanning zero.
    batch_project(project, [batch_eval([1, 1, 0], [1, 0, 0], judged=True)])
    result = project.run("--runs", "3", "--max-runs", "9")
    assert len(eval_calls(project)) == 3
    assert behaviour_runs(project, result) == (9, 9)
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1
    lines = [line for line in fail_lines(gated) if "behaviour/c1" in line]
    assert len(lines) == 1
    assert re.search(r"delta \+0\.33 \[[+−]\d\.\d\d, [+−]\d\.\d\d\] still uncertain after 9 runs", lines[0])


def test_gate_fails_a_close_case_that_has_not_used_its_extra_batches(run_script, isolated_env):
    parts = base_parts()
    parts["manifest"]["maxRuns"] = 9
    case = claude_case(parts, "behaviour/b1")
    case["arms"]["without"] = [
        run_entry([grader_result(DET, "regex", p), grader_result(JUDGE, "llm", p)]) for p in (True, True, False)
    ]
    result = gate(run_script, isolated_env.root, parts)
    assert result.returncode == 1
    lines = [line for line in fail_lines(result) if "behaviour/b1" in line]
    assert len(lines) == 1
    assert "uncertain after 3 runs, needs more runs (max 9)" in lines[0]


def test_no_gain_fails_the_gate_and_runs_no_extra_batch(project):
    batch_project(project, [batch_eval([1, 1, 1], [1, 1, 1])])
    result = project.run("--runs", "3", "--max-runs", "9")
    assert len(eval_calls(project)) == 1
    assert behaviour_runs(project, result) == (3, 3)
    gated = project.run_script("gate", project.results_dir(result))
    assert gated.returncode == 1
    lines = [line for line in fail_lines(gated) if "behaviour/c1" in line]
    assert len(lines) == 1
    assert "delta +0.00 [+0.00, +0.00], no gain" in lines[0]


def test_gate_prints_the_same_verdict_and_interval_on_every_run(run_script, isolated_env):
    parts = base_parts()
    parts["manifest"]["maxRuns"] = 3
    case = claude_case(parts, "behaviour/b1")
    case["arms"]["without"] = [
        run_entry([grader_result(DET, "regex", p), grader_result(JUDGE, "llm", p)]) for p in (True, True, False)
    ]
    results = write_results(isolated_env.root, parts)
    first = run_script("gate", results)
    second = run_script("gate", results)
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert re.search(r"behaviour/b1.*\[[+−]\d\.\d\d, [+−]\d\.\d\d\]", first.stdout)


@pytest.mark.parametrize("flags", [("--runs", "3", "--max-runs", "7"), ("--runs", "6", "--max-runs", "3")])
def test_an_invalid_max_runs_is_refused_before_any_model_call(project, flags):
    batch_project(project, [batch_eval([1, 1, 1], [0, 0, 0])])
    result = project.run(*flags)
    assert result.returncode == 1
    assert "--max-runs" in result.stderr
    assert calls(project.env.home, "claude") == []
    assert calls(project.env.home, "codex") == []


def test_codex_extends_a_close_case_and_passes_on_six_runs(project):
    batch_project(project, [batch_eval([1, 1, 1], [0, 0, 0])], harnesses=("claude", "codex"))
    project.scenario["codex"] = {
        "with_messages": ["visible"],
        "without_messages": ["visible", "visible", "nothing", "nothing"],
    }
    result = project.run("--runs", "3", "--max-runs", "9", "--concurrency", "1", **FAST)
    assert result.returncode == 0, result.stderr
    case = json.loads((project.results_dir(result) / "codex.json").read_text())["cases"]["behaviour/c1"]
    assert (len(case["with"]), len(case["without"])) == (6, 6)
    assert len(codex_execs(project)) == 12
    gated = project.run_script("gate", project.results_dir(result))
    assert (gated.returncode, fail_lines(gated)) == (0, [])
