#!/usr/bin/env python3
"""Gate one dotfiles skill with behaviour evals on Claude Code and Codex.

Three subcommands:

  eval_skill.py run <skill-dir> [options]   run every arm, print the results directory
  eval_skill.py gate <results-dir>          apply the pass rule; exit 0 pass, 1 fail
  eval_skill.py summary <results-dir>       print a Markdown summary for a PR body

Standard library only, Python 3.9. The cases (prompt.md, graders/*.md, case.yaml) are parsed by
`claude plugin eval`, so this script reads that command's JSON and never parses YAML.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Json = dict[str, Any]

KINDS = ("behaviour", "trigger", "near-miss", "explicit")
HARNESSES = ("claude", "codex")
CONFIG_KEYS = {"harnesses"}
# Judge-style graders are noisy, so they need ceil(2N/3) passing runs. Every other grader type is
# deterministic and must pass in every run.
JUDGE_TYPES = {"llm", "baseline"}
PREVIOUS_ARM = "claude-previous"
# Codex runs only these kinds, with and without the skill. It records no skill-invocation event, so the
# Claude arms alone decide trigger and near-miss cases.
CODEX_KINDS = {"behaviour", "explicit"}

# Real-environment trigger check: `claude -p` stops after this many turns, and a Skill tool_use in any
# turn counts as fired. Proven with a real run on 2026-10-18 (claude 2.1.295, claude-opus-5-5): with
# --max-turns 1 a firing prompt records the Skill tool_use in turn 1 and ends with result subtype
# error_max_turns and exit 1; a plain answer ends with subtype success. We use 2 because with 1 a
# near-miss whose first turn tries another (denied) tool and fires Skill in turn 2 reads as "not
# fired", a false pass in the gate. A stop at max turns after a tool call is not an error.
REAL_ENV_MAX_TURNS = 2

# Proven with a real run on 2026-10-18: `--tools "" --json-schema` returns `structured_output.verdict`
# in the result JSON when the prompt arrives on stdin.
JUDGE_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": ["PASS", "FAIL"]}},
        "required": ["verdict"],
    }
)
JUDGE_VOTES = 3


# A run that fails only because the provider is busy gets up to two more tries, after these delays.
TRANSIENT_ERROR = re.compile(r"at capacity|rate limit|429|overloaded", re.IGNORECASE)
DEFAULT_RETRY_DELAYS = "30,90"


def retry_delays() -> list[float]:
    """Seconds to wait before retry 1 and retry 2. EVAL_SKILL_RETRY_DELAYS="0,0" makes tests fast."""
    raw = os.environ.get("EVAL_SKILL_RETRY_DELAYS", DEFAULT_RETRY_DELAYS)
    return [float(part) for part in raw.split(",") if part.strip()]


def is_transient(text: str) -> bool:
    return bool(TRANSIENT_ERROR.search(text))


class SetupError(Exception):
    """A problem that stops the command before or between arms. The message goes to stderr."""


class JudgeError(Exception):
    """A judge call failed or returned no verdict."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --- small helpers ---------------------------------------------------------------------------------------------------


def load_json(path: Path) -> Json:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def need_for(grader_type: str, runs: int) -> int:
    """Passing runs a grader needs: every run, or ceil(2N/3) for judge graders."""
    return math.ceil(2 * runs / 3) if grader_type in JUDGE_TYPES else runs


# --- the behaviour delta: bootstrap interval and outcome ---

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = "eval-skill-bootstrap-v1"
DEFAULT_RUNS = 3
DEFAULT_MAX_RUNS = 9


def bootstrap_seed(harness: str, key: str) -> int:
    """A seed that depends only on the harness and the case key, so the same results give the same interval."""
    digest = hashlib.sha256(f"{BOOTSTRAP_SEED}|{harness}|{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_interval(
    with_scores: list[float], without_scores: list[float], harness: str, key: str
) -> tuple[float, float]:
    """95% percentile bootstrap interval for mean(with) - mean(without). Each arm resamples on its own."""
    rng = random.Random(bootstrap_seed(harness, key))
    deltas = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        a = rng.choices(with_scores, k=len(with_scores))
        b = rng.choices(without_scores, k=len(without_scores))
        deltas.append(sum(a) / len(a) - sum(b) / len(b))
    deltas.sort()
    low = deltas[int(BOOTSTRAP_RESAMPLES * 0.025)]
    high = deltas[int(BOOTSTRAP_RESAMPLES * 0.975) - 1]
    return round(low, 9) + 0.0, round(high, 9) + 0.0


def delta_outcome(low: float, high: float) -> str:
    """pass: the whole interval is above zero. no-gain: it is at or below zero. close: it spans zero."""
    if low > 0:
        return "pass"
    if high <= 0:
        return "no-gain"
    return "close"


def assess(with_scores: list[float], without_scores: list[float], harness: str, key: str) -> Json | None:
    """The look at one case: delta, interval, outcome, and run count. None when an arm has no scores."""
    if not with_scores or not without_scores:
        return None
    low, high = bootstrap_interval(with_scores, without_scores, harness, key)
    delta = round(sum(with_scores) / len(with_scores) - sum(without_scores) / len(without_scores), 9) + 0.0
    return {
        "runs": len(with_scores),
        "delta": delta,
        "low": low,
        "high": high,
        "outcome": delta_outcome(low, high),
    }


def fmt_interval(look: Json) -> str:
    text = f"{look['delta']:+.2f} [{look['low']:+.2f}, {look['high']:+.2f}]"
    return text.replace("-", "\u2212")


def tail(text: str, limit: int = 300) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return (lines[-1] if lines else "no output")[:limit]


