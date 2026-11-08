"""Write detector output to <data>/detect/ and to fraudnet.db (ARCHITECTURE.md section 4).

Files are byte-stable: UTF-8, LF line endings, sorted JSON keys and no timestamps, so the same input
and settings always give identical bytes.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from fraudnet.detect.pipeline import DetectorOutput

INDICATOR_CODE_LIST = ("'SHARED_BANK', 'SHARED_PHONE', 'SHARED_EMAIL', 'SHARED_ADDRESS', 'PROVIDER_SHARED_CONTACT', "
                       "'DUPLICATE_INVOICE', 'REPEATED_NARRATIVE', 'CLAIM_BURST', 'SHARED_INCIDENT', 'UNRECORDED_LINK', "
                       "'PROVIDER_CONCENTRATION', 'INFLATED_AMOUNT', 'ORPHAN_POLICY_REF', 'PAYMENT_OVER_APPROVED'")
DETECTOR_TABLES = {
    "detector_run": """CREATE TABLE detector_run (
    run_id TEXT PRIMARY KEY CHECK (run_id GLOB 'RUN-[0-9A-F]*'),
    input_manifest_sha256 TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    code_version TEXT NOT NULL,
    summary_json TEXT NOT NULL
) STRICT;""",
    "detected_edge": """CREATE TABLE detected_edge (
    run_id TEXT NOT NULL REFERENCES detector_run(run_id),
    link_id TEXT NOT NULL CHECK (link_id GLOB 'LNK-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    source_node_id TEXT NOT NULL REFERENCES graph_node(node_id),
    target_node_id TEXT NOT NULL REFERENCES graph_node(node_id),
    edge_type TEXT NOT NULL,
    family TEXT NOT NULL CHECK (family IN ('IDENTITY', 'BILLING', 'STORY', 'TIMING', 'INCIDENT', 'LOCATION')),
    matched_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    source_refs_json TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    in_recorded_edges INTEGER CHECK (in_recorded_edges IN (0, 1)),
    cap REAL NOT NULL,
    rarity REAL NOT NULL,
    explanation_code TEXT CHECK (explanation_code IN ('HOUSEHOLD', 'BUILDING', 'COMMON_EVENT', 'BUSY_PROVIDER')),
    explanation_factor REAL NOT NULL,
    strength REAL NOT NULL CHECK (strength BETWEEN 0 AND 1),
    PRIMARY KEY (run_id, link_id),
    UNIQUE (run_id, source_node_id, target_node_id, edge_type, matched_value),
    CHECK (source_node_id <> target_node_id)
) STRICT;""",
    "network": """CREATE TABLE network (
    network_id TEXT PRIMARY KEY CHECK (network_id GLOB 'NET-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    run_id TEXT NOT NULL REFERENCES detector_run(run_id),
    rank INTEGER NOT NULL UNIQUE CHECK (rank >= 1),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    priority TEXT NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    flagged INTEGER NOT NULL CHECK (flagged IN (0, 1)),
    member_count INTEGER NOT NULL CHECK (member_count >= 2),
    families TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (length(summary) > 0)
) STRICT;""",
    "network_member": """CREATE TABLE network_member (
    network_id TEXT NOT NULL REFERENCES network(network_id),
    node_id TEXT NOT NULL REFERENCES graph_node(node_id),
    member_role TEXT NOT NULL CHECK (member_role IN ('CLAIMANT', 'LINKED_PROVIDER', 'SHARED_PROVIDER', 'BILLING_PROVIDER', 'SHARED_INCIDENT')),
    member_score REAL NOT NULL CHECK (member_score BETWEEN 0 AND 1),
    PRIMARY KEY (network_id, node_id)
) STRICT;""",
    "fraud_indicator": f"""CREATE TABLE fraud_indicator (
    indicator_id TEXT PRIMARY KEY CHECK (indicator_id GLOB 'FIN-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    run_id TEXT NOT NULL REFERENCES detector_run(run_id),
    network_id TEXT REFERENCES network(network_id),
    subject_node_id TEXT REFERENCES graph_node(node_id),
    indicator_code TEXT NOT NULL CHECK (indicator_code IN ({INDICATOR_CODE_LIST})),
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    score_contribution REAL NOT NULL CHECK (score_contribution BETWEEN 0 AND 1),
    explanation TEXT NOT NULL CHECK (length(explanation) > 0),
    evidence_json TEXT NOT NULL CHECK (length(evidence_json) > 2)
) STRICT;""",
}
# Children first, so dropping never breaks a foreign key.
DROP_ORDER = ("fraud_indicator", "network_member", "network", "detected_edge", "detector_run")


def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _write_json(path: Path, body) -> None:
    _write_bytes(path, (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    _write_bytes(path, frame.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def write_files(output: DetectorOutput, folder: Path) -> list[str]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _write_json(folder / "detector_run.json", output.run)
    _write_csv(folder / "detected_edge.csv", output.detected_edge)
    _write_csv(folder / "network.csv", output.network)
    _write_csv(folder / "network_member.csv", output.network_member)
    _write_csv(folder / "fraud_indicator.csv", output.fraud_indicator)
    _write_json(folder / "cleared_groups.json", output.cleared_groups)
    _write_json(folder / "network_detail.json", output.network_detail)
    return sorted(path.name for path in folder.iterdir())


def _rows(frame: pd.DataFrame):
    """Plain Python values for sqlite3: NaN and NA become NULL."""
    for record in frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None):
        yield tuple(int(value) if hasattr(value, "item") and float(value).is_integer() and not isinstance(value, float)
                    else value.item() if hasattr(value, "item") else value for value in record)


def write_database(output: DetectorOutput, database: Path) -> None:
    """Replace the detector tables with this run. Input tables are never touched."""
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for table in DROP_ORDER:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        for ddl in DETECTOR_TABLES.values():
            connection.execute(ddl)
        run = output.run
        connection.execute("INSERT INTO detector_run VALUES (?, ?, ?, ?, ?)",
                           (run["run_id"], run["input_manifest_sha256"], run["config_sha256"], run["code_version"],
                            json.dumps(run, sort_keys=True)))
        for table, frame in (("detected_edge", output.detected_edge), ("network", output.network),
                             ("network_member", output.network_member), ("fraud_indicator", output.fraud_indicator)):
            connection.executemany(f"INSERT INTO {table} ({', '.join(frame.columns)}) VALUES "
                                   f"({', '.join('?' * len(frame.columns))})", _rows(frame))
