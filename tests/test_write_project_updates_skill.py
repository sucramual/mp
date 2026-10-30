"""Black-box tests for skills/write-project-updates/scripts/style_memory.py.

Each test runs the real script as a subprocess, with DRIVE_MEETING_SUMMARIES_HOME pointing at a
temp directory, and reads the knowledge-map.json it writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import REPO_ROOT, IsolatedEnv

SCRIPT = REPO_ROOT / "skills" / "write-project-updates" / "scripts" / "style_memory.py"
CONCURRENT_WRITERS = 24


def memory_command(*args: str) -> list[str]:
    return [sys.executable, str(SCRIPT), *args]


def memory_env(isolated_env: IsolatedEnv, home: Path) -> dict[str, str]:
    return {**isolated_env.env, "DRIVE_MEETING_SUMMARIES_HOME": str(home)}


def make_home(isolated_env: IsolatedEnv, name: str) -> Path:
    """Create an empty data directory, like the bash test's ``mktemp -d``."""
    home = isolated_env.root / name
    home.mkdir()
    return home


def run_memory(isolated_env: IsolatedEnv, home: Path, *args: str) -> None:
    """Run the script and fail the test on a non-zero exit, like the bash test's ``set -e``."""
    result = subprocess.run(
        memory_command(*args), env=memory_env(isolated_env, home), text=True, capture_output=True, timeout=120
    )
    assert result.returncode == 0, f"style_memory.py {' '.join(args)} exited {result.returncode}:\n{result.stderr}"


def knowledge_map(home: Path) -> dict[str, Any]:
    return json.loads((home / "knowledge-map.json").read_text(encoding="utf-8"))


def add_evidence(
    isolated_env: IsolatedEnv, home: Path, evidence_id: str, source_ref: str, observed_at: str, observation: str
) -> None:
    run_memory(
        isolated_env,
        home,
        "add-evidence",
        "--id",
        evidence_id,
        "--source-kind",
        "approved-example",
        "--source-ref",
        source_ref,
        "--observed-at",
        observed_at,
        "--observation",
        observation,
    )


def upsert_preferred_tone(
    isolated_env: IsolatedEnv, home: Path, status: str, confidence: str, evidence_ids: str
) -> None:
    run_memory(
        isolated_env,
        home,
        "upsert-trait",
        "--id",
        "preferred-tone",
        "--category",
        "voice",
        "--statement",
        "Use the preferred tone.",
        "--status",
        status,
        "--confidence",
        confidence,
        "--evidence-ids",
        evidence_ids,
    )


def test_seed_has_no_evidence_and_undated_traits(isolated_env: IsolatedEnv) -> None:
    home = make_home(isolated_env, "memory")
    run_memory(isolated_env, home, "show")
    data = knowledge_map(home)

    assert len(data["evidence"]) == 0, "the generic seed must not set an evidence cursor"
    dated = [t for t in data["traits"] if t.get("first_seen") is not None or t.get("last_seen") is not None]
    assert len(dated) == 0, "bundled traits must remain undated"


def test_upsert_trait_keeps_earlier_evidence_without_duplicates(isolated_env: IsolatedEnv) -> None:
    home = make_home(isolated_env, "memory")
    run_memory(isolated_env, home, "show")
    add_evidence(isolated_env, home, "first-example", "local:first", "2026-01-01", "First approved example")
    upsert_preferred_tone(isolated_env, home, "candidate", "0.8", "first-example")
    add_evidence(isolated_env, home, "second-example", "local:second", "2026-01-02", "Second approved example")
    upsert_preferred_tone(isolated_env, home, "confirmed", "1", "second-example,second-example")

    actual_evidence = ",".join(
        evidence_id
        for trait in knowledge_map(home)["traits"]
        if trait["id"] == "preferred-tone"
        for evidence_id in trait["evidence_ids"]
    )
    assert actual_evidence == "first-example,second-example", (
        "updating a trait should preserve earlier evidence and remove duplicates"
    )


def test_concurrent_writers_keep_every_evidence_entry(isolated_env: IsolatedEnv) -> None:
    home = make_home(isolated_env, "concurrent")
    run_memory(isolated_env, home, "show")
    env = memory_env(isolated_env, home)
    writers = [
        subprocess.Popen(
            memory_command(
                "add-evidence",
                "--id",
                f"concurrent-{index}",
                "--source-kind",
                "approved-example",
                "--source-ref",
                f"local:concurrent-{index}",
                "--observed-at",
                "2026-01-03",
                "--observation",
                f"Concurrent approved example {index}",
            ),
            env=env,
            stdout=subprocess.DEVNULL,
        )
        for index in range(1, CONCURRENT_WRITERS + 1)
    ]
    # Writers inherit stderr, so pytest's captured output shows any error text.
    exit_codes = [writer.wait(timeout=120) for writer in writers]
    assert exit_codes == [0] * CONCURRENT_WRITERS, f"writer exit codes: {exit_codes}"

    assert len(knowledge_map(home)["evidence"]) == CONCURRENT_WRITERS, (
        "concurrent writers should not lose evidence entries"
    )
