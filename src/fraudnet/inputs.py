"""Load input tables from an input folder, using only the files its manifest lists.

The validator and the detector both load data through here. Nothing outside the input folder,
such as hidden labels, can be reached this way.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from fraudnet.generate.schema import TABLES

MANIFEST = "input_manifest.json"


def integer_columns() -> dict[str, list[str]]:
    """INTEGER columns per table, read from the schema so the CSV types match the database."""
    return {table: re.findall(r"^\s+(\w+) INTEGER", ddl, flags=re.MULTILINE) for table, ddl in TABLES.items()}


def read_manifest(input_dir: Path) -> dict:
    return json.loads((Path(input_dir) / MANIFEST).read_text(encoding="utf-8"))


def manifest_sha256(input_dir: Path) -> str:
    return hashlib.sha256((Path(input_dir) / MANIFEST).read_bytes()).hexdigest()


def read_csv_table(path: Path, table: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    for column in integer_columns()[table]:
        frame[column] = frame[column].astype("Int64")
    return frame


def load_input(input_dir: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    """Return {table: DataFrame} for every CSV listed in the manifest, and the manifest itself."""
    input_dir = Path(input_dir)
    manifest = read_manifest(input_dir)
    tables = {item["table"]: read_csv_table(input_dir / item["path"], item["table"])
              for item in manifest["files"] if "table" in item and item["path"].startswith("csv/")}
    return tables, manifest
