"""Helpers for the Cases page: database access through the investigation workflow, and the hash strand.

All writes go through `fraudnet.investigate.workflow.Workflow`, so the page enforces exactly the same
rules as the command line: roles, four-eyes, escalation, the analyst limit and BLOCKED records.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fraudnet.app import theme
from fraudnet.investigate.workflow import ACTIONS, REASONS, STAFF, Workflow

STATUSES = ("OPEN", "IN_REVIEW", "ESCALATED", "CLOSED_CONFIRMED", "CLOSED_CLEARED")
STATUS_COLOUR = {"OPEN": "#5BC6E8", "IN_REVIEW": "#E9EDF3", "ESCALATED": "#EED9A4",
                 "CLOSED_CONFIRMED": "#F4A62A", "CLOSED_CLEARED": "#7FE0B5"}
STATUS_LABEL = {"OPEN": "Open", "IN_REVIEW": "In review", "ESCALATED": "Escalated",
                "CLOSED_CONFIRMED": "Closed: fraud confirmed", "CLOSED_CLEARED": "Closed: cleared"}
ACTION_LABEL = {"START_REVIEW": "Start review", "ESCALATE": "Escalate", "CONFIRM": "Confirm fraud",
                "CLEAR": "Clear", "REOPEN": "Reopen", "NOTE": "Add a note"}
ROLE_LABEL = {"OPS_ANALYST": "Operations analyst", "RISK_REVIEWER": "Risk reviewer", "SYS_ADMIN": "System administrator"}
ROLE_CAN = {"OPS_ANALYST": "opens cases, reviews, escalates, clears LOW or MEDIUM cases",
            "RISK_REVIEWER": "confirms or clears fraud, reopens cases, never on a case they opened",
            "SYS_ADMIN": "runs the system, makes no case decisions"}


def needs_reason(action: str) -> bool:
    return action in ACTIONS and ACTIONS[action][3]


def reasons(action: str) -> tuple[str, ...]:
    return REASONS.get(action, ())


def plain(code: str | None) -> str:
    return "" if not code else code.replace("_", " ").capitalize()


@contextmanager
def workflow(folder: Path):
    connection = sqlite3.connect(Path(folder) / "fraudnet.db")
    try:
        yield Workflow(connection)
    finally:
        connection.close()


REFUSAL_PLAIN = {"ROLE_NOT_ALLOWED": "your role can't do this", "INVALID_TRANSITION": "not possible from this status",
                 "FOUR_EYES_BLOCKED": "you opened this case, so a second reviewer must confirm it",
                 "ESCALATION_REQUIRED": "a critical case must be escalated first",
                 "ANALYST_LIMIT": "analysts can clear only low or medium cases",
                 "REASON_REQUIRED": "choose a reason first", "NOTE_REQUIRED": "write a note first"}


def preview(flow: Workflow, case: dict, action: str, actor_id: str, reason_code: str | None, note: str | None) -> tuple[bool, str, str]:
    """What would happen, before anything is written: (allowed, headline, what pressing does).
    Uses the workflow's own rule check, so the preview always matches the outcome."""
    role = STAFF[actor_id][0]
    refusal = flow._refusal(case, action, role, actor_id, reason_code, note)
    if refusal is None:
        target = case["current_status"] if action == "NOTE" else ACTIONS[action][1]
        moves = "adds a note" if action == "NOTE" else f"{STATUS_LABEL[case['current_status']]} → {STATUS_LABEL[target]}"
        return True, f"Allowed · {moves}", "Pressing it adds a sealed event to the history."
    code, _ = refusal
    if role == "SYS_ADMIN":
        return False, f"Refused · {REFUSAL_PLAIN[code]}", "Administrators leave no case events: nothing is recorded."
    return False, f"Refused · {REFUSAL_PLAIN[code]}", f"Pressing it records the refusal ({code}) in the history."


