"""Classify review-gate findings with TypeSafe (Jev) for /matrix.

Each finding gets one of four classes:
  before-merge  fix it in this PR
  fix-forward   fix it in a follow-up PR in the same /neo chain
  not-a-defect  drop it
  decide        an answer is near the threshold, so the finding goes to the decision queue

Usage: triage.py <input.json>
Input:  {"work_order": "<text>", "findings": [{"id": "<id>", "text": "<finding>"}]}
Output: a JSON list on stdout, one {"id", "class", "answers"} object for each finding.
Exit 3 when TYPESAFE_API_KEY is not set or the API call fails. /matrix then uses LLM triage.
The questions and the rule match references/triage-rule.md, which LLM triage reads. A test keeps them in step.

The rule and the band come from the 2026-11-02 trial: 11 of 12 labelled findings matched.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
# An answer in [BAND_LOW, BAND_HIGH) is too close to call, so a person decides.
BAND_LOW = 0.4
BAND_HIGH = 0.6

RISK_QUESTIONS = {
    "weak_check": "Does this finding show that a check, test, or guard can pass or report success when it should fail?",
    "leak": "Does this finding show that a secret, key, token, or personal data can be exposed?",
    "data": "Does this finding show a change to stored data, a database, or a migration that is wrong?",
    "contract": "Does this finding show a break in an API or contract that other teams or services rely on?",
    "prod": "Does this finding show a problem in code that deploys straight to production?",
}
REAL_QUESTION = "Is this finding a real defect in the change, given the work order and the owner's decisions in it?"
CLASSES = ("before-merge", "fix-forward", "not-a-defect", "decide")

Post = Callable[[dict[str, Any]], dict[str, Any]]


class TriageError(Exception):
    """The input is invalid or TypeSafe gave no usable answer."""


def classify(answers: dict[str, float]) -> str:
    """Apply the triage rule to one finding's Noul answers."""
    real = answers["real"]
    if real < BAND_LOW:
        return "not-a-defect"
    if real < BAND_HIGH:
        return "decide"
    risks = [answers[key] for key in RISK_QUESTIONS]
    if max(risks) >= BAND_HIGH:
        return "before-merge"
    if max(risks) >= BAND_LOW:
        return "decide"
    return "fix-forward"


def request_body(work_order: str, finding: str) -> dict[str, Any]:
    questions = {key: {"type": "noul", "instructions": text} for key, text in RISK_QUESTIONS.items()}
    questions["real"] = {"type": "noul", "instructions": REAL_QUESTION}
    return {"model": MODEL, "state": f"Work order:\n{work_order}\n\nFinding:\n{finding}", "questions": questions}


def http_post(api_key: str) -> Post:
    def post(body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    return post


def parse_input(raw: Any) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(raw, dict) or set(raw) != {"work_order", "findings"}:
        raise TriageError("input must be an object with exactly 'work_order' and 'findings'")
    work_order, findings = raw["work_order"], raw["findings"]
    if not isinstance(work_order, str) or not work_order.strip():
        raise TriageError("work_order must be non-empty text")
    if not isinstance(findings, list) or not findings:
        raise TriageError("findings must be a non-empty list")
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"id", "text"}:
            raise TriageError("each finding must have exactly 'id' and 'text'")
        if not all(isinstance(finding[key], str) and finding[key].strip() for key in ("id", "text")):
            raise TriageError("finding id and text must be non-empty text")
    return work_order, findings


def answers_from(response: dict[str, Any]) -> dict[str, float]:
    try:
        raw = response["answers"]
        answers = {key: float(raw[key]["noul"]) for key in (*RISK_QUESTIONS, "real")}
    except (KeyError, TypeError, ValueError) as error:
        raise TriageError(f"TypeSafe response is missing an answer: {error}") from error
    if not all(0.0 <= value <= 1.0 for value in answers.values()):
        raise TriageError("TypeSafe returned an answer outside 0 to 1")
    return answers


def triage(raw: Any, post: Post) -> list[dict[str, Any]]:
    work_order, findings = parse_input(raw)
    results = []
    for finding in findings:
        answers = answers_from(post(request_body(work_order, finding["text"])))
        results.append({"id": finding["id"], "class": classify(answers), "answers": answers})
    return results


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        parse_input(raw)
    except (OSError, json.JSONDecodeError, TriageError) as error:
        print(f"triage: invalid input: {error}", file=sys.stderr)
        return 2
    api_key = os.environ.get("TYPESAFE_API_KEY", "")
    if not api_key:
        print("triage: TYPESAFE_API_KEY is not set. Use LLM triage.", file=sys.stderr)
        return 3
    try:
        results = triage(raw, http_post(api_key))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, TriageError) as error:
        # Never print the request headers: they hold the key.
        print(f"triage: TypeSafe call failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 3
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
