"""Investigation workflow: who may do what, the four-eyes rule, and hash-chained history.

Rules: ARCHITECTURE.md section 6 and DATA_DICTIONARY section 6. Every attempt is recorded. A refused
action is written as a BLOCKED event with the reason, so the history shows what was tried as well
as what happened.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fraudnet.investigate.schema import ensure_schema

GENESIS = "0" * 64

# Synthetic staff accounts for the demo. No real people.
STAFF = {
    "USR-OPS-01": ("OPS_ANALYST", "Operations analyst 1"),
    "USR-OPS-02": ("OPS_ANALYST", "Operations analyst 2"),
    "USR-RSK-01": ("RISK_REVIEWER", "Risk reviewer 1"),
    "USR-RSK-02": ("RISK_REVIEWER", "Risk reviewer 2"),
    "USR-ADM-01": ("SYS_ADMIN", "System administrator"),
}

# action: (statuses it may start from, status it leads to, roles allowed, reason required)
ACTIONS = {
    "START_REVIEW": (("OPEN",), "IN_REVIEW", ("OPS_ANALYST", "RISK_REVIEWER"), False),
    "ESCALATE": (("IN_REVIEW",), "ESCALATED", ("OPS_ANALYST", "RISK_REVIEWER"), True),
    "CONFIRM": (("IN_REVIEW", "ESCALATED"), "CLOSED_CONFIRMED", ("RISK_REVIEWER",), True),
    "CLEAR": (("IN_REVIEW", "ESCALATED"), "CLOSED_CLEARED", ("OPS_ANALYST", "RISK_REVIEWER"), True),
    "REOPEN": (("CLOSED_CONFIRMED", "CLOSED_CLEARED"), "IN_REVIEW", ("RISK_REVIEWER",), True),
}
OPENERS = ("OPS_ANALYST", "RISK_REVIEWER")
REASONS = {
    "ESCALATE": ("NEEDS_SENIOR_REVIEW", "HIGH_VALUE", "CRITICAL_PRIORITY"),
    "CONFIRM": ("CONFIRMED_LINKS", "CONFIRMED_DUPLICATE_BILLING", "CONFIRMED_OVERPAYMENT", "CONFIRMED_DATA_ERROR"),
    "CLEAR": ("INSUFFICIENT_EVIDENCE", "BENIGN_EXPLANATION", "DATA_ERROR_CORRECTED", "PAYMENT_RECOVERED"),
    "REOPEN": ("NEW_EVIDENCE", "REVIEW_ERROR"),
}
BLOCK_REASONS = ("ROLE_NOT_ALLOWED", "INVALID_TRANSITION", "FOUR_EYES_BLOCKED", "ESCALATION_REQUIRED",
                 "ANALYST_LIMIT", "REASON_REQUIRED", "NOTE_REQUIRED")
EXCEPTION_ACTIONS = {"ORPHAN_POLICY_REF": "HOLD_PAYMENT", "PAYMENT_OVER_APPROVED": "REVIEW_PAYMENT",
                     "DUPLICATE_INVOICE": "INVESTIGATE"}


class WorkflowError(Exception):
    """An action that the rules refuse. `code` is one of BLOCK_REASONS or a setup error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Outcome:
    accepted: bool
    event_id: str
    status: str
    message: str


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_hash(event: dict) -> str:
    """SHA-256 over every field of the event except its own hash, including the previous event's hash."""
    body = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class Workflow:
    """Case operations on one fraudnet.db connection. `clock` returns UTC timestamps (fixed in tests)."""

    def __init__(self, connection: sqlite3.Connection, clock: Callable[[], str] = utc_now) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self.db, self.clock = connection, clock
        ensure_schema(connection)

    # ---- reading

    def case(self, investigation_id: str) -> dict:
        row = self.db.execute("SELECT * FROM investigation WHERE investigation_id = ?", (investigation_id,)).fetchone()
        if row is None:
            raise WorkflowError("NOT_FOUND", f"no investigation {investigation_id}")
        return dict(row)

    def cases(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM investigation ORDER BY investigation_id")]

    def history(self, investigation_id: str | None = None) -> list[dict]:
        query, args = "SELECT * FROM investigation_events", ()
        if investigation_id:
            query, args = query + " WHERE investigation_id = ?", (investigation_id,)
        return [dict(row) for row in self.db.execute(query + " ORDER BY investigation_id, seq", args)]

    def subjects(self, investigation_id: str) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM investigation_subject WHERE investigation_id = ? ORDER BY node_id", (investigation_id,))]

    def verify_chain(self, investigation_id: str) -> dict:
        """Recompute every hash. Any edit to a stored event breaks the chain from that event on."""
        previous = GENESIS
        for event in self.history(investigation_id):
            if event["prev_hash"] != previous or event_hash(event) != event["event_hash"]:
                return {"intact": False, "broken_at_seq": event["seq"], "event_id": event["event_id"]}
            previous = event["event_hash"]
        return {"intact": True, "broken_at_seq": None, "event_id": None}

    # ---- writing

    def _staff(self, actor_id: str) -> str:
        if actor_id not in STAFF:
            raise WorkflowError("UNKNOWN_ACTOR", f"{actor_id} is not a staff account")
        return STAFF[actor_id][0]

    def _next_id(self, table: str, column: str, prefix: str, width: int) -> str:
        last = self.db.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
        number = int(last[len(prefix):]) + 1 if last else 1
        return f"{prefix}{number:0{width}d}"

    def _append(self, investigation_id: str, action: str, from_status: str | None, to_status: str, actor_id: str,
                reason_code: str | None, note: str | None) -> str:
        last = self.db.execute("SELECT seq, event_hash FROM investigation_events WHERE investigation_id = ? "
                               "ORDER BY seq DESC LIMIT 1", (investigation_id,)).fetchone()
        event = {
            "event_id": self._next_id("investigation_events", "event_id", "VEV-", 8),
            "investigation_id": investigation_id, "seq": last["seq"] + 1 if last else 1, "action": action,
            "from_status": from_status, "to_status": to_status, "event_at": self.clock(),
            "actor_role": STAFF[actor_id][0], "actor_id": actor_id, "reason_code": reason_code, "note": note,
            "prev_hash": last["event_hash"] if last else GENESIS,
        }
        event["event_hash"] = event_hash(event)
        self.db.execute(f"INSERT INTO investigation_events ({', '.join(event)}) VALUES ({', '.join('?' * len(event))})",
                        tuple(event.values()))
        if to_status != from_status:
            self.db.execute("UPDATE investigation SET current_status = ? WHERE investigation_id = ?",
                            (to_status, investigation_id))
        return event["event_id"]

    def _open(self, case: dict, subjects: list[tuple[str, str]], actor_id: str, note: str | None) -> str:
        role = self._staff(actor_id)
        if role not in OPENERS:
            raise WorkflowError("ROLE_NOT_ALLOWED", f"{role} can't open cases; system administrators make no case decisions")
        key, value = ("network_id", case["network_id"]) if case["network_id"] else ("exception_id", case["exception_id"])
        active = self.db.execute(f"SELECT investigation_id FROM investigation WHERE {key} = ? AND current_status NOT IN "
                                 "('CLOSED_CONFIRMED', 'CLOSED_CLEARED')", (value,)).fetchone()
        if active:
            raise WorkflowError("ALREADY_OPEN", f"{value} already has open case {active[0]}")
        case = {"investigation_id": self._next_id("investigation", "investigation_id", "INVG-2026-", 6), **case,
                "opened_at": self.clock(), "opened_by": actor_id, "current_status": "OPEN"}
        with self.db:
            self.db.execute(f"INSERT INTO investigation ({', '.join(case)}) VALUES ({', '.join('?' * len(case))})",
                            tuple(case.values()))
            self.db.executemany("INSERT INTO investigation_subject VALUES (?, ?, ?)",
                                [(case["investigation_id"], node, role_name) for node, role_name in sorted(set(subjects))])
            self._append(case["investigation_id"], "OPEN", None, "OPEN", actor_id, None, note)
        return case["investigation_id"]

    def open_from_network(self, network_id: str, actor_id: str, note: str | None = None) -> str:
        """Open a case on a detected network, keeping a snapshot of its score and evidence summary."""
        row = self.db.execute("SELECT * FROM network WHERE network_id = ?", (network_id,)).fetchone()
        if row is None:
            raise WorkflowError("NOT_FOUND", f"no network {network_id} in the current detector run")
        members = self.db.execute("SELECT node_id, member_role FROM network_member WHERE network_id = ?",
                                  (network_id,)).fetchall()
        case = {"trigger_type": "NETWORK_SCORE", "run_id": row["run_id"], "network_id": network_id,
                "exception_id": None, "exception_type": None, "priority": row["priority"], "trigger_score": row["score"],
                "trigger_summary": row["summary"], "recommended_action": "INVESTIGATE"}
        return self._open(case, [(member["node_id"], member["member_role"]) for member in members], actor_id, note)

    def open_from_exception(self, exception_id: str, actor_id: str, note: str | None = None) -> str:
        """Open an exception case: the required route for data errors such as an orphan policy (EC-1)."""
        row = self.db.execute("SELECT * FROM data_exception WHERE exception_id = ?", (exception_id,)).fetchone()
        if row is None:
            raise WorkflowError("NOT_FOUND", f"no data exception {exception_id}")
        detail = json.loads(row["detail_json"])
        subjects = []
        if row["entity_type"] == "CLAIM":
            claimant = self.db.execute("SELECT claimant_id FROM claim WHERE claim_id = ?", (row["entity_id"],)).fetchone()
            subjects.append((claimant[0], "CLAIMANT"))
            subjects += [(payment, "PAYMENT") for payment in detail.get("settled_payment_ids", [])]
        else:  # A duplicate invoice: every claimant billed and the provider.
            subjects += [(claimant, "CLAIMANT") for claimant in detail.get("claimant_ids", [])]
            subjects.append((detail["provider_id"], "PROVIDER"))
        summary = (f"{row['exception_type']} on {row['entity_type'].lower()} {row['entity_id']}: {row['field_name']} is "
                   f"{row['observed_value']}, expected: {row['expected_rule']}.")
        case = {"trigger_type": "DATA_EXCEPTION", "run_id": None, "network_id": None, "exception_id": exception_id,
                "exception_type": row["exception_type"], "priority": row["severity"], "trigger_score": None,
                "trigger_summary": summary, "recommended_action": EXCEPTION_ACTIONS[row["exception_type"]]}
        return self._open(case, subjects, actor_id, note)

    def _refusal(self, case: dict, action: str, role: str, actor_id: str, reason_code: str | None,
                 note: str | None) -> tuple[str, str] | None:
        """The rule an action breaks, if any: (block reason, message)."""
        if action == "NOTE":
            if role not in OPENERS:
                return "ROLE_NOT_ALLOWED", f"{role} can't add case notes"
            return None if note else ("NOTE_REQUIRED", "a note needs text")
        starts, _, roles, needs_reason = ACTIONS[action]
        status = case["current_status"]
        if role not in roles:
            return "ROLE_NOT_ALLOWED", f"{role} can't {action.lower().replace('_', ' ')} a case"
        if status not in starts:
            return "INVALID_TRANSITION", f"can't {action.lower().replace('_', ' ')} a case that is {status}"
        if needs_reason and reason_code not in REASONS[action]:
            return "REASON_REQUIRED", f"{action.lower()} needs one of: {', '.join(REASONS[action])}"
        if action == "CONFIRM" and actor_id == case["opened_by"]:
            return "FOUR_EYES_BLOCKED", f"{actor_id} opened this case, so a second reviewer must confirm it"
        if action in ("CONFIRM", "CLEAR") and case["priority"] == "CRITICAL" and status != "ESCALATED":
            return "ESCALATION_REQUIRED", "a CRITICAL case must be escalated before it can close"
        if action == "CLEAR" and role == "OPS_ANALYST" and (case["priority"] in ("HIGH", "CRITICAL") or status == "ESCALATED"):
            return "ANALYST_LIMIT", "analysts can clear only LOW or MEDIUM cases that are not escalated"
        return None

    def act(self, investigation_id: str, action: str, actor_id: str, reason_code: str | None = None,
            note: str | None = None) -> Outcome:
        """Apply an action. A refused action is recorded as a BLOCKED event and reported, never silently dropped."""
        if action not in ACTIONS and action != "NOTE":
            raise WorkflowError("UNKNOWN_ACTION", f"unknown action {action}")
        role = self._staff(actor_id)
        case = self.case(investigation_id)
        status = case["current_status"]
        refusal = self._refusal(case, action, role, actor_id, reason_code, note)
        with self.db:
            if role not in OPENERS and refusal:  # A system administrator leaves no case events at all.
                raise WorkflowError(*refusal)
            if refusal:
                code, message = refusal
                event_id = self._append(investigation_id, "BLOCKED", status, status, actor_id, code,
                                        f"Refused {action}: {message}." + (f" Note: {note}" if note else ""))
                return Outcome(False, event_id, status, message)
            to_status = status if action == "NOTE" else ACTIONS[action][1]
            event_id = self._append(investigation_id, action, status, to_status, actor_id, reason_code, note)
        return Outcome(True, event_id, to_status, f"{action} recorded: {status} -> {to_status}")


def export_history(workflow: Workflow) -> dict:
    """Every case and event, for download: live cases on the hosted app can reset when it restarts (D-018)."""
    cases = workflow.cases()
    return {"cases": cases, "events": workflow.history(),
            "subjects": {case["investigation_id"]: workflow.subjects(case["investigation_id"]) for case in cases},
            "chains": {case["investigation_id"]: workflow.verify_chain(case["investigation_id"]) for case in cases}}