def run_command(
    cmd: list[str], *, cwd: Path | str | None = None, input_text: str | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a command with stdin from /dev/null (or input_text) and capture text output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        stdin=None if input_text is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def tool_version(tool: str) -> str:
    try:
        result = run_command([tool, "--version"], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f"cannot run `{tool} --version`: {error}") from error
    if result.returncode != 0:
        raise SetupError(f"`{tool} --version` failed (exit {result.returncode}): {tail(result.stderr)}")
    return result.stdout.strip()


def git_output(cwd: Path, *args: str) -> str | None:
    try:
        result = run_command(["git", *args], cwd=cwd, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


# --- skill, config, and case discovery -------------------------------------------------------------------------------


def load_config(skill_dir: Path) -> list[str]:
    path = skill_dir / "evals" / "eval-skill.json"
    if not path.exists():
        return list(HARNESSES)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SetupError(f"{path}: not valid JSON ({error})") from error
    if not isinstance(config, dict):
        raise SetupError(f"{path}: must be a JSON object")
    unknown = sorted(set(config) - CONFIG_KEYS)
    if unknown:
        raise SetupError(f"{path}: unknown key {unknown[0]!r}; allowed keys: {sorted(CONFIG_KEYS)}")
    harnesses = config.get("harnesses", list(HARNESSES))
    if not isinstance(harnesses, list) or not harnesses:
        raise SetupError(f"{path}: harnesses must be a non-empty list of {list(HARNESSES)}")
    for value in harnesses:
        if value not in HARNESSES:
            raise SetupError(f"{path}: unknown harnesses value {value!r}; allowed values: {list(HARNESSES)}")
    return [h for h in HARNESSES if h in harnesses]


def discover_cases(skill_dir: Path, case_glob: str | None) -> list[str]:
    """Return sorted "kind/name" keys. A case is a folder with prompt.md or case.yaml, exactly two levels down."""
    evals = skill_dir / "evals"
    if not evals.is_dir():
        raise SetupError(f"{evals} does not exist: the skill has no evals")
    found: list[str] = []
    for base, dirs, files in os.walk(evals):
        rel = Path(base).relative_to(evals)
        skip = {"graders", "fixtures"} | ({"results"} if rel == Path(".") else set())
        dirs[:] = sorted(d for d in dirs if d not in skip)
        if rel == Path("."):
            continue
        if "prompt.md" in files or "case.yaml" in files:
            parts = rel.parts
            if len(parts) != 2:
                raise SetupError(f"case {rel} must sit directly under evals/<kind>/, as evals/<kind>/<case>")
            if parts[0] not in KINDS:
                raise SetupError(f"case {rel} is in the unknown kind {parts[0]!r}; kinds: {', '.join(KINDS)}")
            if case_glob is None or fnmatch.fnmatch(parts[1], case_glob):
                found.append(f"{parts[0]}/{parts[1]}")
            dirs[:] = []
    if not found:
        raise SetupError("no eval cases found" + (f" matching {case_glob!r}" if case_glob else ""))
    return sorted(found)


def codex_skills_config_conflict() -> str | None:
    """A -c skills.config override replaces the whole array, so a configured array would be lost."""
    home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    path = Path(home) / "config.toml"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    table = re.search(r"^\s*\[skills\]\s*$(.*?)(?=^\s*\[|\Z)", text, re.M | re.S)
    if (
        re.search(r"^\s*\[\[\s*skills\.config\s*\]\]", text, re.M)
        or re.search(r"^\s*skills\.config\s*=", text, re.M)
        or (table and re.search(r"^\s*config\s*=", table.group(1), re.M))
    ):
        return str(path)
    return None


# --- wrapper plugin --------------------------------------------------------------------------------------------------


def copy_skill(src: Path, dest: Path) -> None:
    """Copy a skill folder without its evals/ folder."""
    shutil.copytree(src, dest, ignore=lambda directory, names: ["evals"] if Path(directory) == src else [])


def wrapper_plugin_name(name: str) -> str:
    """A new plugin name for each wrapper, so a run can tell the copy under test from any other copy."""
    return f"eval-{name}-{secrets.token_hex(4)}"


def build_wrapper(parent: Path, name: str, plugin: str, skill_src: Path, evals_src: Path) -> Path:
    """Build <plugin>/ with plugin.json, a copy of the skill, and a copy of its evals (no results/)."""
    wrapper = parent / plugin
    (wrapper / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": plugin, "version": "0.0.0", "description": f"Temporary eval wrapper for {name}"}
    (wrapper / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    copy_skill(skill_src, wrapper / "skills" / name)
    shutil.copytree(
        evals_src,
        wrapper / "evals",
        ignore=lambda directory, names: ["results"] if Path(directory) == evals_src else [],
    )
    return wrapper


def export_previous_skill(repo: Path, ref: str, rel: str, dest: Path) -> bool:
    """Export the skill folder at ref with git archive. Return False when SKILL.md is not in that ref."""
    if git_output(repo, "cat-file", "-e", f"{ref}:{rel}/SKILL.md") is None:
        return False
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, "--", rel],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise SetupError(f"git archive {ref} failed: {tail(result.stderr.decode('utf-8', 'replace'))}")
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive.getmembers():
            target = os.path.normpath(member.name)
            if target.startswith("..") or os.path.isabs(target) or member.issym() or member.islnk():
                continue
            archive.extract(member, dest)
    return True


# --- arm 1 and 5: claude plugin eval ---------------------------------------------------------------------------------


def claude_eval(
    wrapper: Path,
    out: Path,
    arm: str,
    opts: argparse.Namespace,
    *,
    ablation_none: bool,
    case: str | None = None,
    runs: int | None = None,
    max_cost: float | None = None,
    stem: str | None = None,
) -> tuple[Json | None, str | None]:
    """Run `claude plugin eval` and return (run JSON or None, error text or None).

    case, runs, max_cost and stem override the options for one extra batch. stem names the JSON, log and output folder.
    """
    stem = stem or arm
    json_path = out / f"{stem}.json"
    case = case if case is not None else opts.case
    max_cost = max_cost if max_cost is not None else opts.max_cost_usd
    cmd = [
        "claude",
        "plugin",
        "eval",
        str(wrapper),
        "--runs",
        str(runs if runs is not None else opts.runs),
        "--scaffold",
        "--model",
        opts.model,
        "--judge-model",
        opts.judge_model,
        "--threshold",
        "0",
        "--no-publish",
        "--trust-plugin",
        "--max-cost-usd",
        f"{max_cost:g}",
        "-j",
        str(opts.concurrency),
        "--json",
        str(json_path),
        "--output-dir",
        str(out / stem),
    ]
    if ablation_none:
        cmd += ["--ablation", "none"]
    if case:
        cmd += ["--case", case]
    try:
        result = run_command(cmd, cwd=wrapper.parent)
    except OSError as error:
        return None, f"cannot start claude plugin eval: {error}"
    (out / f"{stem}.log").write_text(result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
    error_text = None
    if result.returncode != 0:
        error_text = f"claude plugin eval exited {result.returncode}: {tail(result.stderr or result.stdout)}"
    doc: Json | None = None
    try:
        doc = load_json(json_path)
    except (OSError, ValueError) as problem:
        error_text = error_text or f"claude plugin eval wrote no readable JSON: {problem}"
    return doc, error_text


def case_key(case: Json) -> str | None:
    parts = str(case.get("dir", "")).split("/")
    if len(parts) == 3 and parts[0] == "evals":
        return f"{parts[1]}/{parts[2]}"
    return None


# --- arm 2: real-environment trigger check ---------------------------------------------------------------------------


def run_scaffold(scaffold: Path, workspace: Path) -> str | None:
    if not scaffold.exists():
        return None
    result = run_command(["bash", str(scaffold)], cwd=workspace, timeout=300)
    if result.returncode != 0:
        return f"scaffold.sh exited {result.returncode}: {tail(result.stderr or result.stdout)}"
    return None


def classify_real_env(stdout: str, name: str, plugin: str) -> Json:
    """Read a stream-json transcript. Return fired, error, and costUsd.

    Only the call `<plugin>:<name>` counts as fired. Another copy of the skill is a run error.
    """
    pattern = re.compile(rf"^(?:[\w-]+:)?{re.escape(name)}$")
    fired = False
    other_copy: str | None = None
    saw_tool_use = False
    result_event: Json | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "assistant":
            content = (event.get("message") or {}).get("content") or []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    saw_tool_use = True
                    called = str((block.get("input") or {}).get("skill", ""))
                    if block.get("name") != "Skill" or not pattern.match(called):
                        continue
                    if called == f"{plugin}:{name}":
                        fired = True
                    else:
                        other_copy = other_copy or called
        elif event.get("type") == "result":
            result_event = event
    cost = float((result_event or {}).get("total_cost_usd") or 0)
    error = None
    if other_copy is not None:
        error = f"another copy of {name} fired: {other_copy}"
    elif result_event is None:
        error = "no result event in the transcript"
    elif result_event.get("subtype") == "success":
        pass
    elif result_event.get("subtype") == "error_max_turns" and saw_tool_use:
        pass
    else:
        error = f"run ended with {result_event.get('subtype')}"
    return {"fired": fired and other_copy is None, "error": error, "costUsd": cost}


def real_env_run(
    wrapper: Path, out: Path, case: Json, key: str, index: int, opts: argparse.Namespace, name: str
) -> Json:
    """One `claude -p` run in a fresh empty working directory."""
    plugin = wrapper.name
    record: Json = {"fired": False, "error": None, "costUsd": 0.0, "retries": 0}
    timeout = float(case.get("timeoutSeconds") or 300) + 60
    workspace = Path(tempfile.mkdtemp(prefix="eval-skill-real-"))
    try:
        problem = run_scaffold(wrapper / str(case["dir"]) / "scaffold.sh", workspace)
        if problem:
            record["error"] = problem
            return record
        cmd = [
            "claude",
            "-p",
            "--plugin-dir",
            str(wrapper),
            "--model",
            opts.model,
            "--output-format",
            "stream-json",
            "--verbose",
            "--strict-mcp-config",
            "--settings",
            '{"disableAllHooks": true}',
            "--allowedTools",
            "Skill",
            "--max-turns",
            str(REAL_ENV_MAX_TURNS),
            "--no-session-persistence",
            "--",
            str(case.get("promptMarkdown", "")),
        ]
        delays = retry_delays()
        retries = 0
        while True:
            try:
                result = run_command(cmd, cwd=workspace, timeout=timeout)
            except subprocess.TimeoutExpired:
                record["error"] = f"timed out after {timeout:.0f}s"
                return record
            except OSError as error:
                record["error"] = f"cannot start claude: {error}"
                return record
            raw = out / "claude-real-env" / key.replace("/", "__")
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"run-{index + 1}.jsonl").write_text(result.stdout, encoding="utf-8")
            record = classify_real_env(result.stdout, name, plugin)
            if record["error"] and result.returncode != 0:
                record["error"] += f" (exit {result.returncode}: {tail(result.stderr)})"
            if record["error"] and is_transient(result.stdout + result.stderr) and retries < len(delays):
                time.sleep(delays[retries])
                retries += 1
                continue
            record["retries"] = retries
            return record
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def real_env_arm(wrapper: Path, out: Path, cases: list[Json], opts: argparse.Namespace, name: str) -> Json:
    doc: Json = {"model": opts.model, "maxTurns": REAL_ENV_MAX_TURNS, "cases": {}}
    spent = [0.0]
    lock = threading.Lock()

    def task(case: Json, key: str, index: int) -> Json:
        # The cost ceiling is checked before each run starts, so overrun is bounded to the runs in flight.
        with lock:
            over = spent[0] > opts.max_cost_usd
        if over:
            return {
                "fired": False,
                "error": f"cost ceiling ${opts.max_cost_usd} reached before this run",
                "costUsd": 0.0,
            }
        record = real_env_run(wrapper, out, case, key, index, opts, name)
        with lock:
            spent[0] += float(record["costUsd"])
        return record

    with ThreadPoolExecutor(max_workers=opts.concurrency) as pool:
        futures: dict[str, list[Any]] = {}
        for case in cases:
            key = case_key(case)
            if key is None or key.split("/")[0] not in {"trigger", "near-miss"}:
                continue
            futures[key] = [pool.submit(task, case, key, index) for index in range(opts.runs)]
        for key, runs in futures.items():
            doc["cases"][key] = {"runs": [f.result() for f in runs]}
    return doc


# --- arm 3 and 4: Codex ----------------------------------------------------------------------------------------------


def judge_votes(criteria: str, text: str, judge_model: str) -> tuple[list[bool], float]:
    """Ask the pinned judge three times. Raise JudgeError when any call fails."""
    prompt = (
        "You grade one reply against a rubric. Answer PASS only if the reply satisfies the rubric.\n\n"
        f"Rubric:\n{criteria}\n\nReply to grade:\n<<<\n{text}\n>>>\n"
    )
    votes: list[bool] = []
    cost = 0.0
    scratch = Path(tempfile.mkdtemp(prefix="eval-skill-judge-"))
    try:
        for _ in range(JUDGE_VOTES):
            cmd = [
                "claude",
                "-p",
                "--model",
                judge_model,
                "--tools",
                "",
                "--strict-mcp-config",
                "--settings",
                '{"disableAllHooks": true}',
                "--no-session-persistence",
                "--output-format",
                "json",
                "--json-schema",
                JUDGE_SCHEMA,
            ]
            delays = retry_delays()
            attempt = 0
            while True:
                try:
                    result = run_command(cmd, cwd=scratch, input_text=prompt, timeout=300)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise JudgeError(f"judge call failed: {error}") from error
                if result.returncode != 0 and is_transient(result.stdout + result.stderr) and attempt < len(delays):
                    time.sleep(delays[attempt])
                    attempt += 1
                    continue
                break
            if result.returncode != 0:
                raise JudgeError(f"judge call exited {result.returncode}: {tail(result.stderr or result.stdout)}")
            try:
                reply = json.loads(result.stdout)
                structured = reply.get("structured_output")
                verdict = (
                    structured.get("verdict")
                    if isinstance(structured, dict)
                    else json.loads(reply["result"])["verdict"]
                )
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise JudgeError(f"judge reply has no verdict: {tail(result.stdout)}") from error
            if verdict not in {"PASS", "FAIL"}:
                raise JudgeError(f"judge verdict {verdict!r} is not PASS or FAIL")
            votes.append(verdict == "PASS")
            cost += float(reply.get("total_cost_usd") or 0)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return votes, cost


def parse_codex_events(stdout: str) -> list[Json]:
    events: list[Json] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def codex_run_facts(events: list[Json], returncode: int) -> Json:
    """Last message, token usage, and the run error (if any).

    An item.completed event with item.type "error" is a warning, not a run error.
    """
    last_message = ""
    usage: Json = {}
    error = None
    completed = False
    for event in events:
        kind = event.get("type")
        raw_item = event.get("item")
        item: Json = raw_item if isinstance(raw_item, dict) else {}
        if kind == "item.completed":
            if item.get("type") == "agent_message":
                last_message = str(item.get("text", ""))
        elif kind == "turn.completed":
            completed = True
            usage = event.get("usage") or {}
        elif kind == "turn.failed":
            error = error or f"turn.failed: {json.dumps(event.get('error'))[:200]}"
        elif kind == "error":
            error = error or f"error event: {str(event.get('message'))[:200]}"
    if error is None and returncode != 0:
        error = f"codex exited {returncode}"
    if error is None and not completed:
        error = "no turn.completed event"
    return {
        "lastMessage": last_message,
        "tokens": {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0)},
        "error": error,
    }


FLAG_BITS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}


def codex_can_grade(grader: Json) -> bool:
    """Codex grades only graders that read the final reply: regex and llm on last_message."""
    config = grader.get("config") or {}
    if grader.get("type") in {"regex", "llm"}:
        return config.get("target", config.get("focus", "last_message")) == "last_message"
    return False


def grade_codex_run(facts: Json, specs: list[Json], judge_model: str) -> tuple[list[Json], float]:
    """Grade one Codex run. Return the grader results and the judge cost. Raise JudgeError or ValueError."""
    results: list[Json] = []
    judge_cost = 0.0
    for grader in specs:
        gtype = grader.get("type")
        config = grader.get("config") or {}
        entry: Json = {
            "name": grader["name"],
            "type": gtype,
            "weight": grader.get("weight", 1),
            "passed": None,
            "applicable": False,
            "scored": False,
        }
        if codex_can_grade(grader) and gtype == "regex":
            flags = 0
            for letter in str(config.get("flags", "")):
                flags |= FLAG_BITS.get(letter, 0)
            hits = len(list(re.finditer(str(config.get("pattern", "")), facts["lastMessage"], flags)))
            match = str(config.get("match", "contains"))
            if match == "contains":
                passed = hits > 0
            elif match == "not_contains":
                passed = hits == 0
            elif match.startswith("count:"):
                passed = hits == int(match.split(":", 1)[1])
            else:
                raise ValueError(f"grader {grader['name']}: unknown match {match!r}")
            entry.update(passed=passed, applicable=True, scored=True)
        elif codex_can_grade(grader) and gtype == "llm":
            criteria = str(config.get("criteria") or grader.get("graderMarkdown") or "")
            votes, cost = judge_votes(criteria, facts["lastMessage"], judge_model)
            judge_cost += cost
            entry.update(passed=sum(votes) >= 2, applicable=True, scored=True, judgeVotes=votes)
        results.append(entry)
    return results, judge_cost


def score_run(graders: list[Json]) -> float | None:
    scored = [g for g in graders if g["scored"] and g["applicable"]]
    total = sum(g["weight"] for g in scored)
    if not total:
        return None
    return sum(g["weight"] for g in scored if g["passed"]) / total


def codex_case_status(kind: str, specs: list[Json]) -> str:
    """not-run: Codex does not run this kind. ungradable: no grader reads the final reply. scored: it runs."""
    if kind not in CODEX_KINDS:
        return "not-run"
    return "scored" if any(codex_can_grade(g) for g in specs) else "ungradable"


def codex_prompt(key: str, name: str, prompt: str) -> str:
    """Codex invokes a skill explicitly with $name, so an explicit case's leading /name becomes $name."""
    if key.startswith("explicit/") and re.match(rf"/{re.escape(name)}(?:\s|$)", prompt):
        return "$" + prompt[1:]
    return prompt


def codex_one_run(
    wrapper: Path,
    out: Path,
    case: Json,
    key: str,
    arm: str,
    index: int,
    opts: argparse.Namespace,
    name: str,
) -> Json:
    """One `codex exec` run in a fresh workspace, graded. The installed skill copy is always hidden."""
    record: Json = {
        "score": None,
        "error": None,
        "lastMessage": "",
        "tokens": {"input": 0, "output": 0},
        "graders": [],
        "judgeCostUsd": 0.0,
        "retries": 0,
    }
    installed = Path.home() / ".agents" / "skills" / name / "SKILL.md"
    workspace = Path(os.path.realpath(tempfile.mkdtemp(prefix="eval-skill-codex-")))
    try:
        problem = run_scaffold(wrapper / str(case["dir"]) / "scaffold.sh", workspace)
        if problem:
            record["error"] = problem
            return record
        # The without-arm gets no copy at all: a disabled copy can still be found with find and read with cat.
        if arm == "with":
            copy_skill(wrapper / "skills" / name, workspace / ".agents" / "skills" / name)
        disabled: list[Path] = []
        if installed.exists():
            disabled.append(installed)
        entries = ", ".join("{path=" + json.dumps(str(path)) + ", enabled=false}" for path in disabled)
        cmd = [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "-s",
            "read-only",
            "-m",
            opts.codex_model,
            "-c",
            f"skills.config=[{entries}]",
            "--",
            codex_prompt(key, name, str(case.get("promptMarkdown", ""))),
        ]
        timeout = float(case.get("timeoutSeconds") or 300) + 60
        delays = retry_delays()
        while True:
            try:
                result = run_command(cmd, cwd=workspace, timeout=timeout)
            except subprocess.TimeoutExpired:
                record["error"] = f"codex timed out after {timeout:.0f}s"
                return record
            except OSError as error:
                record["error"] = f"cannot start codex: {error}"
                return record
            raw = out / "codex" / key.replace("/", "__")
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"{arm}-{index + 1}.jsonl").write_text(result.stdout, encoding="utf-8")
            facts = codex_run_facts(parse_codex_events(result.stdout), result.returncode)
            # Retry only a run that failed on a transient provider error. A finished run is never retried.
            if facts["error"] and is_transient(facts["error"]) and record["retries"] < len(delays):
                time.sleep(delays[record["retries"]])
                record["retries"] += 1
                continue
            break
        record.update(
            lastMessage=facts["lastMessage"],
            tokens=facts["tokens"],
            error=facts["error"],
        )
        if record["error"] is None:
            try:
                graders, cost = grade_codex_run(facts, case.get("graders") or [], opts.judge_model)
            except JudgeError as error:
                record["error"] = f"judge failed: {error}"
            except (ValueError, KeyError, re.error) as error:
                record["error"] = f"grading failed: {error}"
            else:
                record.update(graders=graders, score=score_run(graders), judgeCostUsd=cost)
        return record
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def codex_arm(
    wrapper: Path,
    out: Path,
    cases: list[Json],
    opts: argparse.Namespace,
    name: str,
    *,
    doc: Json | None = None,
    only: set[str] | None = None,
    count: int | None = None,
) -> Json:
    """Run the Codex arm. With doc and only, add count more runs to the named cases of an earlier result."""
    count = opts.runs if count is None else count
    extending = doc is not None
    if doc is None:
        doc = {
            "model": opts.codex_model,
            "judgeModel": opts.judge_model,
            "tokens": {"input": 0, "output": 0},
            "judgeCostUsd": 0.0,
            "cases": {},
        }
    plans: list[tuple[str, Json, dict[str, list[Any]]]] = []
    with ThreadPoolExecutor(max_workers=opts.concurrency) as pool:
        for case in cases:
            key = case_key(case)
            if key is None or (only is not None and key not in only):
                continue
            if extending:
                case_doc = doc["cases"][key]
            else:
                kind = key.split("/")[0]
                status = codex_case_status(kind, case.get("graders") or [])
                if status != "scored":
                    doc["cases"][key] = {"status": status, "with": [], "without": [], "delta": None}
                    continue
                case_doc = doc["cases"][key] = {"status": status, "with": [], "without": []}
            futures = {
                arm: [
                    # Run indices continue from the runs already there, so raw output files never collide.
                    pool.submit(codex_one_run, wrapper, out, case, key, arm, index, opts, name)
                    for index in range(len(case_doc[arm]), len(case_doc[arm]) + count)
                ]
                for arm in ("with", "without")
            }
            plans.append((key, case_doc, futures))
        for key, case_doc, futures in plans:
            for arm in futures:
                for future in futures[arm]:
                    record = future.result()
                    doc["tokens"]["input"] += record["tokens"]["input"]
                    doc["tokens"]["output"] += record["tokens"]["output"]
                    doc["judgeCostUsd"] += record.pop("judgeCostUsd", 0.0)
                    case_doc[arm].append(record)
            look = assess(numbers(case_doc["with"]), numbers(case_doc["without"]), "codex", key)
            case_doc["delta"] = look["delta"] if look else None
            if look:
                case_doc.setdefault("looks", []).append(look)
    return doc


