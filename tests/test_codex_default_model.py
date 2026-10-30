"""The tracked Codex default model must be one that works with Marcus's ChatGPT-account Codex.

Protects: `codex` starting with the tracked default instead of failing with HTTP 400. A realistic bug:
the Codex app writes a newer model name into the tracked file (as in #107), and the merge then
pushes it to every machine. test_install_codex_config.py pins an exact value, so it passes for any
value that someone copies into both places. This test checks the value against evidence.
"""

from __future__ import annotations

import tomllib

from conftest import REPO_ROOT

CONFIG = REPO_ROOT / "config" / "codex" / "config.toml"

# Models confirmed to work with Marcus's ChatGPT-account Codex.
# 2026-10-23: `codex exec -m gpt-6-sol` returned OK in every eval run and in a direct check.
# 2026-10-23: `-m gpt-6.1-sol` failed with "model is not supported when using Codex with a ChatGPT account".
# Add a model here only after `codex exec -m <model>` succeeds.
SUPPORTED_MODELS = {"gpt-6-sol"}


def test_default_model_is_confirmed_to_work() -> None:
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert "model" in config, "the tracked config should set a default model"
    assert config["model"] in SUPPORTED_MODELS, (
        f"model {config['model']!r} is not confirmed to work with a ChatGPT-account Codex;"
        f" confirmed: {sorted(SUPPORTED_MODELS)}"
    )
