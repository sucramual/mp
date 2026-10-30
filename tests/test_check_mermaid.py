"""Black-box tests for skills/open-pr/scripts/check-mermaid.sh.

Each test writes a Markdown body to a temp dir, runs the real checker from a separate temp cwd,
and checks the exit code, the summary on stdout, and the per-block errors on stderr.
The first run installs the pinned Mermaid with `npm ci`, so the subprocess timeout is generous.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "skills" / "open-pr" / "scripts" / "check-mermaid.sh"

FLOWCHART = """```mermaid
---
config:
  flowchart:
    wrappingWidth: 400
---
flowchart LR
  A[check-mermaid.sh] --> B[check-mermaid.mjs]
  classDef new fill:#cfc,stroke:#393
  class A,B new
```"""

SEQUENCE = """~~~Mermaid
sequenceDiagram
  Agent->>Checker: body.md
  Checker-->>Agent: exit 0
~~~"""

BROKEN = """   ```mermaid
   flowchart LR
     A[a -->
   ```"""


def run_checker(arg: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run check-mermaid.sh with one argument from cwd. Never raises on a non-zero exit."""
    env = {**os.environ, "TMPDIR": str(cwd)}
    return subprocess.run(
        [str(SCRIPT), arg], cwd=cwd, env=env, input=stdin, text=True, capture_output=True, timeout=600
    )


def snapshot(*dirs: Path) -> set[Path]:
    return {path for directory in dirs for path in directory.rglob("*")}


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """A docs dir that holds the Markdown file and an empty cwd for the run."""
    docs = tmp_path.resolve() / "docs"
    cwd = tmp_path.resolve() / "cwd"
    docs.mkdir()
    cwd.mkdir()
    return docs, cwd


def test_valid_blocks_pass_and_leave_no_files(dirs: tuple[Path, Path]) -> None:
    # Protects: valid GitHub-style diagrams (front matter, classDef, a tilde fence) pass.
    # Bug caught: a checker that loads mermaid without a DOM fails classDef with "DOMPurify.addHook".
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text(f"## Description\n\nIntro.\n\n{FLOWCHART}\n\nMore text.\n\n{SEQUENCE}\n")
    before = snapshot(docs, cwd)

    result = run_checker(str(body), cwd)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mermaid 12.1.0: 2 blocks parsed\n"
    assert snapshot(docs, cwd) == before, "the check should leave no files behind"


def test_broken_block_is_reported_with_its_line(dirs: tuple[Path, Path]) -> None:
    # Protects: a broken diagram fails the check and names the block and its opening-fence line.
    # Bug caught: a checker that stops at the first block, or that reports a pass for a parse error.
    docs, cwd = dirs
    body = docs / "body.md"
    # Line 1 heading, 2 blank, 3-13 flowchart, 14 blank, 15 "- item:", 16 broken fence (indented in a list).
    body.write_text(f"## Description\n\n{FLOWCHART}\n\n- item:\n{BROKEN}\n")
    before = snapshot(docs, cwd)

    result = run_checker(str(body), cwd)

    assert result.returncode == 1, result.stdout + result.stderr
    error_lines = [line for line in result.stderr.splitlines() if line.startswith("block ")]
    assert any(line.startswith("block 2 (line 16): ") for line in error_lines), result.stderr
    assert "Parse error" in result.stderr, result.stderr
    assert not any(line.startswith("block 1 ") for line in error_lines), result.stderr
    assert result.stdout == ""
    assert snapshot(docs, cwd) == before, "the check should leave no files behind"


def test_body_without_mermaid_passes(dirs: tuple[Path, Path]) -> None:
    # Protects: other fences, and a mermaid fence line inside them, are not parsed as diagrams.
    # Bug caught: a scanner that treats "```mermaid" inside a ```python fence as a block start.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text("## Description\n\n````python\nprint('hi')\n```mermaid\nnot a diagram\n```\n````\n")

    result = run_checker(str(body), cwd)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mermaid 12.1.0: no mermaid blocks\n"


