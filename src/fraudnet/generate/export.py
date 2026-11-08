"""Write byte-stable CSV, JSON and SQL files, the manifests and the SQLite database."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import networkx
import numpy
import pandas as pd

from fraudnet.generate.schema import schema_sql
from fraudnet.generate.sql_export import load_database, seed_sql

PROVENANCE = ("All data is synthetic, produced by this repository's seeded generator from built-in fictional "
              "value lists. No external dataset or real personal data is used, so no licence or attribution applies.")


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _json_value(value):
    if pd.isna(value):
        return None
    return int(value) if not isinstance(value, str) else value


def table_json(table: pd.DataFrame) -> bytes:
    """One JSON array per table, one record per line, in the CSV's row and column order. Empty values are null."""
    lines = [json.dumps({column: _json_value(value) for column, value in zip(table.columns, row)},
                        separators=(",", ":"), ensure_ascii=True)
             for row in table.itertuples(index=False, name=None)]
    return ("[\n" + ",\n".join(lines) + "\n]\n").encode("utf-8")


def write_input(tables: dict[str, pd.DataFrame], output_dir: Path, generator: dict | None = None) -> dict:
    """Write tables to <output_dir>/input and <output_dir>/fraudnet.db, and return the input manifest.

    The manifest holds no timestamps, so the same seed and scale give identical bytes. `generator`
    records the seed and scale, which the validator needs for volume checks. The .db file is not
    listed: reproducibility is checked on the CSV, JSON and SQL files (see D-002).
    """
    output_dir = Path(output_dir)
    input_dir = output_dir / "input"
    for folder in ("csv", "json", "sql"):
        (input_dir / folder).mkdir(parents=True, exist_ok=True)

    files = []
    for name in sorted(tables):
        csv_bytes = tables[name].to_csv(index=False, lineterminator="\n").encode("utf-8")
        files.append({"path": f"csv/{name}.csv", "table": name, "rows": len(tables[name]),
                      "sha256": _write(input_dir / "csv" / f"{name}.csv", csv_bytes)})
        files.append({"path": f"json/{name}.json", "table": name, "rows": len(tables[name]),
                      "sha256": _write(input_dir / "json" / f"{name}.json", table_json(tables[name]))})

    schema, seed = schema_sql(), seed_sql(tables)
    files.append({"path": "sql/schema.sql", "sha256": _write(input_dir / "sql/schema.sql", schema.encode("utf-8"))})
    files.append({"path": "sql/seed.sql", "sha256": _write(input_dir / "sql/seed.sql", seed.encode("utf-8"))})

    manifest = {"files": files}
    if generator is not None:
        manifest["generator"] = generator
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (input_dir / "input_manifest.json").write_bytes(text.encode("utf-8"))

    load_database(schema, seed, tables, output_dir / "fraudnet.db")
    return manifest


def write_source_manifest(output_dir: Path, seed: int, scale: float, input_manifest: dict) -> None:
    """Record how the data was made: command, settings, software versions, files and provenance.

    Hidden label checksums stay in hidden/hidden_manifest.json, never here.
    """
    reports = Path(output_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    body = {
        "command": f"python -m fraudnet.generate --seed {seed} --scale {scale} --out <output_dir>",
        "seed": seed,
        "scale": scale,
        "software": {"python": platform.python_version(), "numpy": numpy.__version__,
                     "pandas": pd.__version__, "networkx": networkx.__version__},
        "row_counts": {item["table"]: item["rows"] for item in input_manifest["files"] if item["path"].startswith("csv/")},
        "input_files": input_manifest["files"],
        "provenance": PROVENANCE,
    }
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    (reports / "source_manifest.json").write_bytes(text.encode("utf-8"))
