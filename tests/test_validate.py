"""The validator (DATA_DICTIONARY.md section 11): clean data passes, and each rule catches a deliberate break."""
import json
import shutil
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from fraudnet.generate.__main__ import run as generate_into
from fraudnet.inputs import load_input
from fraudnet.validate import checks
from fraudnet.validate.__main__ import validate
from fraudnet.validate.reproducibility import check_reproducibility

SEED, SCALE = 20261022, 0.1


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    folder = tmp_path_factory.mktemp("dataset")
    generate_into(SEED, SCALE, folder)
    return folder


@pytest.fixture(scope="module")
def summary(dataset):
    return validate(dataset)


@pytest.fixture()
def tables(dataset):
    """A fresh copy of the input tables for each test, so a deliberate break affects only that test."""
    loaded, _ = load_input(dataset / "input")
    return {name: table.copy() for name, table in loaded.items()}


def _first_row(table, column, value):
    table.loc[table.index[0], column] = value


# ---- clean data

def test_clean_data_passes_every_check(summary):
    assert summary["status"] == "PASS"
    assert [check["id"] for check in summary["checks"]] == [f"V-{n:02d}" for n in range(1, 13)]
    assert all(check["status"] == "PASS" for check in summary["checks"]), summary["checks"]


def test_exceptions_are_reported_not_failed(summary, dataset):
    assert summary["exceptions"] == {"DUPLICATE_INVOICE": 2, "ORPHAN_POLICY_REF": 1, "PAYMENT_OVER_APPROVED": 1}
    with sqlite3.connect(dataset / "fraudnet.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_exception").fetchone()[0] == 4
    rows = json.loads((dataset / "reports/data_exception.json").read_text(encoding="utf-8"))
    assert {row["exception_type"] for row in rows} == set(summary["exceptions"])


def test_coverage_counts_every_required_case(summary):
    assert summary["coverage"] and all(count > 0 for count in summary["coverage"].values())


def test_validation_needs_only_the_input_folder(dataset, summary, tmp_path):
    """Hidden labels play no part: a copy holding only input/ gives the same result."""
    shutil.copytree(dataset / "input", tmp_path / "input")
    alone = validate(tmp_path)
    assert alone["checks"] == summary["checks"] and alone["exceptions"] == summary["exceptions"]
    assert not (tmp_path / "hidden").exists()


def test_reports_hold_no_label_names(dataset, summary):
    text = "".join((dataset / "reports" / name).read_text(encoding="utf-8")
                   for name in ("validation_summary.json", "data_exception.json", "source_manifest.json"))
    for word in ("ground_truth", "is_fraud", "ring_id", "RING-", "R-RING", "B-HOUSE", "EC-4"):
        assert word not in text


