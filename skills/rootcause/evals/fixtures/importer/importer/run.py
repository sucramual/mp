"""Nightly user import: read users.csv and upsert each row."""

import csv
from datetime import datetime

from importer.store import upsert_user


def normalize_email(value):
    return value.strip().lower()


def import_users(path):
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            upsert_user(
                email=normalize_email(row["email"]),
                joined=datetime.strptime(row["joined"], "%Y-%m-%d").date(),
                plan=row["plan"],
            )