def test_indented_code_example_is_not_a_diagram(dirs: tuple[Path, Path]) -> None:
    # Protects: a top-level code example indented four spaces is code, as GitHub renders it, even
    # when its text holds a broken ```mermaid fence. GFM allows at most three spaces before a fence.
    # Bug caught: a fence finder that accepts any indent and fails publication on example text.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text("## Description\n\nExample:\n\n    ```mermaid\n    flowchart LR\n      A[a -->\n    ```\n")

    result = run_checker(str(body), cwd)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mermaid 12.1.0: no mermaid blocks\n"


def test_fence_in_blockquote_is_checked_with_its_line(dirs: tuple[Path, Path]) -> None:
    # Protects: GitHub renders a mermaid fence inside a blockquote, so the check parses it and
    # reports the source line of its opening fence.
    # Bug caught: a finder that only walks top-level blocks, or counts lines inside the quote only.
    docs, cwd = dirs
    body = docs / "body.md"
    # Line 1 heading, 2 blank, 3 quote text, 4 quote blank, 5 opening fence.
    body.write_text("## Description\n\n> Note:\n>\n> ```mermaid\n> flowchart LR\n>   A[a -->\n> ```\n")

    result = run_checker(str(body), cwd)

    assert result.returncode == 1, result.stdout + result.stderr
    assert any(line.startswith("block 1 (line 5): ") for line in result.stderr.splitlines()), result.stderr
    assert result.stdout == ""


def copy_checker(dest: Path) -> Path:
    """Copy the wrapper and the package files, without node_modules, into dest. Return the wrapper."""
    package = SCRIPT.parent / "check-mermaid"
    (dest / "check-mermaid").mkdir(parents=True)
    shutil.copy2(SCRIPT, dest / SCRIPT.name)
    for name in ("check-mermaid.mjs", "package.json", "package-lock.json"):
        shutil.copy2(package / name, dest / "check-mermaid" / name)
    return dest / SCRIPT.name


