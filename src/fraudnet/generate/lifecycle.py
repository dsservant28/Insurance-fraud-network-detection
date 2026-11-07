"""Calculate amounts, payments, events and statuses from source rows.

Formulas and conditional rules are defined in docs/DATA_DICTIONARY.md section 7. Random draws here
only choose realistic delays and payment outcomes. Every amount and status is computed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from fraudnet.generate.config import AS_OF_DATE
from fraudnet.generate.master import OPS_ANALYST_IDS, MasterTables
from fraudnet.generate.transactions import INCIDENT_TYPES_BY_POLICY, SourceTables

PAYMENT_FAILURE_RATE = 0.03
PAYMENT_REVERSAL_RATE = 0.015
CLAIMANT_PAYEE_RATE = 0.15


@dataclass
class DerivedTables:
    incident: pd.DataFrame
    claim: pd.DataFrame
    claim_provider: pd.DataFrame
    invoice: pd.DataFrame
    invoice_line: pd.DataFrame
    payment: pd.DataFrame
    claim_events: pd.DataFrame
    invoice_events: pd.DataFrame
    payment_events: pd.DataFrame


class _EventLog:
    """Builds one parent's event sequence. Events after the as-of date have not happened yet."""

    def __init__(self, rng: np.random.Generator, rows: list[dict], parent_field: str, parent_key: int) -> None:
        self.rng, self.rows, self.parent_field, self.parent_key = rng, rows, parent_field, parent_key
        self.status: str | None = None
        self.seq = 0
        self.last_day: date | None = None

    def add(self, status: str, day: date, role: str = "SYSTEM", reason: str | None = None) -> bool:
        if day > AS_OF_DATE:
            return False
        if self.last_day is not None and day <= self.last_day:
            raise ValueError(f"event order broken for {self.parent_field} {self.parent_key}")
        self.seq += 1
        actor = None
        if role == "OPS_ANALYST":
            actor = OPS_ANALYST_IDS[int(self.rng.integers(len(OPS_ANALYST_IDS)))]
        self.rows.append({
            self.parent_field: self.parent_key,
            "seq": self.seq,
            "from_status": self.status,
            "to_status": status,
            "event_at": (f"{day.isoformat()}T{int(self.rng.integers(8, 18)):02d}:"
                         f"{int(self.rng.integers(60)):02d}:{int(self.rng.integers(60)):02d}Z"),
            "actor_role": role,
            "actor_id": actor,
            "reason_code": reason,
        })
        self.status, self.last_day = status, day
        return True


def _after(rng: np.random.Generator, day: date, low: int, high: int) -> date:
    return day + timedelta(days=int(rng.integers(low, high + 1)))


def policy_status_on(events: list[dict], day: date) -> str | None:
    """Return a policy's status on a date from its event history."""
    status = None
    for event in sorted(events, key=lambda row: row["seq"]):
        if event["event_at"][:10] <= day.isoformat():
            status = event["to_status"]
    return status