def codex_needs_more(entry: Json, key: str, max_runs: int) -> bool:
    """A scored behaviour case whose last look is close, with no run error and room for another batch."""
    looks = entry.get("looks") or []
    return (
        key.startswith("behaviour/")
        and entry.get("status") == "scored"
        and bool(looks)
        and looks[-1]["outcome"] == "close"
        and len(entry["with"]) < max_runs
        and not any(r["error"] is not None for arm in ("with", "without") for r in entry[arm])
    )


# --- run -------------------------------------------------------------------------------------------------------------


def state_root(override: str | None) -> Path:
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "eval-skill"


def new_results_dir(root: Path, name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    parent = root / name
    parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(100):
        candidate = parent / (stamp if attempt == 0 else f"{stamp}-{attempt}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise SetupError(f"cannot create a results directory under {parent}")


def check_max_runs(opts: argparse.Namespace) -> None:
    if opts.max_runs < opts.runs or opts.max_runs % opts.runs != 0:
        raise SetupError(
            f"--max-runs {opts.max_runs} must be a multiple of --runs {opts.runs} and not less than --runs"
        )


def claude_run_cost(doc: Json) -> float:
    """Spend so far in one Claude results document: the eval cost plus the judge cost of each run."""
    total = float(doc.get("costUsd") or 0)
    for case in doc.get("cases", []):
        for runs in (case.get("arms") or {}).values():
            total += sum(numbers(runs, "judgeCostUsd"))
    return total


def merge_claude_batch(doc: Json, batch: Json, error: str | None) -> None:
    """Add the runs of an extra batch to the same cases in the main document and recompute each delta."""
    by_dir = {c.get("dir"): c for c in doc.get("cases", []) if isinstance(c, dict)}
    for extra in batch.get("cases", []):
        target = by_dir.get(extra.get("dir")) if isinstance(extra, dict) else None
        if target is None:
            continue
        for arm in ("with", "without"):
            target["arms"].setdefault(arm, []).extend((extra.get("arms") or {}).get(arm, []))
        with_scores = numbers(target["arms"]["with"])
        without_scores = numbers(target["arms"].get("without", []))
        aggregates = target.setdefault("aggregates", {})
        if with_scores:
            aggregates["score"] = round(sum(with_scores) / len(with_scores), 9)
        if without_scores:
            aggregates["scoreWithout"] = round(sum(without_scores) / len(without_scores), 9)
        if with_scores and without_scores:
            aggregates["delta"] = round(
                sum(with_scores) / len(with_scores) - sum(without_scores) / len(without_scores), 9
            )
    doc["costUsd"] = float(doc.get("costUsd") or 0) + float(batch.get("costUsd") or 0)
    if batch.get("partial") or error:
        doc["partial"] = True


def claude_looks(doc: Json, max_runs: int) -> dict[str, Json]:
    """The latest look for each behaviour case that is close, has no run error and has room for a batch."""
    pending: dict[str, Json] = {}
    for case in doc.get("cases", []):
        key = case_key(case) if isinstance(case, dict) else None
        arms = (case or {}).get("arms") or {}
        if not key or not key.startswith("behaviour/") or "without" not in arms:
            continue
        if any(r.get("error") is not None for arm in ("with", "without") for r in arms[arm]):
            continue
        look = assess(numbers(arms["with"]), numbers(arms["without"]), "claude-isolated", key)
        if look and look["outcome"] == "close" and look["runs"] < max_runs:
            pending[key] = look
    return pending


def extend_claude(
    wrapper: Path, results: Path, doc: Json, opts: argparse.Namespace, manifest: Json, save: Callable[[], None]
) -> None:
    """Run extra batches for each close behaviour case, one case at a time, until each stops or the budget ends."""
    all_keys = [k for k in (case_key(c) for c in doc.get("cases", []) if isinstance(c, dict)) if k]
    batch_number = 1
    refused: set[str] = set()
    while True:
        pending = sorted(k for k in claude_looks(doc, opts.max_runs) if k not in refused)
        if not pending:
            return
        key = pending[0]
        folder = key.split("/")[-1]
        matches = [k for k in all_keys if fnmatch.fnmatch(k.split("/")[-1], folder)]
        if len(matches) > 1:
            manifest["warnings"].append(
                f"claude-isolated {key}: --case {folder} matches {len(matches)} cases, so the case was not extended"
            )
            refused.add(key)
            continue
        remaining = opts.max_cost_usd - claude_run_cost(doc)
        if remaining <= 0:
            manifest["warnings"].append(
                "claude-isolated: the --max-cost-usd budget is spent, so close cases were not extended"
            )
            return
        batch_number += 1
        stem = f"claude-isolated.batch-{batch_number}"
        log(f"claude-isolated: extra batch for {key} ({opts.runs} run(s) per arm)")
        batch, error = claude_eval(
            wrapper,
            results,
            "claude-isolated",
            opts,
            ablation_none=False,
            case=folder,
            runs=opts.runs,
            max_cost=remaining,
            stem=stem,
        )
        if error:
            manifest["armErrors"]["claude-isolated"] = f"{stem}: {error}"
        if batch is None:
            doc["partial"] = True
            write_json(results / "claude-isolated.json", doc)
            save()
            return
        merge_claude_batch(doc, batch, error)
        write_json(results / "claude-isolated.json", doc)
        save()
        if error:
            return


def cmd_run(opts: argparse.Namespace) -> int:
    check_max_runs(opts)
    skill_dir = Path(opts.skill_dir).resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise SetupError(f"{skill_dir} has no SKILL.md")
    name = skill_dir.name
    harnesses = load_config(skill_dir)
    case_keys = discover_cases(skill_dir, opts.case)
    if "codex" in harnesses:
        conflict = codex_skills_config_conflict()
        if conflict:
            raise SetupError(
                f"{conflict} already sets skills.config ([[skills.config]]). The Codex arm replaces the whole "
                "skills.config array with -c, so remove that setting before you run the eval."
            )
    versions = {"claude": tool_version("claude"), "codex": tool_version("codex") if "codex" in harnesses else "skipped"}
    repo_top = git_output(skill_dir, "rev-parse", "--show-toplevel")
    repo = Path(repo_top).resolve() if repo_top else None
    results = new_results_dir(state_root(opts.state_dir), name)
    manifest: Json = {
        "skill": name,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "runs": opts.runs,
        "maxRuns": opts.max_runs,
        "harnesses": harnesses,
        "models": {"claude": opts.model, "codex": opts.codex_model, "judge": opts.judge_model},
        "versions": versions,
        "gitSha": git_output(skill_dir, "rev-parse", "HEAD") if repo else None,
        "cases": case_keys,
        "arms": [],
        "armErrors": {},
        # Per-run errors. The gate reads them from the arm files, so they are not arm errors.
        "runErrors": [],
        "warnings": [],
        "previousRef": opts.previous_ref,
    }

    def save() -> None:
        write_json(results / "manifest.json", manifest)

    save()
    temp = Path(tempfile.mkdtemp(prefix="eval-skill-"))
    try:
        plugin = wrapper_plugin_name(name)
        manifest["wrapperPlugin"] = plugin
        wrapper = build_wrapper(temp / "current", name, plugin, skill_dir, skill_dir / "evals")
        manifest["arms"].append("claude-isolated")
        log(f"claude-isolated: running {len(case_keys)} case(s), {opts.runs} run(s) each")
        doc, error = claude_eval(wrapper, results, "claude-isolated", opts, ablation_none=False)
        if error:
            manifest["armErrors"]["claude-isolated"] = error
        save()
        if doc is not None and not error:
            extend_claude(wrapper, results, doc, opts, manifest, save)
        cases = [c for c in (doc or {}).get("cases", []) if isinstance(c, dict)]

        if doc is not None and any((case_key(c) or "/").split("/")[0] in {"trigger", "near-miss"} for c in cases):
            manifest["arms"].append("claude-real-env")
            log("claude-real-env: running trigger and near-miss cases")
            real = real_env_arm(wrapper, results, cases, opts, name)
            write_json(results / "claude-real-env.json", real)
            for key, entry in real["cases"].items():
                for record in entry["runs"]:
                    if record["error"]:
                        manifest["runErrors"].append(f"claude-real-env {key}: {record['error']}")
            save()

        if "codex" in harnesses and doc is not None:
            manifest["arms"].append("codex")
            log("codex: running with and without the skill")
            codex = codex_arm(wrapper, results, cases, opts, name)
            while True:
                more = {k for k, e in codex["cases"].items() if codex_needs_more(e, k, opts.max_runs)}
                if not more:
                    break
                log(f"codex: extra batch for {', '.join(sorted(more))}")
                codex = codex_arm(wrapper, results, cases, opts, name, doc=codex, only=more, count=opts.runs)
            write_json(results / "codex.json", codex)
            for key, case_doc in codex["cases"].items():
                for arm in ("with", "without"):
                    for record in case_doc.get(arm, []):
                        if record["error"]:
                            manifest["runErrors"].append(f"codex {key} {arm}: {record['error']}")
            save()
        elif "codex" in harnesses:
            manifest["armErrors"]["codex"] = "skipped: claude-isolated produced no results to take the cases from"
            save()

        if repo is not None and opts.previous_ref:
            rel = os.path.relpath(skill_dir, repo).replace(os.sep, "/")
            previous_root = temp / "previous-src"
            previous_root.mkdir()
            try:
                present = export_previous_skill(repo, opts.previous_ref, rel, previous_root)
            except SetupError as problem:
                manifest["warnings"].append(f"previous version skipped: {problem}")
                present = False
            else:
                if not present:
                    manifest["warnings"].append(f"previous version skipped: {opts.previous_ref} has no {rel}/SKILL.md")
            if present:
                manifest["arms"].append(PREVIOUS_ARM)
                old_wrapper = build_wrapper(
                    temp / "previous", name, wrapper_plugin_name(name), previous_root / rel, skill_dir / "evals"
                )
                log(f"{PREVIOUS_ARM}: running the skill as of {opts.previous_ref}")
                _, previous_error = claude_eval(old_wrapper, results, PREVIOUS_ARM, opts, ablation_none=True)
                if previous_error:
                    manifest["armErrors"][PREVIOUS_ARM] = previous_error
                    manifest["warnings"].append(f"{PREVIOUS_ARM}: {previous_error}")
            save()
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        save()

    blocking = {arm: err for arm, err in manifest["armErrors"].items() if arm != PREVIOUS_ARM}
    for arm, err in blocking.items():
        log(f"ERROR {arm}: {err}")
    for err in manifest["runErrors"]:
        log(f"ERROR run {err}")
    print(results)
    return 1 if blocking or manifest["runErrors"] else 0


# --- gate ------------------------------------------------------------------------------------------------------------


@dataclass
class Failure:
    harness: str
    case: str | None
    grader: str | None
    text: str

    def line(self) -> str:
        where = " ".join(part for part in (self.harness, self.case) if part)
        subject = f"{where} {self.grader}" if self.grader else where
        return f"FAIL {subject}: {self.text}"


def has_truthy_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any((k == key and bool(v)) or has_truthy_key(v, key) for k, v in value.items())
    if isinstance(value, list):
        return any(has_truthy_key(v, key) for v in value)
    return False


def is_skill_grader(spec: Json) -> bool:
    return spec.get("type") == "tool_used" and (spec.get("config") or {}).get("tool") == "Skill"


def check_runs(harness: str, case: str, which: str, runs: list[Json], expected: int, *, paid: bool) -> list[Failure]:
    """Run count, error, and skipped-judge checks for one arm of one case."""
    problems: list[Failure] = []
    if len(runs) != expected:
        problems.append(Failure(harness, case, None, f"{which}-arm has {len(runs)} run(s), expected {expected}"))
    for index, run in enumerate(runs, start=1):
        if run["error"] is not None:
            problems.append(Failure(harness, case, None, f"{which}-arm run {index} errored: {str(run['error'])[:200]}"))
        if paid and run["skippedPaidGraders"]:
            problems.append(Failure(harness, case, None, f"{which}-arm run {index} skipped the paid (judge) graders"))
    return problems


def behaviour_runs(
    harness: str,
    key: str,
    with_runs: list[Json],
    without_runs: list[Json] | None,
    runs: int,
    max_runs: int,
    *,
    paid: bool,
) -> list[Failure]:
    """Run-count and run-error checks for a behaviour case. The count is whole batches, equal in both arms."""
    count = len(with_runs)
    valid = (without_runs is None or len(without_runs) == count) and runs <= count <= max_runs and count % runs == 0
    expected = count if valid else runs
    problems = check_runs(harness, key, "with", with_runs, expected, paid=paid)
    if without_runs is not None:
        problems += check_runs(harness, key, "without", without_runs, expected, paid=paid)
    return problems


def delta_failure(
    harness: str,
    key: str,
    stored_delta: Any,
    with_runs: list[Json],
    without_runs: list[Json],
    max_runs: int,
) -> list[Failure]:
    """The delta passes only on a bootstrap outcome of pass. The run scores decide, not the stored delta."""
    if any(run["error"] is not None for run in with_runs + without_runs):
        return []  # the run-error lines already fail the case
    look = assess(numbers(with_runs), numbers(without_runs), harness, key) if stored_delta is not None else None
    if look is None:
        return [Failure(harness, key, None, "delta missing, needs a gain with a positive lower bound")]
    if look["outcome"] == "pass":
        return []
    text = f"delta {fmt_interval(look)}"
    count = len(with_runs)
    if look["outcome"] == "no-gain":
        return [Failure(harness, key, None, f"{text}, no gain")]
    if count >= max_runs:
        return [Failure(harness, key, None, f"{text} still uncertain after {count} runs")]
    return [Failure(harness, key, None, f"{text} uncertain after {count} runs, needs more runs (max {max_runs})")]


def gate_claude_case(case: Json, key: str, expected_runs: int, max_runs: int) -> list[Failure]:
    arm = "claude-isolated"
    kind = key.split("/")[0]
    arms = case["arms"]
    with_runs = arms["with"]
    if kind == "behaviour":
        problems = behaviour_runs(arm, key, with_runs, arms.get("without"), expected_runs, max_runs, paid=True)
    else:
        problems = check_runs(arm, key, "with", with_runs, expected_runs, paid=True)
        if "without" in arms:
            problems += check_runs(arm, key, "without", arms["without"], expected_runs, paid=True)
    if "without" not in arms and kind == "behaviour":
        problems.append(Failure(arm, key, None, "no without-arm runs, so no delta"))
    if any(run["error"] is not None for run in with_runs):
        # The run-error lines above already fail the case. An errored run has no grader results to count.
        return problems
    for spec in case["graders"]:
        name = spec["name"]
        entries = [next(g for g in run["graders"] if g["name"] == name) for run in with_runs]
        skill = is_skill_grader(spec)
        if skill and kind == "explicit":
            continue  # a typed /<name> expands without a Skill tool call
        required = any(e["scored"] for e in entries) or (skill and kind in {"trigger", "near-miss"})
        if not required:
            continue
        passed = sum(1 for e in entries if e["passed"] is True)
        need = need_for(str(spec.get("type")), len(entries))
        if passed < need:
            problems.append(Failure(arm, key, name, f"passed {passed}/{len(entries)}, needs {need}/{len(entries)}"))
    if kind == "behaviour" and "without" in arms:
        problems += delta_failure(arm, key, case["aggregates"].get("delta"), with_runs, arms["without"], max_runs)
    return problems


def gate_codex_case(entry: Json, key: str, expected_runs: int, max_runs: int) -> list[Failure]:
    kind = key.split("/")[0]
    status = entry["status"]
    if status == "not-run" and kind not in CODEX_KINDS:
        return []
    if status == "ungradable" and kind in CODEX_KINDS:
        return [
            Failure(
                "codex",
                key,
                None,
                "no grader can grade this case on Codex. Add a grader that reads the final reply"
                " (regex or llm, target last_message), or opt out of Codex in evals/eval-skill.json",
            )
        ]
    if status != "scored":
        return [Failure("codex", key, None, f"unexpected Codex status {status!r} for a {kind} case")]
    with_runs = entry["with"]
    if kind == "behaviour":
        problems = behaviour_runs("codex", key, with_runs, entry["without"], expected_runs, max_runs, paid=False)
    else:
        problems = check_runs("codex", key, "with", with_runs, expected_runs, paid=False)
        if kind in CODEX_KINDS:
            problems += check_runs("codex", key, "without", entry["without"], expected_runs, paid=False)
    if any(run["error"] is not None for run in with_runs):
        # The run-error lines above already fail the case. An errored run has no grader results to count.
        return problems
    for name in sorted({g["name"] for run in with_runs for g in run["graders"]}):
        entries = [next(g for g in run["graders"] if g["name"] == name) for run in with_runs]
        first = entries[0]
        required = first["scored"] and first["applicable"]
        if not required:
            continue
        passed = sum(1 for e in entries if e["passed"] is True)
        need = need_for(str(first["type"]), len(entries))
        if passed < need:
            problems.append(Failure("codex", key, name, f"passed {passed}/{len(entries)}, needs {need}/{len(entries)}"))
    if kind == "behaviour":
        problems += delta_failure("codex", key, entry["delta"], with_runs, entry["without"], max_runs)
    return problems


def gate_real_env_case(entry: Json, key: str, expected_runs: int) -> list[Failure]:
    arm = "claude-real-env"
    runs = entry["runs"]
    problems: list[Failure] = []
    if len(runs) != expected_runs:
        problems.append(Failure(arm, key, None, f"has {len(runs)} run(s), expected {expected_runs}"))
    for index, run in enumerate(runs, start=1):
        if run["error"] is not None:
            problems.append(Failure(arm, key, None, f"run {index} errored: {str(run['error'])[:200]}"))
    fired = sum(1 for run in runs if run["fired"] is True)
    need = len(runs) if key.startswith("trigger/") else 0
    if fired != need:
        problems.append(Failure(arm, key, None, f"fired {fired}/{len(runs)}, needs {need}/{len(runs)}"))
    return problems


def evaluate(results: Path) -> list[Failure]:
    """Apply the pass rule to a results directory. Any doubt is a failure."""
    try:
        manifest = load_json(results / "manifest.json")
        expected_runs = int(manifest["runs"])
        max_runs = int(manifest.get("maxRuns", expected_runs))
        harnesses = list(manifest["harnesses"])
        keys = list(manifest["cases"])
        errors = dict(manifest.get("armErrors") or {})
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [Failure("manifest", None, None, f"manifest.json missing or unreadable ({error})")]
    failures = [
        Failure(arm, None, None, f"arm failed: {str(text)[:200]}")
        for arm, text in errors.items()
        if arm != PREVIOUS_ARM
    ]

    def load_arm(arm: str) -> Json | None:
        try:
            return load_json(results / f"{arm}.json")
        except (OSError, ValueError) as error:
            failures.append(Failure(arm, None, None, f"results file missing or unreadable ({error})"))
            return None

    claude = load_arm("claude-isolated")
    if claude is not None:
        if claude.get("partial") is not False:
            failures.append(Failure("claude-isolated", None, None, "partial result (the run did not finish)"))
        if has_truthy_key(claude, "aborted"):
            failures.append(Failure("claude-isolated", None, None, "an aborted entry is present"))
        listed = [c for c in claude.get("cases", []) if isinstance(c, dict)]
        by_key = {case_key(c): c for c in listed}
        for key in keys:
            case = by_key.get(key)
            if case is None:
                failures.append(Failure("claude-isolated", key, None, "case missing from the results"))
                continue
            try:
                failures += gate_claude_case(case, key, expected_runs, max_runs)
            except (KeyError, TypeError, StopIteration, ValueError) as error:
                failures.append(Failure("claude-isolated", key, None, f"malformed result, missing field {error}"))
        for directory in sorted(str(c.get("dir")) for c in listed):
            parts = directory.split("/")
            if len(parts) != 3 or parts[1] not in KINDS:
                failures.append(
                    Failure("claude-isolated", directory, None, "case is not under evals/<known kind>/<case>")
                )

    real_keys = [k for k in keys if k.split("/")[0] in {"trigger", "near-miss"}]
    if real_keys:
        real = load_arm("claude-real-env")
        if real is not None:
            for key in real_keys:
                try:
                    failures += gate_real_env_case(real["cases"][key], key, expected_runs)
                except (KeyError, TypeError) as error:
                    failures.append(Failure("claude-real-env", key, None, f"malformed or missing result {error}"))

    if "codex" in harnesses:
        codex = load_arm("codex")
        if codex is not None:
            for key in keys:
                try:
                    failures += gate_codex_case(codex["cases"][key], key, expected_runs, max_runs)
                except (KeyError, TypeError, StopIteration) as error:
                    failures.append(Failure("codex", key, None, f"malformed or missing result {error}"))
    return failures


def cmd_gate(opts: argparse.Namespace) -> int:
    results = Path(opts.results_dir)
    failures = evaluate(results)
    if failures:
        for failure in failures:
            print(failure.line())
        return 1
    print(f"PASS: {len(load_json(results / 'manifest.json')['cases'])} case(s) gated")
    return 0


# --- summary ---------------------------------------------------------------------------------------------------------


def fmt_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def fmt_delta(value: Any) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{value:+.2f}"


def safe_load(path: Path) -> Json | None:
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def numbers(items: list[Json], field: str = "score") -> list[float]:
    return [r[field] for r in items if isinstance(r.get(field), (int, float))]


def claude_total_cost(results: Path) -> float:
    total = 0.0
    for arm in ("claude-isolated", PREVIOUS_ARM):
        doc = safe_load(results / f"{arm}.json")
        if not doc:
            continue
        total += float(doc.get("costUsd") or 0)
        for case in doc.get("cases", []):
            for runs in (case.get("arms") or {}).values():
                total += sum(numbers(runs, "judgeCostUsd"))
    real = safe_load(results / "claude-real-env.json")
    if real:
        total += sum(numbers([r for c in real["cases"].values() for r in c["runs"]], "costUsd"))
    codex = safe_load(results / "codex.json")
    if codex:
        total += float(codex.get("judgeCostUsd") or 0)
    return total


def delta_cell(key: str, with_runs: list[Json], without_runs: list[Json], harness: str, stored: Any) -> str:
    """A behaviour delta shows its 95% interval and the run count. Other kinds show the plain delta."""
    if not key.startswith("behaviour/"):
        return fmt_delta(stored)
    look = assess(numbers(with_runs), numbers(without_runs), harness, key)
    if look is None:
        return fmt_delta(stored)
    return f"{fmt_interval(look)} ({len(with_runs)} runs)".replace("delta ", "")


def codex_cells(harnesses: list[str], codex: Json | None, key: str) -> list[str]:
    if "codex" not in harnesses:
        return [f"skipped (harnesses: {', '.join(harnesses)})"] * 3
    entry = ((codex or {}).get("cases") or {}).get(key)
    if entry is None:
        return ["missing"] * 3
    if entry.get("status") == "not-run":
        return ["not run"] * 3
    if entry.get("status") == "ungradable":
        return ["ungradable"] * 3
    return [
        fmt_score(mean(numbers(entry["with"]))),
        fmt_score(mean(numbers(entry["without"]))),
        delta_cell(key, entry["with"], entry["without"], "codex", entry.get("delta")),
    ]


def cmd_summary(opts: argparse.Namespace) -> int:
    results = Path(opts.results_dir)
    manifest = safe_load(results / "manifest.json")
    if manifest is None:
        raise SetupError(f"{results}/manifest.json is missing or unreadable")
    failures = evaluate(results)
    harnesses = manifest.get("harnesses", [])
    claude = safe_load(results / "claude-isolated.json") or {}
    real = safe_load(results / "claude-real-env.json") or {}
    codex = safe_load(results / "codex.json")
    previous = safe_load(results / f"{PREVIOUS_ARM}.json")
    errors = manifest.get("armErrors") or {}
    by_key = {case_key(c): c for c in claude.get("cases", []) if isinstance(c, dict)}
    previous_by_key = {case_key(c): c for c in (previous or {}).get("cases", []) if isinstance(c, dict)}
    models = manifest.get("models", {})
    versions = manifest.get("versions", {})
    codex_tokens = (codex or {}).get("tokens", {})
    total_tokens = int(codex_tokens.get("input", 0)) + int(codex_tokens.get("output", 0))

    lines = [
        f"# Skill eval: {manifest.get('skill')}",
        "",
        f"- Date: {manifest.get('date')}",
        f"- Skill: {manifest.get('skill')}",
        f"- Agent models: {models.get('claude')} (Claude Code), {models.get('codex')} (Codex)",
        f"- Judge model: {models.get('judge')}",
        f"- Claude Code version: {versions.get('claude')}",
        f"- Codex version: {versions.get('codex')}",
        f"- Runs per arm: {manifest.get('runs')}",
        f"- Max runs per behaviour arm: {manifest.get('maxRuns', manifest.get('runs'))}",
        f"- Total Claude cost: ${claude_total_cost(results):.2f}",
        f"- Total Codex tokens: {total_tokens:,}",
        "",
        "| Case | Kind | Claude with | Claude without | Δ | Codex with | Codex without | Codex Δ"
        " | Real env fired | Previous | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    failing = {f.case for f in failures if f.case}
    for key in manifest.get("cases", []):
        kind, name = key.split("/", 1)
        case = by_key.get(key) or {}
        arms = case.get("arms") or {}
        real_cell = "n/a"
        if kind in {"trigger", "near-miss"}:
            runs = (real.get("cases") or {}).get(key, {}).get("runs")
            real_cell = "missing" if runs is None else f"{sum(1 for r in runs if r.get('fired'))}/{len(runs)}"
        if previous is None:
            previous_cell = "error" if PREVIOUS_ARM in errors else "n/a"
        elif key in previous_by_key:
            previous_cell = fmt_score(mean(numbers((previous_by_key[key].get("arms") or {}).get("with", []))))
        else:
            previous_cell = "n/a"
        cells = [
            name,
            kind,
            fmt_score(mean(numbers(arms.get("with", [])))),
            fmt_score(mean(numbers(arms.get("without", [])))),
            delta_cell(
                key,
                arms.get("with", []),
                arms.get("without", []),
                "claude-isolated",
                (case.get("aggregates") or {}).get("delta"),
            ),
            *codex_cells(harnesses, codex, key),
            real_cell,
            previous_cell,
            "FAIL" if key in failing else "PASS",
        ]
        lines.append("| " + " | ".join(cells) + " |")

    warnings = list(manifest.get("warnings") or [])
    if PREVIOUS_ARM in errors and not any(PREVIOUS_ARM in w for w in warnings):
        warnings.append(f"{PREVIOUS_ARM}: {errors[PREVIOUS_ARM]}")
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    lines += ["", "## Gate verdict", ""]
    if failures:
        lines.append(f"FAIL ({len(failures)} failure(s))")
        lines += ["", "```text"] + [f.line() for f in failures] + ["```"]
    else:
        lines.append("PASS")
    print("\n".join(lines))
    return 0


# --- command line ----------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run every arm and print the results directory")
    run.add_argument("skill_dir")
    run.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="runs per arm in each batch")
    run.add_argument(
        "--max-runs",
        type=int,
        default=DEFAULT_MAX_RUNS,
        help="most runs per behaviour arm after extra batches. Must be a multiple of --runs (default 9)",
    )
    run.add_argument("--case", default=None, help="only cases whose name matches this glob")
    run.add_argument("--max-cost-usd", type=float, default=10.0)
    run.add_argument("--concurrency", type=int, default=4, help="parallel runs, 1 to 8 (default 4)")
    run.add_argument("--model", default="claude-opus-5-5")
    run.add_argument("--codex-model", default="gpt-6-sol")
    run.add_argument("--judge-model", default="claude-sonnet-5-5")
    run.add_argument("--previous-ref", default="origin/main")
    run.add_argument("--state-dir", default=None)
    run.set_defaults(handler=cmd_run)
    gate = sub.add_parser("gate", help="exit 0 when the results pass, 1 otherwise")
    gate.add_argument("results_dir")
    gate.set_defaults(handler=cmd_gate)
    summary = sub.add_parser("summary", help="print a Markdown summary for a PR body")
    summary.add_argument("results_dir")
    summary.set_defaults(handler=cmd_summary)
    return parser


def main(argv: list[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)
    if getattr(opts, "runs", 1) < 1:
        print("error: --runs must be at least 1", file=sys.stderr)
        return 1
    if getattr(opts, "concurrency", 1) not in range(1, 9):
        print("error: --concurrency must be from 1 to 8", file=sys.stderr)
        return 1
    try:
        return int(opts.handler(opts))
    except SetupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
