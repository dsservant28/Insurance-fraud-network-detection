"""Investigation tables in fraudnet.db. They survive detector and validator reruns.

The detector and validator replace `network` and `data_exception` on every run, so a case can't
hold a foreign key to them. It stores the run ID and a snapshot of what triggered it instead.
Subjects do reference `graph_node`, which only changes when the data is regenerated.
"""
from __future__ import annotations

import sqlite3

STATUSES = "('OPEN', 'IN_REVIEW', 'ESCALATED', 'CLOSED_CONFIRMED', 'CLOSED_CLEARED')"
ACTIONS = "('OPEN', 'START_REVIEW', 'ESCALATE', 'CONFIRM', 'CLEAR', 'REOPEN', 'NOTE', 'BLOCKED')"
ROLES = "('OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN')"

DDL = (
    f"""CREATE TABLE IF NOT EXISTS investigation (
    investigation_id TEXT PRIMARY KEY CHECK (investigation_id GLOB 'INVG-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('NETWORK_SCORE', 'DATA_EXCEPTION')),
    run_id TEXT,
    network_id TEXT,
    exception_id TEXT,
    exception_type TEXT,
    priority TEXT NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    trigger_score REAL CHECK (trigger_score IS NULL OR trigger_score BETWEEN 0 AND 1),
    trigger_summary TEXT NOT NULL CHECK (length(trigger_summary) > 0),
    recommended_action TEXT NOT NULL CHECK (recommended_action IN ('INVESTIGATE', 'HOLD_PAYMENT', 'REVIEW_PAYMENT')),
    opened_at TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN {STATUSES}),
    CHECK ((trigger_type = 'NETWORK_SCORE' AND network_id IS NOT NULL AND run_id IS NOT NULL AND exception_id IS NULL)
        OR (trigger_type = 'DATA_EXCEPTION' AND exception_id IS NOT NULL AND network_id IS NULL))
) STRICT;""",
    f"""CREATE TABLE IF NOT EXISTS investigation_events (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB 'VEV-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    investigation_id TEXT NOT NULL REFERENCES investigation(investigation_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    action TEXT NOT NULL CHECK (action IN {ACTIONS}),
    from_status TEXT CHECK (from_status IS NULL OR from_status IN {STATUSES}),
    to_status TEXT NOT NULL CHECK (to_status IN {STATUSES}),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN {ROLES}),
    actor_id TEXT NOT NULL,
    reason_code TEXT,
    note TEXT,
    prev_hash TEXT NOT NULL CHECK (length(prev_hash) = 64),
    event_hash TEXT NOT NULL UNIQUE CHECK (length(event_hash) = 64),
    UNIQUE (investigation_id, seq),
    CHECK ((seq = 1) = (from_status IS NULL)),
    CHECK (action IN ('NOTE', 'BLOCKED') OR seq = 1 OR from_status <> to_status)
) STRICT;""",
    """CREATE TABLE IF NOT EXISTS investigation_subject (
    investigation_id TEXT NOT NULL REFERENCES investigation(investigation_id),
    node_id TEXT NOT NULL REFERENCES graph_node(node_id),
    subject_role TEXT NOT NULL,
    PRIMARY KEY (investigation_id, node_id)
) STRICT;""",
    # History is append-only: events and subjects can never change or disappear.
    """CREATE TRIGGER IF NOT EXISTS investigation_events_no_update BEFORE UPDATE ON investigation_events
    BEGIN SELECT RAISE(ABORT, 'investigation_events is append-only'); END;""",
    """CREATE TRIGGER IF NOT EXISTS investigation_events_no_delete BEFORE DELETE ON investigation_events
    BEGIN SELECT RAISE(ABORT, 'investigation_events is append-only'); END;""",
    """CREATE TRIGGER IF NOT EXISTS investigation_subject_no_change BEFORE UPDATE ON investigation_subject
    BEGIN SELECT RAISE(ABORT, 'investigation_subject is append-only'); END;""",
    """CREATE TRIGGER IF NOT EXISTS investigation_subject_no_delete BEFORE DELETE ON investigation_subject
    BEGIN SELECT RAISE(ABORT, 'investigation_subject is append-only'); END;""",
    """CREATE TRIGGER IF NOT EXISTS investigation_no_delete BEFORE DELETE ON investigation
    BEGIN SELECT RAISE(ABORT, 'investigations are never deleted'); END;""",
    # Only current_status may change, and only to the status of the latest event.
    """CREATE TRIGGER IF NOT EXISTS investigation_fixed_fields BEFORE UPDATE ON investigation
    WHEN NEW.investigation_id IS NOT OLD.investigation_id OR NEW.trigger_type IS NOT OLD.trigger_type
      OR NEW.run_id IS NOT OLD.run_id OR NEW.network_id IS NOT OLD.network_id
      OR NEW.exception_id IS NOT OLD.exception_id OR NEW.priority IS NOT OLD.priority
      OR NEW.trigger_summary IS NOT OLD.trigger_summary OR NEW.opened_at IS NOT OLD.opened_at
      OR NEW.opened_by IS NOT OLD.opened_by
    BEGIN SELECT RAISE(ABORT, 'only current_status of an investigation can change'); END;""",
    """CREATE TRIGGER IF NOT EXISTS investigation_status_follows_events BEFORE UPDATE OF current_status ON investigation
    WHEN NEW.current_status IS NOT (SELECT to_status FROM investigation_events
                                    WHERE investigation_id = NEW.investigation_id ORDER BY seq DESC LIMIT 1)
    BEGIN SELECT RAISE(ABORT, 'current_status must equal the latest event'); END;""",
)


def connect(database) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    for statement in DDL:
        connection.execute(statement)
    connection.commit()
