"""The SQL export and SQLite database, including rules the database itself enforces."""
import sqlite3

import pytest

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.export import write_input
from fraudnet.generate.pipeline import generate
from fraudnet.generate.schema import EVENT_TABLES, TABLES, schema_sql
from fraudnet.generate.sql_export import seed_sql


@pytest.fixture(scope="module")
def tables():
    return generate(GeneratorConfig(scale=0.1))


@pytest.fixture(scope="module")
def built(tables, tmp_path_factory):
    folder = tmp_path_factory.mktemp("output")
    write_input(tables, folder)
    return folder


@pytest.fixture()
def db(built, tmp_path):
    """A private copy for each test, with foreign keys on, so writes can't affect other tests."""
    source = sqlite3.connect(built / "fraudnet.db")
    target = sqlite3.connect(tmp_path / "copy.db")
    source.backup(target)
    source.close()
    target.execute("PRAGMA foreign_keys = ON")
    yield target
    target.close()


def _first(db, sql):
    return db.execute(sql).fetchone()[0]


def test_every_table_is_in_the_schema_and_columns_match(tables, db):
    assert set(tables) == set(TABLES)
    for name, table in tables.items():
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({name})")]
        assert columns == list(table.columns), name


def test_row_counts_match_generated_tables(tables, db):
    for name, table in tables.items():
        assert _first(db, f"SELECT COUNT(*) FROM {name}") == len(table), name


def test_all_foreign_keys_are_valid(db):
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_empty_values_load_as_null(tables, db):
    expected = int(tables["payment"]["payee_claimant_id"].isna().sum())
    assert _first(db, "SELECT COUNT(*) FROM payment WHERE payee_claimant_id IS NULL") == expected


def test_documented_joins_lose_no_rows(tables, db):
    joined = _first(db, """
        SELECT COUNT(*) FROM claim c
        JOIN incident i ON i.incident_id = c.incident_id
        JOIN claimant p ON p.claimant_id = c.claimant_id
        LEFT JOIN policy o ON o.policy_id = c.policy_id
        WHERE o.policy_id IS NOT NULL OR c.policy_id IS NULL""")
    assert joined == len(tables["claim"])
    # The only claims without a policy row are EC-1 claims, whose policy_ref names no policy.
    assert _first(db, "SELECT COUNT(*) FROM claim WHERE policy_id IS NULL AND policy_ref IN "
                      "(SELECT policy_id FROM policy)") == 0
    edges = _first(db, """SELECT COUNT(*) FROM relationship_edge e
        JOIN graph_node s ON s.node_id = e.source_node_id JOIN graph_node t ON t.node_id = e.target_node_id""")
    assert edges == len(tables["relationship_edge"])
    assert _first(db, "SELECT COUNT(*) FROM payment p JOIN invoice i USING (invoice_id, claim_id)") == len(tables["payment"])


def test_foreign_key_violation_is_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE claim SET claimant_id = 'CLT-999999' WHERE rowid = 1")


def test_payment_must_belong_to_the_invoice_claim(db):
    other_claim = _first(db, "SELECT claim_id FROM claim WHERE claim_id NOT IN "
                             "(SELECT claim_id FROM payment WHERE rowid = 1) LIMIT 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE payment SET claim_id = ? WHERE rowid = 1", (other_claim,))


@pytest.mark.parametrize("statement", [
    "UPDATE policy SET policy_type = 'BOAT' WHERE rowid = 1",
    "UPDATE claim SET current_status = 'MAYBE' WHERE rowid = 1",
    "UPDATE claim SET claim_id = 'CLAIM-1' WHERE rowid = 1",
    "UPDATE claim SET balance_cents = balance_cents + 1 WHERE rowid = 1",
    "UPDATE invoice_line SET line_amount_cents = line_amount_cents + 1 WHERE rowid = 1",
    "UPDATE payment SET payee_claimant_id = NULL, payee_provider_id = NULL WHERE rowid = 1",
    "UPDATE invoice SET provider_id = 'PRV-999999' WHERE rowid = 1",
])
def test_invalid_values_are_rejected(db, statement):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(statement)


def test_tables_are_strict_about_types(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE policy SET deductible_cents = 'lots' WHERE rowid = 1")


@pytest.mark.parametrize("table", EVENT_TABLES)
def test_event_history_cannot_be_changed_or_deleted(db, table):
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(f"UPDATE {table} SET reason_code = 'EDITED' WHERE rowid = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(f"DELETE FROM {table} WHERE rowid = 1")


def test_nonexistent_policy_reference_can_load_with_empty_policy_id(db):
    """EC-1 must load so that it can be reported."""
    db.execute("UPDATE claim SET policy_ref = 'POL-999999', policy_id = NULL WHERE rowid = 1")
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_policy_id_cannot_differ_from_policy_ref(db):
    other = _first(db, "SELECT policy_id FROM policy WHERE policy_id <> "
                       "(SELECT policy_id FROM claim WHERE rowid = 1) LIMIT 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE claim SET policy_id = ? WHERE rowid = 1", (other,))


def test_overpayment_can_load_with_negative_balance(db):
    """EC-2 must load so that it can be reported."""
    db.execute("UPDATE claim SET paid_amount_cents = approved_amount_cents + 100, balance_cents = -100 WHERE rowid = 1")
    assert _first(db, "SELECT balance_cents FROM claim WHERE rowid = 1") == -100


def test_duplicate_external_invoice_number_can_load(db):
    """EC-3 must load so that it can be reported."""
    db.execute("UPDATE invoice SET external_invoice_no = 'EXT-SAME' WHERE rowid IN (1, 2)")
    assert _first(db, "SELECT COUNT(*) FROM invoice WHERE external_invoice_no = 'EXT-SAME'") == 2


def test_text_with_apostrophes_is_escaped(tables):
    changed = {name: table.copy() for name, table in tables.items()}
    changed["incident"].loc[0, "narrative"] = "The driver's door; it's -- damaged"
    assert "The driver''s door; it''s -- damaged" in seed_sql(changed)


def test_sql_files_are_identical_for_the_same_seed(tables, tmp_path):
    write_input(tables, tmp_path / "a")
    write_input(generate(GeneratorConfig(scale=0.1)), tmp_path / "b")
    for name in ("schema.sql", "seed.sql"):
        assert (tmp_path / "a/input/sql" / name).read_bytes() == (tmp_path / "b/input/sql" / name).read_bytes()


def test_manifest_lists_sql_files_but_not_the_database(built):
    text = (built / "input/input_manifest.json").read_text(encoding="utf-8")
    assert "sql/schema.sql" in text and "sql/seed.sql" in text
    assert "fraudnet.db" not in text


def test_running_again_replaces_the_database(tables, tmp_path):
    write_input(tables, tmp_path)
    write_input(tables, tmp_path)
    connection = sqlite3.connect(tmp_path / "fraudnet.db")
    assert connection.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == len(tables["claim"])
    connection.close()


def test_sql_and_database_hold_no_label_names(tables, db):
    forbidden = {"ground_truth", "is_fraud", "ring_id", "planted", "issue_type", "household_id"}
    text = schema_sql().lower()
    assert not [word for word in forbidden if word in text]
    for name in TABLES:
        assert not forbidden & {row[1] for row in db.execute(f"PRAGMA table_info({name})")}
