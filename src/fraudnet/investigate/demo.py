"""A small, realistic case history for the demo app, made through the same rules as every user action.

Timestamps come from a fixed demo clock, so the seeded history is the same on every start.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fraudnet.investigate.workflow import Workflow

DEMO_START = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


class DemoClock:
    def __init__(self, start: datetime = DEMO_START, step: timedelta = timedelta(minutes=37)) -> None:
        self.now, self.step = start, step

    def __call__(self) -> str:
        self.now += self.step
        return self.now.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_demo(workflow: Workflow) -> list[str]:
    """Open and progress a few cases. Does nothing if any case already exists."""
    if workflow.cases():
        return []
    db = workflow.db
    flagged = [row["network_id"] for row in db.execute(
        "SELECT network_id FROM network WHERE flagged = 1 ORDER BY rank")]
    orphan = db.execute("SELECT exception_id FROM data_exception WHERE exception_type = 'ORPHAN_POLICY_REF' "
                        "ORDER BY exception_id LIMIT 1").fetchone()
    overpaid = db.execute("SELECT exception_id FROM data_exception WHERE exception_type = 'PAYMENT_OVER_APPROVED' "
                          "ORDER BY exception_id LIMIT 1").fetchone()
    opened = []
    if flagged:
        # The top network: worked by an analyst, escalated, then confirmed by a second reviewer.
        case = workflow.open_from_network(flagged[0], "USR-OPS-01", "Opened from the top of the ranked queue.")
        workflow.act(case, "START_REVIEW", "USR-OPS-01")
        workflow.act(case, "NOTE", "USR-OPS-01", note="Evidence links checked against the claim files.")
        workflow.act(case, "CONFIRM", "USR-OPS-01", "CONFIRMED_LINKS")  # refused: analysts can't confirm
        workflow.act(case, "ESCALATE", "USR-OPS-01", "NEEDS_SENIOR_REVIEW")
        workflow.act(case, "CONFIRM", "USR-RSK-01", "CONFIRMED_LINKS", "Links and timing reviewed; refer to SIU.")
        opened.append(case)
    if len(flagged) > 1:
        # Opened by a reviewer, who then can't confirm their own case: the four-eyes rule.
        case = workflow.open_from_network(flagged[1], "USR-RSK-01")
        workflow.act(case, "START_REVIEW", "USR-RSK-01")
        workflow.act(case, "CONFIRM", "USR-RSK-01", "CONFIRMED_LINKS")  # refused: four-eyes
        workflow.act(case, "NOTE", "USR-RSK-01", note="Waiting for a second reviewer.")
        opened.append(case)
    if orphan:
        case = workflow.open_from_exception(orphan["exception_id"], "USR-OPS-02", "Claim names a policy we don't hold.")
        workflow.act(case, "START_REVIEW", "USR-OPS-02")
        workflow.act(case, "NOTE", "USR-OPS-02", note="Payment held while the policy number is checked with the broker.")
        opened.append(case)
    if overpaid:
        opened.append(workflow.open_from_exception(overpaid["exception_id"], "USR-OPS-02"))
    if len(flagged) > 2:
        opened.append(workflow.open_from_network(flagged[2], "USR-OPS-01"))
    return opened