def test_input_manifest_records_seed_and_scale_only(dataset):
    manifest = json.loads((dataset / "input/input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator"] == {"seed": SEED, "scale": SCALE}
    assert all(item["path"].split("/")[0] in {"csv", "json", "sql"} for item in manifest["files"])


def test_source_manifest_records_how_the_data_was_made(dataset):
    manifest = json.loads((dataset / "reports/source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == SEED and manifest["scale"] == SCALE
    assert set(manifest["software"]) == {"python", "numpy", "pandas", "networkx"}
    assert manifest["row_counts"]["claim"] == 500 and "synthetic" in manifest["provenance"]
    assert "hidden" not in json.dumps(manifest)


def test_json_export_matches_csv_rows(dataset):
    records = json.loads((dataset / "input/json/claim.json").read_text(encoding="utf-8"))
    csv_lines = (dataset / "input/csv/claim.csv").read_text(encoding="utf-8").splitlines()
    assert len(records) == len(csv_lines) - 1
    assert list(records[0]) == csv_lines[0].split(",")
    assert any(record["policy_id"] is None for record in records)  # empty values become null


# ---- each rule catches a deliberate break

def test_v01_catches_a_repeated_or_malformed_id(tables):
    tables["claim"].loc[tables["claim"].index[1], "claim_id"] = tables["claim"]["claim_id"].iloc[0]
    _first_row(tables["provider"], "provider_id", "PRV-1")
    assert len(checks.v01_primary_keys(tables).failures) >= 2


def test_v02_catches_a_missing_parent(tables):
    _first_row(tables["claim"], "claimant_id", "CLT-999999")
    assert checks.v02_foreign_keys(tables).failures


def test_v02_catches_an_empty_policy_id_for_a_real_policy(tables):
    claim = tables["claim"]
    row = claim[claim["policy_id"].notna()].index[0]
    claim.loc[row, "policy_id"] = None
    assert any("policy_ref exists" in failure for failure in checks.v02_foreign_keys(tables).failures)


def test_v03_catches_a_value_outside_the_list(tables):
    _first_row(tables["claim"], "current_status", "MAYBE")
    assert checks.v03_enums(tables).failures


def test_v04_catches_a_report_before_the_incident(tables):
    _first_row(tables["claim"], "reported_date", "2025-01-01")
    assert checks.v04_dates(tables).failures


def test_v04_catches_an_impossible_date(tables):
    _first_row(tables["policy"], "effective_to", "2026-02-30")
    assert any("not a valid date" in failure for failure in checks.v04_dates(tables).failures)


@pytest.mark.parametrize("table, column", [("invoice_line", "line_amount_cents"), ("claim", "balance_cents"),
                                           ("claim", "approved_amount_cents"), ("invoice", "total_cents")])
def test_v05_catches_a_changed_amount(tables, table, column):
    tables[table].loc[tables[table].index[0], column] += 1
    assert checks.v05_arithmetic(tables).failures


def test_v06_catches_a_status_that_does_not_match_history(tables):
    claim = tables["claim"]
    row = claim[claim["current_status"] == "CLOSED"].index[0]
    claim.loc[row, "current_status"] = "APPROVED"
    assert checks.v06_lifecycles(tables).failures


def test_v06_catches_a_skipped_transition(tables):
    events = tables["claim_events"]
    row = events[events["to_status"] == "APPROVED"].index[0]
    events.loc[row, "from_status"] = "SUBMITTED"
    assert checks.v06_lifecycles(tables).failures


def test_v07_catches_a_repeated_edge(tables):
    edges = tables["relationship_edge"]
    tables["relationship_edge"] = pd.concat([edges, edges.iloc[[0]].assign(edge_id="EDG-999999")], ignore_index=True)
    assert checks.v07_duplicates(tables).failures


def test_v08_catches_a_csv_edited_after_export(dataset, tmp_path):
    shutil.copytree(dataset / "input", tmp_path / "input")
    path = tmp_path / "input/csv/claimant.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace(lines[1].split(",")[1], "Edited Name", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    edited, manifest = load_input(tmp_path / "input")
    result, connection = checks.v08_cross_file(edited, tmp_path / "input", manifest)
    connection.close()
    assert any("checksum" in failure for failure in result.failures)
    assert any("differ from CSV" in failure for failure in result.failures)


def test_v09_catches_a_wrong_volume(tables):
    assert checks.v09_volume(tables, {"generator": {"seed": SEED, "scale": 0.2}}).failures
    assert checks.v09_volume(tables, {}).failures


def test_v10_catches_missing_coverage(tables):
    events = tables["claim_events"]
    tables["claim_events"] = events[events["to_status"] != "WITHDRAWN"]
    assert any("withdrawn" in failure for failure in checks.v10_coverage(tables).failures)


def test_v11_catches_a_join_that_loses_rows(tables, dataset):
    tables["invoice"] = tables["invoice"].iloc[1:]
    connection = sqlite3.connect(":memory:")
    assert checks.v11_joins(tables, connection).failures
    connection.close()


def test_v12_catches_a_real_looking_contact(tables):
    _first_row(tables["claimant_contact"], "email", "someone@gmail.com")
    _first_row(tables["provider"], "phone", "212-555-0100")
    assert len(checks.v12_synthetic(tables).failures) >= 2


def test_command_fails_with_exit_code_one_on_broken_data(dataset, tmp_path):
    shutil.copytree(dataset / "input", tmp_path / "input")
    path = tmp_path / "input/csv/claim.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("CLOSED", "MAYBE", 1), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "fraudnet.validate", "--data", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 1 and "FAIL" in result.stdout


# ---- reproducibility

def test_reproducibility_check_passes_and_matches_existing_output(dataset):
    report = check_reproducibility(SEED, SCALE, compare_with=dataset)
    assert report["status"] == "PASS" and not report["mismatched_files"]
    assert report["matches_existing_output"] is True
    assert report["csv_files_changed_by_different_seed"] > 0
    assert any(name.startswith("hidden/") for name in report["checksums"])