def allocate(approved_cents: int, covered_by_invoice: list[int]) -> list[int]:
    """Split the approved amount by covered amount. The last invoice takes the rounding remainder."""
    total = sum(covered_by_invoice)
    shares = [approved_cents * covered // total for covered in covered_by_invoice[:-1]]
    return shares + [approved_cents - sum(shares)]


def denial_reason(claim: dict, policy: dict, incident: dict, policy_events: list[dict], covered_cents: int) -> str | None:
    """Apply the conditional rules in a fixed order. Returns None when the claim can be approved."""
    day = incident["incident_date"]
    if incident["incident_type"] not in INCIDENT_TYPES_BY_POLICY[policy["policy_type"]][0]:
        return "TYPE_NOT_COVERED"
    if not policy["effective_from"] <= day <= policy["effective_to"]:
        return "OUTSIDE_COVERAGE"
    if policy_status_on(policy_events, day) != "ACTIVE":
        return "POLICY_NOT_ACTIVE"
    if claim["plan_manual_denial"]:
        return "INSUFFICIENT_EVIDENCE"
    if covered_cents <= policy["deductible_cents"]:
        return "BELOW_DEDUCTIBLE"
    return None


def _pay_invoice(rng, invoice: dict, amount: int, decision_day: date, payee: dict, payments: list[dict],
                 payment_events: list[dict], invoice_log: _EventLog) -> date | None:
    """Create payment rows for one invoice. Returns the settled day, if the money stayed paid."""
    day = _after(rng, decision_day, 1, 10)
    while day <= AS_OF_DATE:
        key = len(payments)
        log = _EventLog(rng, payment_events, "payment_key", key)
        payments.append({
            "payment_key": key,
            "claim_key": invoice["claim_key"],
            "invoice_key": invoice["invoice_key"],
            **payee,
            "amount_cents": amount,
            "payment_date": day,
        })
        log.add("INITIATED", day)
        outcome_day = _after(rng, day, 1, 3)
        if rng.random() < PAYMENT_FAILURE_RATE:
            if not log.add("FAILED", outcome_day, reason="BANK_REJECTED"):
                payments[-1]["current_status"] = log.status
                return None
            payments[-1]["current_status"] = log.status
            day = _after(rng, outcome_day, 2, 5)  # The failed row stays; a retry is a new row.
            continue
        if not log.add("SETTLED", outcome_day):
            payments[-1]["current_status"] = log.status
            return None
        if rng.random() < PAYMENT_REVERSAL_RATE and log.add("REVERSED", _after(rng, outcome_day, 3, 20),
                                                            reason="BANK_RECALL"):
            payments[-1]["current_status"] = log.status
            return None
        payments[-1]["current_status"] = log.status
        invoice_log.add("PAID", outcome_day)
        return outcome_day
    return None


def _payee(rng, claim: dict, provider: dict, claimant_bank: dict[int, str]) -> dict:
    bank = claimant_bank.get(claim["claimant_key"])
    if bank is not None and rng.random() < CLAIMANT_PAYEE_RATE:
        return {"payee_type": "CLAIMANT", "payee_claimant_key": claim["claimant_key"],
                "payee_provider_key": None, "payee_bank_token": bank}
    return {"payee_type": "PROVIDER", "payee_claimant_key": None,
            "payee_provider_key": provider["provider_key"], "payee_bank_token": provider["bank_token"]}


def build_lifecycle(rng: np.random.Generator, master: MasterTables, source: SourceTables) -> DerivedTables:
    policies = {row["policy_key"]: row for row in master.policy.to_dict("records")}
    providers = {row["provider_key"]: row for row in master.provider.to_dict("records")}
    incidents = {row["incident_key"]: row for row in source.incident}
    claimant_bank = {row["claimant_key"]: row["bank_token"]
                     for row in master.claimant_contact.to_dict("records") if not pd.isna(row["bank_token"])}
    policy_events: dict[int, list[dict]] = {}
    for row in master.policy_events.to_dict("records"):
        policy_events.setdefault(row["policy_key"], []).append(row)

    lines = [{**line, "line_amount_cents": line["quantity"] * line["unit_price_cents"]} for line in source.invoice_line]
    invoices = [dict(row) for row in source.invoice]
    invoices_by_claim: dict[int, list[dict]] = {}
    for invoice in invoices:
        invoice["total_cents"] = 0
        invoice["covered_cents"] = 0
        invoices_by_claim.setdefault(invoice["claim_key"], []).append(invoice)
    invoices_by_key = {row["invoice_key"]: row for row in invoices}
    for line in lines:
        invoice = invoices_by_key[line["invoice_key"]]
        invoice["total_cents"] += line["line_amount_cents"]
        invoice["covered_cents"] += line["line_amount_cents"] * line["is_covered"]

    claims, payments = [], []
    claim_event_rows, invoice_event_rows, payment_event_rows = [], [], []

    for source_claim in source.claim:
        claim = dict(source_claim)
        incident = incidents[claim["incident_key"]]
        policy = policies[claim["policy_key"]]
        claim_invoices = sorted(invoices_by_claim.get(claim["claim_key"], []),
                                key=lambda row: (row["invoice_date"], row["invoice_key"]))

        approved = 0
        claim_log = _EventLog(rng, claim_event_rows, "claim_key", claim["claim_key"])
        claim_log.add("SUBMITTED", claim["reported_date"], "CUSTOMER")
        review_day = _after(rng, claim["reported_date"], 1, 5)

        withdraw_day = _after(rng, claim["reported_date"], 1, 20) if claim["plan_withdraw"] else None
        withdrawn = False
        if withdraw_day is not None and withdraw_day <= AS_OF_DATE:
            if review_day < withdraw_day:
                claim_log.add("UNDER_REVIEW", review_day, "OPS_ANALYST")
            withdrawn = claim_log.add("WITHDRAWN", withdraw_day, "CUSTOMER", "CUSTOMER_REQUEST")
        else:
            claim_log.add("UNDER_REVIEW", review_day, "OPS_ANALYST")

        # Verify each invoice. No covered amount, or a failed check, rejects that invoice only.
        logs, active, latest = {}, [], max(review_day, withdraw_day or review_day)
        for invoice in claim_invoices:
            log = _EventLog(rng, invoice_event_rows, "invoice_key", invoice["invoice_key"])
            logs[invoice["invoice_key"]] = log
            log.add("RECEIVED", invoice["invoice_date"])
            verify_day = _after(rng, invoice["invoice_date"], 1, 5)
            latest = max(latest, verify_day)
            if invoice["covered_cents"] == 0:
                log.add("REJECTED", verify_day, "OPS_ANALYST", "NOT_COVERED")
            elif invoice["plan_reject"]:
                log.add("REJECTED", verify_day, "OPS_ANALYST", "FAILED_VERIFICATION")
            elif log.add("VERIFIED", verify_day, "OPS_ANALYST"):
                active.append(invoice)

        decision_day = _after(rng, latest, 1, 14)
        if withdrawn:
            for invoice in claim_invoices:
                log = logs[invoice["invoice_key"]]
                if log.status in {"RECEIVED", "VERIFIED"}:
                    log.add("REJECTED", decision_day, "OPS_ANALYST", "CLAIM_WITHDRAWN")
            claim_log.add("CLOSED", _after(rng, max(withdraw_day, decision_day), 1, 30), "SYSTEM", "WITHDRAWN")
        elif decision_day <= AS_OF_DATE and all(logs[i["invoice_key"]].status != "RECEIVED" for i in claim_invoices):
            covered_total = sum(invoice["covered_cents"] for invoice in active)
            reason = denial_reason(claim, policy, incident, policy_events[claim["policy_key"]], covered_total)
            if reason is not None:
                claim_log.add("DENIED", decision_day, "OPS_ANALYST", reason)
                for invoice in active:
                    logs[invoice["invoice_key"]].add("REJECTED", decision_day, "OPS_ANALYST", "CLAIM_DENIED")
                claim_log.add("CLOSED", _after(rng, decision_day, 1, 30), "SYSTEM", "DENIED_FINAL")
            else:
                approved = min(covered_total, policy["coverage_limit_cents"]) - policy["deductible_cents"]
                claim_log.add("APPROVED", decision_day, "OPS_ANALYST")
                shares = allocate(approved, [invoice["covered_cents"] for invoice in active])
                settled_days, all_settled = [], True
                for invoice, share in zip(active, shares):
                    log = logs[invoice["invoice_key"]]
                    log.add("APPROVED", decision_day, "OPS_ANALYST")
                    if share == 0:
                        continue
                    payee = _payee(rng, claim, providers[invoice["provider_key"]], claimant_bank)
                    settled = _pay_invoice(rng, invoice, share, decision_day, payee, payments, payment_event_rows, log)
                    all_settled = all_settled and settled is not None
                    if settled is not None:
                        settled_days.append(settled)
                if all_settled and settled_days:
                    paid_day = _after(rng, max(settled_days), 1, 3)
                    if claim_log.add("PAID", paid_day):
                        claim_log.add("CLOSED", _after(rng, paid_day, 1, 30), "SYSTEM", "SETTLED")

        claim["approved_amount_cents"] = approved
        claim["current_status"] = claim_log.status
        claims.append(claim)
        for invoice in claim_invoices:
            invoice["current_status"] = logs[invoice["invoice_key"]].status

    paid_by_claim: dict[int, int] = {}
    for payment in payments:
        if payment["current_status"] == "SETTLED":
            paid_by_claim[payment["claim_key"]] = paid_by_claim.get(payment["claim_key"], 0) + payment["amount_cents"]

    for claim in claims:
        incident = incidents[claim["incident_key"]]
        policy = policies[claim["policy_key"]]
        claim_invoices = invoices_by_claim.get(claim["claim_key"], [])
        claim["claimed_amount_cents"] = sum(invoice["total_cents"] for invoice in claim_invoices)
        claim["paid_amount_cents"] = paid_by_claim.get(claim["claim_key"], 0)
        claim["balance_cents"] = claim["approved_amount_cents"] - claim["paid_amount_cents"]
        claim["days_incident_to_report"] = (claim["reported_date"] - incident["incident_date"]).days
        claim["days_policy_start_to_incident"] = (incident["incident_date"] - policy["effective_from"]).days

    return DerivedTables(
        incident=pd.DataFrame(source.incident),
        claim=pd.DataFrame(claims),
        claim_provider=pd.DataFrame(source.claim_provider),
        invoice=pd.DataFrame(invoices),
        invoice_line=pd.DataFrame(lines),
        payment=pd.DataFrame(payments),
        claim_events=pd.DataFrame(claim_event_rows),
        invoice_events=pd.DataFrame(invoice_event_rows),
        payment_events=pd.DataFrame(payment_event_rows),
    )
