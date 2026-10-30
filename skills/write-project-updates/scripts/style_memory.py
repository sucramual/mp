#!/usr/bin/env python3
"""Maintain the private, local style knowledge map for the skill."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Keep the existing storage name so the skill rename preserves private writing history.
STYLE_DATA_NAMESPACE = "drive-meeting-summaries"
SCHEMA_VERSION = 1
VALID_CATEGORIES = {
    "voice",
    "structure",
    "initiative",
    "audience",
    "avoid",
    "structural-inspiration",
}
VALID_STATUSES = {"candidate", "confirmed", "rejected", "superseded"}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def data_dir() -> Path:
    override = os.environ.get("DRIVE_MEETING_SUMMARIES_HOME")
    if override:
        return Path(override).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / STYLE_DATA_NAMESPACE
    return Path.home() / ".local" / "share" / STYLE_DATA_NAMESPACE


def map_path() -> Path:
    return data_dir() / "knowledge-map.json"


@contextmanager
def map_lock() -> Iterator[None]:
    path = map_path().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def seed_profile() -> dict[str, Any]:
    created_at = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "updated_at": created_at,
        "traits": [
            {
                "id": "lead-with-result",
                "category": "voice",
                "statement": "Lead with the result, current state, or reason for the update.",
                "status": "candidate",
                "confidence": 0.8,
                "evidence_ids": [],
                "first_seen": None,
                "last_seen": None,
            },
            {
                "id": "calibrate-certainty",
                "category": "voice",
                "statement": "Separate observations, concerns, and questions instead of claiming false agreement.",
                "status": "candidate",
                "confidence": 0.8,
                "evidence_ids": [],
                "first_seen": None,
                "last_seen": None,
            },
            {
                "id": "close-the-loop",
                "category": "initiative",
                "statement": "End with the owner, smallest useful next cut, concrete ask, or follow-up point.",
                "status": "candidate",
                "confidence": 0.75,
                "evidence_ids": [],
                "first_seen": None,
                "last_seen": None,
            },
            {
                "id": "reference-labelled-sections",
                "category": "structural-inspiration",
                "statement": (
                    "Use a short context block and labelled takeaway, gap, and next-step sections"
                    " when the content warrants them."
                ),
                "status": "candidate",
                "confidence": 0.8,
                "evidence_ids": [],
                "first_seen": None,
                "last_seen": None,
            },
        ],
        "evidence": [],
        "evaluations": [],
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_map() -> dict[str, Any]:
    path = map_path()
    if not path.exists():
        atomic_write(path, seed_profile())
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported schema version in {path}: {value.get('schema_version')}")
    return value


def validate_id(value: str) -> None:
    if not ID_PATTERN.fullmatch(value):
        raise SystemExit("IDs must be 2-64 characters using lowercase letters, digits, and hyphens.")


def bounded_text(value: str, field: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise SystemExit(f"{field} must contain 1-{limit} characters.")
    return normalized


def command_show(args: argparse.Namespace) -> None:
    with map_lock():
        value = load_map()
        if args.compact:
            value = {
                "path": str(map_path()),
                "updated_at": value["updated_at"],
                "traits": value["traits"],
                "recent_evaluations": value["evaluations"][-5:],
            }
    print(json.dumps(value, indent=2, ensure_ascii=False))


def command_add_evidence(args: argparse.Namespace) -> None:
    validate_id(args.id)
    with map_lock():
        value = load_map()
        if any(item["id"] == args.id for item in value["evidence"]):
            raise SystemExit(f"Evidence already exists: {args.id}")
        value["evidence"].append(
            {
                "id": args.id,
                "source_kind": bounded_text(args.source_kind, "source-kind", 100),
                "source_ref": bounded_text(args.source_ref, "source-ref", 500),
                "observed_at": args.observed_at,
                "observation": bounded_text(args.observation, "observation"),
            }
        )
        value["updated_at"] = utc_now()
        atomic_write(map_path(), value)
    print(map_path())


def command_upsert_trait(args: argparse.Namespace) -> None:
    validate_id(args.id)
    if args.category not in VALID_CATEGORIES:
        raise SystemExit(f"Invalid category: {args.category}")
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status: {args.status}")
    if not 0 <= args.confidence <= 1:
        raise SystemExit("confidence must be between 0 and 1")
    requested_evidence_ids = list(dict.fromkeys(item for item in args.evidence_ids.split(",") if item))
    with map_lock():
        value = load_map()
        existing = next((item for item in value["traits"] if item["id"] == args.id), None)
        existing_evidence_ids = existing["evidence_ids"] if existing else []
        evidence_ids = list(dict.fromkeys([*existing_evidence_ids, *requested_evidence_ids]))
        known_evidence = {item["id"] for item in value["evidence"]}
        missing = sorted(set(evidence_ids) - known_evidence)
        if missing:
            raise SystemExit(f"Unknown evidence IDs: {', '.join(missing)}")
        now_date = datetime.now(UTC).date().isoformat()
        first_seen = existing["first_seen"] if existing else None
        trait = {
            "id": args.id,
            "category": args.category,
            "statement": bounded_text(args.statement, "statement"),
            "status": args.status,
            "confidence": args.confidence,
            "evidence_ids": evidence_ids,
            "first_seen": first_seen or now_date,
            "last_seen": now_date,
        }
        if existing:
            value["traits"][value["traits"].index(existing)] = trait
        else:
            value["traits"].append(trait)
        value["updated_at"] = utc_now()
        atomic_write(map_path(), value)
    print(map_path())


def parse_scores(raw_scores: str) -> dict[str, int]:
    try:
        scores = json.loads(raw_scores)
    except json.JSONDecodeError as error:
        raise SystemExit(f"scores must be valid JSON: {error}") from error
    expected = {
        "source_faithfulness",
        "decisions_and_actions",
        "project_initiative",
        "user_voice",
        "information_structure",
        "concision_and_audience_fit",
    }
    if set(scores) != expected:
        raise SystemExit("scores must contain exactly the six rubric dimensions")
    if any(not isinstance(score, int) or not 0 <= score <= 5 for score in scores.values()):
        raise SystemExit("each rubric score must be an integer from 0 to 5")
    return scores


def command_record_evaluation(args: argparse.Namespace) -> None:
    validate_id(args.summary_id)
    scores = parse_scores(args.scores)
    if not 0 <= args.weighted_total <= 100:
        raise SystemExit("weighted-total must be between 0 and 100")
    with map_lock():
        value = load_map()
        value["evaluations"].append(
            {
                "summary_id": args.summary_id,
                "recorded_at": utc_now(),
                "scores": scores,
                "weighted_total": args.weighted_total,
                "verdict": args.verdict,
                "revision_count": args.revision_count,
                "user_outcome": args.user_outcome,
                "lesson": bounded_text(args.lesson, "lesson") if args.lesson else None,
            }
        )
        value["updated_at"] = utc_now()
        atomic_write(map_path(), value)
    print(map_path())


def command_set_outcome(args: argparse.Namespace) -> None:
    validate_id(args.summary_id)
    with map_lock():
        value = load_map()
        evaluation = next(
            (item for item in reversed(value["evaluations"]) if item["summary_id"] == args.summary_id),
            None,
        )
        if evaluation is None:
            raise SystemExit(f"No evaluation found for summary: {args.summary_id}")
        evaluation["user_outcome"] = args.user_outcome
        evaluation["lesson"] = bounded_text(args.lesson, "lesson") if args.lesson else None
        evaluation["outcome_recorded_at"] = utc_now()
        value["updated_at"] = utc_now()
        atomic_write(map_path(), value)
    print(map_path())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show the current map")
    show_parser.add_argument("--compact", action="store_true")
    show_parser.set_defaults(func=command_show)

    evidence_parser = subparsers.add_parser("add-evidence", help="Add a private-source pointer and derived observation")
    evidence_parser.add_argument("--id", required=True)
    evidence_parser.add_argument("--source-kind", required=True)
    evidence_parser.add_argument("--source-ref", required=True)
    evidence_parser.add_argument("--observed-at", required=True)
    evidence_parser.add_argument("--observation", required=True)
    evidence_parser.set_defaults(func=command_add_evidence)

    trait_parser = subparsers.add_parser("upsert-trait", help="Create or update a user-approved style trait")
    trait_parser.add_argument("--id", required=True)
    trait_parser.add_argument("--category", required=True)
    trait_parser.add_argument("--statement", required=True)
    trait_parser.add_argument("--status", required=True)
    trait_parser.add_argument("--confidence", required=True, type=float)
    trait_parser.add_argument("--evidence-ids", required=True)
    trait_parser.set_defaults(func=command_upsert_trait)

    evaluation_parser = subparsers.add_parser("record-evaluation", help="Append a rubric result")
    evaluation_parser.add_argument("--summary-id", required=True)
    evaluation_parser.add_argument("--scores", required=True)
    evaluation_parser.add_argument("--weighted-total", required=True, type=float)
    evaluation_parser.add_argument("--verdict", required=True, choices=["ready", "revise", "not-ready"])
    evaluation_parser.add_argument("--revision-count", type=int, default=0)
    evaluation_parser.add_argument(
        "--user-outcome",
        default="pending",
        choices=["pending", "approved", "edited", "rejected"],
    )
    evaluation_parser.add_argument("--lesson")
    evaluation_parser.set_defaults(func=command_record_evaluation)

    outcome_parser = subparsers.add_parser("set-outcome", help="Record the user's later approval, edit, or rejection")
    outcome_parser.add_argument("--summary-id", required=True)
    outcome_parser.add_argument(
        "--user-outcome",
        required=True,
        choices=["approved", "edited", "rejected"],
    )
    outcome_parser.add_argument("--lesson")
    outcome_parser.set_defaults(func=command_set_outcome)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
