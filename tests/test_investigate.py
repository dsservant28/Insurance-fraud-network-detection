"""Investigation workflow: lifecycle, roles, four-eyes, append-only history and the hash chain."""
import json
import sqlite3
import subprocess
import sys

import pytest

from fraudnet.detect.__main__ import detect
from fraudnet.detect.config import load_config
from fraudnet.detect.pipeline import run_detector
from fraudnet.detect.store import write_database
from fraudnet.generate.__main__ import run as generate_into
from fraudnet.inputs import load_input, manifest_sha256
from fraudnet.investigate.demo import DemoClock, seed_demo
from fraudnet.investigate.schema import connect
from fraudnet.investigate.workflow import Workflow, WorkflowError, export_history
from fraudnet.validate.__main__ import validate


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cases")
    generate_into(20261022, 0.1, folder)
    validate(folder)
    detect(folder)
    return folder


@pytest.fixture()
def workflow(data, tmp_path):
    """A fresh copy of the database for each test, so cases never leak between tests."""
    database = tmp_path / "fraudnet.db"
    source = sqlite3.connect(data / "fraudnet.db")
    target = sqlite3.connect(database)
    source.backup(target)
    source.close()
    target.close()
    connection = connect(database)
    yield Workflow(connection, clock=DemoClock())
    connection.close()


def _first(workflow, sql):
    return workflow.db.execute(sql).fetchone()[0]


def _network(workflow, rank=1):
    return _first(workflow, f"SELECT network_id FROM network WHERE rank = {rank}")


def _statuses(workflow, case):
    return [(event["action"], event["to_status"]) for event in workflow.history(case)]


def test_opening_from_a_network_keeps_a_snapshot_and_its_subjects(workflow):
    network = _network(workflow)
    case = workflow.open_from_network(network, "USR-OPS-01")
    row = workflow.case(case)
    assert case == "INVG-2026-000001" and row["current_status"] == "OPEN" and row["trigger_type"] == "NETWORK_SCORE"
    expected = workflow.db.execute("SELECT priority, score, summary, run_id FROM network WHERE network_id = ?",
                                   (network,)).fetchone()
    assert (row["priority"], row["trigger_score"], row["trigger_summary"], row["run_id"]) == tuple(expected)
    members = {r[0] for r in workflow.db.execute("SELECT node_id FROM network_member WHERE network_id = ?", (network,))}
    assert {subject["node_id"] for subject in workflow.subjects(case)} == members


def test_a_network_has_one_active_case_and_admins_open_none(workflow):
    network = _network(workflow)
    workflow.open_from_network(network, "USR-OPS-01")
    with pytest.raises(WorkflowError) as error:
        workflow.open_from_network(network, "USR-OPS-02")
    assert error.value.code == "ALREADY_OPEN"
    with pytest.raises(WorkflowError) as error:
        workflow.open_from_network(_network(workflow, 2), "USR-ADM-01")
    assert error.value.code == "ROLE_NOT_ALLOWED"


def test_full_lifecycle_with_escalation_and_a_second_reviewer(workflow):
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    assert workflow.act(case, "START_REVIEW", "USR-OPS-01").accepted
    assert workflow.act(case, "ESCALATE", "USR-OPS-01", "NEEDS_SENIOR_REVIEW").accepted
    outcome = workflow.act(case, "CONFIRM", "USR-RSK-01", "CONFIRMED_LINKS", "Refer to SIU.")
    assert outcome.accepted and outcome.status == "CLOSED_CONFIRMED"
    assert workflow.act(case, "REOPEN", "USR-RSK-02", "NEW_EVIDENCE").status == "IN_REVIEW"
    assert _statuses(workflow, case) == [("OPEN", "OPEN"), ("START_REVIEW", "IN_REVIEW"), ("ESCALATE", "ESCALATED"),
                                         ("CONFIRM", "CLOSED_CONFIRMED"), ("REOPEN", "IN_REVIEW")]
    assert workflow.case(case)["current_status"] == "IN_REVIEW"


def test_four_eyes_rule_blocks_confirming_your_own_case(workflow):
    case = workflow.open_from_network(_network(workflow), "USR-RSK-01")
    workflow.act(case, "START_REVIEW", "USR-RSK-01")
    outcome = workflow.act(case, "CONFIRM", "USR-RSK-01", "CONFIRMED_LINKS")
    assert not outcome.accepted and workflow.case(case)["current_status"] == "IN_REVIEW"
    blocked = workflow.history(case)[-1]
    assert blocked["action"] == "BLOCKED" and blocked["reason_code"] == "FOUR_EYES_BLOCKED"
    assert workflow.act(case, "CONFIRM", "USR-RSK-02", "CONFIRMED_LINKS").accepted