def test_unsupported_node_is_a_setup_error(tmp_path: Path, dirs: tuple[Path, Path]) -> None:
    # Protects: a node outside the package "engines" range stops with setup error 2 and a fix,
    # before npm ci or the checker runs.
    # Bug caught: a wrapper that only checks that node exists; npm ci treats engines as advisory, so
    # the checker later fails on Node 20 with an uncaught exit 1.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text(f"{SEQUENCE}\n")
    real_node = shutil.which("node")
    assert real_node is not None
    shim = tmp_path / "shim"
    shim.mkdir()
    # The shim reports Node 20 and runs the real node for every other call.
    (shim / "node").write_text(
        f'#!/usr/bin/env bash\n[ "$*" = "--version" ] && {{ echo v20.11.0; exit 0; }}\nexec "{real_node}" "$@"\n'
    )
    (shim / "node").chmod(0o755)
    wrapper = copy_checker(tmp_path / "pkg")
    env = {**os.environ, "TMPDIR": str(cwd), "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run([str(wrapper), str(body)], cwd=cwd, env=env, text=True, capture_output=True, timeout=600)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "node 20.11.0" in result.stderr.lower(), result.stderr
    assert "^22.22.2 || ^24.15.0 || >=26" in result.stderr, result.stderr
    assert "installing" not in result.stderr, "npm ci ran after the refusal"
    assert not (tmp_path / "pkg" / "check-mermaid" / "node_modules").exists(), "npm ci ran after the refusal"
    assert result.stdout == "", "the checker ran after the refusal"


def test_stale_dependency_triggers_reinstall(tmp_path: Path, dirs: tuple[Path, Path]) -> None:
    # Protects: when any pinned direct dependency is missing or at another version, the wrapper
    # reinstalls before it runs the checker.
    # Bug caught: a wrapper that compares only mermaid, skips npm ci, and then fails on
    # `import("jsdom")` with an uncaught exit 1.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text(f"{SEQUENCE}\n")
    wrapper = copy_checker(tmp_path / "pkg")
    modules = tmp_path / "pkg" / "check-mermaid" / "node_modules"
    pins = json.loads((tmp_path / "pkg" / "check-mermaid" / "package.json").read_text())["dependencies"]
    # Every pinned package is present at its pin except jsdom, which an interrupted install lost.
    for name, version in pins.items():
        if name == "jsdom":
            continue
        (modules / name).mkdir(parents=True)
        (modules / name / "package.json").write_text(json.dumps({"name": name, "version": version}))
    env = {**os.environ, "TMPDIR": str(cwd)}

    result = subprocess.run([str(wrapper), str(body)], cwd=cwd, env=env, text=True, capture_output=True, timeout=600)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "installing the pinned" in result.stderr, result.stderr
    assert result.stdout == "mermaid 12.1.0: 1 block parsed\n"
    assert json.loads((modules / "jsdom" / "package.json").read_text())["version"] == pins["jsdom"]


def write_direct_packages(package_dir: Path) -> Path:
    """Write stub packages at the pinned version for every direct dependency, and nothing else.

    This is the tree that `npm ci` leaves while it still extracts the transitive packages.
    """
    modules = package_dir / "node_modules"
    pins = json.loads((package_dir / "package.json").read_text())["dependencies"]
    for name, version in pins.items():
        (modules / name).mkdir(parents=True)
        (modules / name / "package.json").write_text(json.dumps({"name": name, "version": version}))
    return modules


def test_partial_install_is_repaired_not_used(tmp_path: Path, dirs: tuple[Path, Path]) -> None:
    # Protects: a node_modules tree that lacks the completion marker is not trusted, even when
    # every direct dependency is present at its pinned version. The wrapper reinstalls it.
    # Bug caught: a wrapper that checks only the direct packages runs Node on a half-extracted
    # tree and fails with ERR_UNSUPPORTED_DIR_IMPORT (es-toolkit/compat), as on 2026-10-23.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text(f"{SEQUENCE}\n")
    wrapper = copy_checker(tmp_path / "pkg")
    modules = write_direct_packages(tmp_path / "pkg" / "check-mermaid")
    env = {**os.environ, "TMPDIR": str(cwd)}

    result = subprocess.run([str(wrapper), str(body)], cwd=cwd, env=env, text=True, capture_output=True, timeout=600)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "installing the pinned" in result.stderr, result.stderr
    assert result.stdout == "mermaid 12.1.0: 1 block parsed\n"
    assert (modules / "es-toolkit" / "package.json").is_file(), "the transitive packages should be installed"


def test_reader_waits_while_another_install_runs(tmp_path: Path, dirs: tuple[Path, Path]) -> None:
    # Protects: while another run holds the install lock, a run that sees the direct packages
    # waits for the lock and does not start Node on the tree.
    # Bug caught: a reader that skips the lock because the direct packages match runs on a partial
    # tree and exits at once with an import error.
    docs, cwd = dirs
    body = docs / "body.md"
    body.write_text(f"{SEQUENCE}\n")
    wrapper = copy_checker(tmp_path / "pkg")
    package_dir = tmp_path / "pkg" / "check-mermaid"
    write_direct_packages(package_dir)
    lock = package_dir / ".install.lock"
    lock.mkdir()  # another run is installing
    env = {**os.environ, "TMPDIR": str(cwd)}

    process = subprocess.Popen(
        [str(wrapper), str(body)], cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=3)  # still waiting for the lock
        lock.rmdir()  # the other install ended without a marker, so this run must repair the tree
        stdout, stderr = process.communicate(timeout=600)
    finally:
        process.kill()
        process.communicate()

    assert process.returncode == 0, stdout + stderr
    assert "installing the pinned" in stderr, stderr
    assert stdout == "mermaid 12.1.0: 1 block parsed\n"


def test_reads_stdin(dirs: tuple[Path, Path]) -> None:
    # Protects: `-` reads the body from stdin, so an agent can pipe `gh pr view` output in.
    _, cwd = dirs

    result = run_checker("-", cwd, stdin=f"Intro.\n\n{SEQUENCE}\n")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mermaid 12.1.0: 1 block parsed\n"


def test_missing_argument_is_a_usage_error(dirs: tuple[Path, Path]) -> None:
    _, cwd = dirs

    result = subprocess.run([str(SCRIPT)], cwd=cwd, text=True, capture_output=True, timeout=600)

    assert result.returncode == 2
    assert "usage:" in result.stderr.lower()
    assert result.stdout == ""
