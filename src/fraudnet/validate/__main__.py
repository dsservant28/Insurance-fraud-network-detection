"""Command line: python -m fraudnet.validate --data data/output [--reproducibility]

Validates <data>/input, writes <data>/reports/validation_summary.json and data_exception files, and
loads data_exception into <data>/fraudnet.db. Exit code 1 means a hard check failed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from fraudnet.inputs import load_input, manifest_sha256
from fraudnet.validate.checks import coverage_counts, run_checks
from fraudnet.validate.exceptions import COLUMNS, find_exceptions
from fraudnet.validate.reproducibility import check_reproducibility

EXCEPTION_DDL = """CREATE TABLE data_exception (
    exception_id TEXT PRIMARY KEY CHECK (exception_id GLOB 'EXC-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    exception_type TEXT NOT NULL CHECK (exception_type IN ('ORPHAN_POLICY_REF', 'PAYMENT_OVER_APPROVED', 'DUPLICATE_INVOICE')),
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    observed_value TEXT NOT NULL,
    expected_rule TEXT NOT NULL,
    detail_json TEXT NOT NULL
) STRICT;"""


def _write_json(path: Path, body) -> None:
    path.write_bytes((json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def validate(data_dir: Path) -> dict:
    """Run every check on <data_dir>/input and write the reports. Returns the summary."""
    data_dir = Path(data_dir)
    input_dir, reports = data_dir / "input", data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    tables, manifest = load_input(input_dir)

    results = run_checks(tables, input_dir, manifest)
    exceptions = find_exceptions(tables)
    summary = {
        "status": "PASS" if all(result.passed for result in results) else "FAIL",
        "input_manifest_sha256": manifest_sha256(input_dir),
        "row_counts": {name: len(table) for name, table in sorted(tables.items())},
        "checks": [result.as_dict() for result in results],
        "coverage": coverage_counts(tables) if all(r.check_id != "V-00" for r in results) else {},
        "exceptions": exceptions["exception_type"].value_counts().sort_index().to_dict(),
        "exception_note": "Exceptions are reported, not failures. Each one is explained in data_exception.",
    }
    _write_json(reports / "validation_summary.json", summary)
    exceptions.to_csv(reports / "data_exception.csv", index=False, lineterminator="\n")
    _write_json(reports / "data_exception.json", exceptions.to_dict("records"))

    database = data_dir / "fraudnet.db"
    if database.exists():
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE IF EXISTS data_exception")
            connection.execute(EXCEPTION_DDL)
            connection.executemany(f"INSERT INTO data_exception VALUES ({', '.join('?' * len(COLUMNS))})",
                                   exceptions[COLUMNS].itertuples(index=False, name=None))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated input data.")
    parser.add_argument("--data", type=Path, default=Path("data/output"))
    parser.add_argument("--reproducibility", action="store_true",
                        help="also regenerate twice with the recorded seed and scale and compare every file")
    args = parser.parse_args()

    summary = validate(args.data)
    for check in summary["checks"]:
        print(f"{check['id']} {check['status']:<4} {check['name']}" +
              (f"  ({check['failure_count']} problems, e.g. {check['examples'][0]})" if check["failure_count"] else ""))
    print(f"Exceptions found (reported, not failures): {summary['exceptions']}")
    status = summary["status"]

    if args.reproducibility:
        generator = json.loads((args.data / "input/input_manifest.json").read_text(encoding="utf-8"))["generator"]
        report = check_reproducibility(generator["seed"], generator["scale"], compare_with=args.data)
        _write_json(args.data / "reports/reproducibility_report.json", report)
        print(f"Reproducibility {report['status']}: {report['files_identical']}/{report['files_compared']} files "
              f"identical; seed {report['different_seed']} changed {report['csv_files_changed_by_different_seed']} CSV files")
        status = "PASS" if status == "PASS" and report["status"] == "PASS" else "FAIL"

    print(f"Validation {status}. Reports: {args.data / 'reports'}")
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
