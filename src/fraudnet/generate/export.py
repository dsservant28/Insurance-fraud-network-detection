"""Write byte-stable CSV and SQL files, the input manifest and the SQLite database."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from fraudnet.generate.schema import schema_sql
from fraudnet.generate.sql_export import load_database, seed_sql


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_input(tables: dict[str, pd.DataFrame], output_dir: Path) -> dict:
    """Write tables to <output_dir>/input and <output_dir>/fraudnet.db, and return the manifest.

    The manifest holds no timestamps, so the same seed and scale give identical bytes. The .db
    file is not listed: reproducibility is checked on the CSV and SQL files (see D-002).
    """
    output_dir = Path(output_dir)
    input_dir = output_dir / "input"
    csv_dir = input_dir / "csv"
    sql_dir = input_dir / "sql"
    csv_dir.mkdir(parents=True, exist_ok=True)
    sql_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for name in sorted(tables):
        data = tables[name].to_csv(index=False, lineterminator="\n").encode("utf-8")
        files.append({
            "path": f"csv/{name}.csv",
            "table": name,
            "rows": len(tables[name]),
            "sha256": _write(csv_dir / f"{name}.csv", data),
        })

    schema, seed = schema_sql(), seed_sql(tables)
    files.append({"path": "sql/schema.sql", "sha256": _write(sql_dir / "schema.sql", schema.encode("utf-8"))})
    files.append({"path": "sql/seed.sql", "sha256": _write(sql_dir / "seed.sql", seed.encode("utf-8"))})

    manifest = {"files": files}
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (input_dir / "input_manifest.json").write_bytes(text.encode("utf-8"))

    load_database(schema, seed, tables, output_dir / "fraudnet.db")
    return manifest