def exception_sentence(flow: Workflow, exception_id: str) -> str:
    """One plain sentence for a data-exception case."""
    row = flow.db.execute("SELECT exception_type, entity_id, observed_value FROM data_exception WHERE exception_id = ?",
                          (exception_id,)).fetchone()
    if row is None:
        return f"Data exception {exception_id}."
    kind, entity, observed = row
    if kind == "ORPHAN_POLICY_REF":
        return f"Claim {entity} names policy {observed}, which does not exist. Hold the payment until it is checked."
    if kind == "PAYMENT_OVER_APPROVED":
        try:
            amount = f"${int(observed) / 100:,.2f}"
        except ValueError:
            amount = observed
        return f"Claim {entity} was paid {amount}, more than its approved amount. Review the payment."
    return f"Invoice {entity} appears on claims of different claimants. Investigate the billing."


def names(folder: Path) -> dict[str, str]:
    with sqlite3.connect(Path(folder) / "fraudnet.db") as connection:
        try:
            return dict(connection.execute("SELECT claimant_id, full_name FROM claimant").fetchall())
        except sqlite3.OperationalError:
            return {}


def open_exceptions(flow: Workflow) -> list[dict]:
    """Data exceptions without an active case."""
    try:
        rows = flow.db.execute(
            "SELECT exception_id, exception_type, severity, entity_type, entity_id, field_name, observed_value, expected_rule "
            "FROM data_exception WHERE exception_id NOT IN (SELECT exception_id FROM investigation WHERE exception_id IS NOT NULL "
            "AND current_status NOT IN ('CLOSED_CONFIRMED', 'CLOSED_CLEARED')) ORDER BY exception_id").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def open_networks(flow: Workflow) -> list[dict]:
    """Flagged networks without an active case, highest score first."""
    try:
        rows = flow.db.execute(
            "SELECT network_id, priority, score, member_count FROM network WHERE flagged = 1 AND network_id NOT IN "
            "(SELECT network_id FROM investigation WHERE network_id IS NOT NULL AND current_status NOT IN "
            "('CLOSED_CONFIRMED', 'CLOSED_CLEARED')) ORDER BY rank").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


EVENT_LABEL = {"OPEN": "Opened", "START_REVIEW": "Review started", "ESCALATE": "Escalated", "CONFIRM": "Fraud confirmed",
               "CLEAR": "Cleared", "REOPEN": "Reopened", "NOTE": "Note", "BLOCKED": "Refused"}


def history_rows(events: list[dict]) -> str:
    """The history as a tidy vertical list: one row per event, its hash on the right."""
    rows = []
    for event in events:
        blocked = event["action"] == "BLOCKED"
        colour = "#FF9A66" if blocked else STATUS_COLOUR.get(event["to_status"], theme.CYAN)
        title = EVENT_LABEL.get(event["action"], event["action"])
        detail = event["note"] if event["note"] else plain(event["reason_code"])
        if blocked:
            detail = f"{event['reason_code']} · {event['note']}" if event["note"] else event["reason_code"]
        when = event["event_at"][5:16].replace("T", " ")
        rows.append(f"""
<div style="display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 10px 0;
            border-top: 1px solid #1E2632">
  <div style="width: 26px; height: 26px; border-radius: 50%; border: 2px solid {colour}; display: flex; align-items: center;
              justify-content: center"><span class="fn-mono" style="font-size: 11px; font-weight: 600; color: {colour}">{event['seq']}</span></div>
  <div style="min-width: 0">
    <div style="font-size: 14px; font-weight: 600; color: {colour if blocked else theme.TEXT}">{theme.esc(title)}
      <span style="font-weight: 400; font-size: 12.5px; color: {theme.FAINT}"> · {theme.esc(event['actor_id'])} · {theme.esc(when)}</span></div>
    {f'<div style="font-size: 12.5px; color: {theme.MUTED}; margin-top: 2px">{theme.esc(detail)}</div>' if detail else ''}
  </div>
  <span class="fn-mono" style="font-size: 11.5px; color: {theme.FAINT}">#{theme.esc(event['event_hash'][:8])}</span>
</div>""")
    return "".join(rows)
