"""Load the product catalog from CSV into a SKU -> price map."""

import csv
from pathlib import Path

DATA = Path(__file__).with_name("data.csv")


def load_catalog(path=DATA):
    catalog = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            sku = row["sku"].strip()
            if not sku.isupper():  # skip blank or malformed rows
                continue
            catalog[sku] = int(row["price_cents"])
    return catalog
