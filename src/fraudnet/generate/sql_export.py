"""Build SQL seed text and load schema and seed into a SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from fraudnet.generate.schema import TABLES


def _literal(value) -> str:
    if pd.isna(value):
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(int(value))


def seed_sql(tables: dict[str, pd.DataFrame]) -> str:
    """Return INSERT statements for every table, parents before children."""
    lines = ["-- Input data only. Synthetic data generated from a fixed seed.",
             "PRAGMA foreign_keys = ON;", "BEGIN TRANSACTION;"]
    for name in TABLES:
        table = tables[name]
        columns = ", ".join(table.columns)
        for row in table.itertuples(index=False, name=None):
            values = ", ".join(_literal(value) for value in row)
            lines.append(f"INSERT INTO {name} ({columns}) VALUES ({values});")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def load_database(schema: str, seed: str, tables: dict[str, pd.DataFrame], db_path: Path) -> None:
    """Create the database from scratch with foreign keys on, then confirm that everything loaded."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db_path.unlink(missing_ok=True)
    except PermissionError as error:
        raise PermissionError(f"{db_path} is in use. Close any program that has it open, then run again.") from error

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(schema)
        connection.executescript(seed)
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise ValueError(f"{len(broken)} foreign key problems in {db_path}, first: {broken[0]}")
        for name, table in tables.items():
            loaded = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if loaded != len(table):
                raise ValueError(f"{name}: expected {len(table)} rows, loaded {loaded}")
    finally:
        connection.close()
