"""Tests for the /matrix TypeSafe triage adapter. No test calls the real API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import triage

LOW = dict.fromkeys(triage.RISK_QUESTIONS, 0.1)


def answers(real: float = 0.9, **risks: float) -> dict[str, float]:
    return {**LOW, **risks, "real": real}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Values from the 2026-11-02 trial.
        (answers(real=0.84, weak_check=0.96), "before-merge"),  # revision race
        (answers(real=0.83, leak=0.91), "before-merge"),  # foreign key in the summary
        (answers(real=0.82, contract=0.29), "fix-forward"),  # stale-key retry
        (answers(real=0.08), "not-a-defect"),  # owner decision reported as a bug
        (answers(real=0.83, weak_check=0.49), "decide"),  # Chromium missing: near the threshold
        (answers(real=0.54), "decide"),  # stale guide: unsure it is real
        # Band edges: the low edge is in the band, the high edge is out of it.
        (answers(real=0.4), "decide"),
        (answers(real=0.6), "fix-forward"),
        (answers(prod=0.6), "before-merge"),
        (answers(prod=0.4), "decide"),
    ],
)
def test_classify(given: dict[str, float], expected: str) -> None:
    assert triage.classify(given) == expected


def test_a_risk_never_rescues_a_finding_that_is_not_real() -> None:
    assert triage.classify(answers(real=0.1, leak=0.99)) == "not-a-defect"


def fake_post(result: dict[str, float], seen: list[dict[str, Any]]) -> triage.Post:
    def post(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body)
        return {"answers": {key: {"type": "noul", "noul": value} for key, value in result.items()}}

    return post


def test_triage_sends_the_work_order_with_each_finding() -> None:
    seen: list[dict[str, Any]] = []
    raw = {"work_order": "Owner decided: refuse two sites.", "findings": [{"id": "A", "text": "refusal is a bug"}]}

    results = triage.triage(raw, fake_post(answers(real=0.1), seen))

    assert results == [{"id": "A", "class": "not-a-defect", "answers": answers(real=0.1)}]
    assert "Owner decided: refuse two sites." in seen[0]["state"]
    assert "refusal is a bug" in seen[0]["state"]
    assert set(seen[0]["questions"]) == {*triage.RISK_QUESTIONS, "real"}


@pytest.mark.parametrize(
    "raw",
    [
        {"findings": [{"id": "A", "text": "x"}]},
        {"work_order": "", "findings": [{"id": "A", "text": "x"}]},
        {"work_order": "w", "findings": []},
        {"work_order": "w", "findings": [{"id": "A"}]},
        {"work_order": "w", "findings": [{"id": "A", "text": "x", "class": "fix-forward"}]},
        {"work_order": "w", "findings": [], "extra": 1},
    ],
)
def test_invalid_input_is_refused(raw: Any) -> None:
    with pytest.raises(triage.TriageError):
        triage.parse_input(raw)


def test_a_missing_answer_is_refused() -> None:
    def post(body: dict[str, Any]) -> dict[str, Any]:
        return {"answers": {"real": {"noul": 0.9}}}

    with pytest.raises(triage.TriageError):
        triage.triage({"work_order": "w", "findings": [{"id": "A", "text": "x"}]}, post)


def test_an_answer_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(triage.TriageError):
        triage.answers_from({"answers": {key: {"noul": 1.5} for key in (*triage.RISK_QUESTIONS, "real")}})


def test_main_exits_3_without_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = tmp_path / "in.json"
    path.write_text(json.dumps({"work_order": "w", "findings": [{"id": "A", "text": "x"}]}))

    assert triage.main(["triage.py", str(path)]) == 3


def test_main_exits_2_on_invalid_input(tmp_path: Path) -> None:
    path = tmp_path / "in.json"
    path.write_text("not json")

    assert triage.main(["triage.py", str(path)]) == 2


def test_every_class_is_in_the_closed_list() -> None:
    for real in (0.1, 0.5, 0.9):
        for risk in (0.1, 0.5, 0.9):
            assert triage.classify(answers(real=real, data=risk)) in triage.CLASSES


RULE = Path(__file__).resolve().parent.parent / "references" / "triage-rule.md"


def test_the_rule_file_asks_the_script_questions_word_for_word() -> None:
    rule = RULE.read_text(encoding="utf-8")

    for key, question in {**triage.RISK_QUESTIONS, "real": triage.REAL_QUESTION}.items():
        assert f"- `{key}`: {question}" in rule, f"LLM triage and TypeSafe triage must ask the same {key!r} question"


def test_the_rule_file_names_the_band_and_every_class() -> None:
    rule = RULE.read_text(encoding="utf-8")

    assert f"Below {triage.BAND_LOW} is no. From {triage.BAND_LOW} up to {triage.BAND_HIGH} is unsure." in rule
    for name in triage.CLASSES:
        assert f"`{name}`" in rule, f"the rule file should define the {name!r} class"