@pytest.mark.parametrize("actor, action, reason, block", [
    ("USR-OPS-01", "CONFIRM", "CONFIRMED_LINKS", "ROLE_NOT_ALLOWED"),
    ("USR-RSK-01", "CONFIRM", None, "REASON_REQUIRED"),
    ("USR-RSK-01", "CONFIRM", "made-up", "REASON_REQUIRED"),
    ("USR-RSK-01", "REOPEN", "NEW_EVIDENCE", "INVALID_TRANSITION"),
    ("USR-OPS-02", "CLEAR", "INSUFFICIENT_EVIDENCE", "ANALYST_LIMIT"),
])
def test_refused_actions_are_recorded_not_dropped(workflow, actor, action, reason, block):
    workflow.db.execute("UPDATE network SET priority = 'HIGH' WHERE rank = 1")
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    workflow.act(case, "START_REVIEW", "USR-OPS-01")
    outcome = workflow.act(case, action, actor, reason)
    assert not outcome.accepted and workflow.history(case)[-1]["reason_code"] == block
    assert workflow.case(case)["current_status"] == "IN_REVIEW"


def test_critical_cases_must_be_escalated_before_closing(workflow):
    workflow.db.execute("UPDATE network SET priority = 'CRITICAL' WHERE rank = 1")
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    workflow.act(case, "START_REVIEW", "USR-OPS-01")
    assert workflow.act(case, "CLEAR", "USR-RSK-01", "BENIGN_EXPLANATION").message.startswith("a CRITICAL case")
    workflow.act(case, "ESCALATE", "USR-OPS-01", "CRITICAL_PRIORITY")
    assert workflow.act(case, "CLEAR", "USR-RSK-01", "BENIGN_EXPLANATION").accepted


def test_analysts_may_clear_low_or_medium_cases(workflow):
    workflow.db.execute("UPDATE network SET priority = 'MEDIUM' WHERE rank = 1")
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    workflow.act(case, "START_REVIEW", "USR-OPS-01")
    assert workflow.act(case, "CLEAR", "USR-OPS-02", "BENIGN_EXPLANATION").status == "CLOSED_CLEARED"


def test_system_admins_leave_no_case_events(workflow):
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    with pytest.raises(WorkflowError):
        workflow.act(case, "START_REVIEW", "USR-ADM-01")
    assert len(workflow.history(case)) == 1


def test_orphan_policy_routes_to_an_exception_case(workflow):
    exception = _first(workflow, "SELECT exception_id FROM data_exception WHERE exception_type = 'ORPHAN_POLICY_REF'")
    case = workflow.open_from_exception(exception, "USR-OPS-02")
    row = workflow.case(case)
    assert row["trigger_type"] == "DATA_EXCEPTION" and row["recommended_action"] == "HOLD_PAYMENT"
    assert row["network_id"] is None and [s["subject_role"] for s in workflow.subjects(case)] == ["CLAIMANT"]


def test_history_cannot_be_edited_or_deleted(workflow):
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    for statement in ("UPDATE investigation_events SET note = 'changed'", "DELETE FROM investigation_events",
                      "DELETE FROM investigation", "DELETE FROM investigation_subject",
                      "UPDATE investigation SET priority = 'LOW'",
                      "UPDATE investigation SET current_status = 'CLOSED_CLEARED'"):
        with pytest.raises(sqlite3.DatabaseError):
            workflow.db.execute(statement)
    assert len(workflow.history(case)) == 1


def test_hash_chain_detects_tampering_with_the_database_file(workflow):
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    workflow.act(case, "START_REVIEW", "USR-OPS-01")
    workflow.act(case, "NOTE", "USR-OPS-01", note="original note")
    assert workflow.verify_chain(case)["intact"]
    # Someone with direct file access removes the guard and rewrites a note.
    workflow.db.execute("DROP TRIGGER investigation_events_no_update")
    workflow.db.execute("UPDATE investigation_events SET note = 'rewritten' WHERE seq = 3")
    assert workflow.verify_chain(case) == {"intact": False, "broken_at_seq": 3, "event_id": "VEV-00000003"}


def test_cases_survive_a_detector_rerun(workflow, data):
    case = workflow.open_from_network(_network(workflow), "USR-OPS-01")
    database = workflow.db.execute("PRAGMA database_list").fetchone()["file"]
    workflow.db.commit()
    tables, _ = load_input(data / "input")
    settings, config_sha = load_config()
    write_database(run_detector(tables, settings, manifest_sha256(data / "input"), config_sha), database)
    assert workflow.case(case)["current_status"] == "OPEN" and workflow.verify_chain(case)["intact"]


def test_demo_history_and_export(workflow):
    opened = seed_demo(workflow)
    assert len(opened) >= 4 and seed_demo(workflow) == []
    exported = json.loads(json.dumps(export_history(workflow)))
    assert all(chain["intact"] for chain in exported["chains"].values())
    reasons = {event["reason_code"] for event in exported["events"]}
    assert {"FOUR_EYES_BLOCKED", "ROLE_NOT_ALLOWED", "CONFIRMED_LINKS"} <= reasons
    assert {case["trigger_type"] for case in exported["cases"]} == {"NETWORK_SCORE", "DATA_EXCEPTION"}


def test_command_line_demo_and_verify(data, tmp_path):
    (tmp_path / "fraudnet.db").write_bytes((data / "fraudnet.db").read_bytes())
    for command in ("demo", "verify"):
        result = subprocess.run([sys.executable, "-m", "fraudnet.investigate", "--data", str(tmp_path), command],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    assert "chain intact" in result.stdout and "BROKEN" not in result.stdout
