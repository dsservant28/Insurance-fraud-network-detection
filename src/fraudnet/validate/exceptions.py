"""Exception checks: facts found in the input data, reported without failing the run.

Rules: docs/DATA_DICTIONARY.md section 11.2. This module reads input tables only and carries no
fraud label. The evaluator later reconciles these rows with the hidden labels in both directions.
"""
from __future__ import annotations

import json

import pandas as pd

COLUMNS = ["exception_id", "exception_type", "severity", "entity_type", "entity_id", "field_name",
           "observed_value", "expected_rule", "detail_json"]


def _detail(**values) -> str:
    return json.dumps(values, sort_keys=True)


def _orphan_policy_refs(tables: dict[str, pd.DataFrame]) -> list[dict]:
    claim = tables["claim"]
    known = set(tables["policy"]["policy_id"])
    orphans = claim[~claim["policy_ref"].isin(known)]
    return [{
        "exception_type": "ORPHAN_POLICY_REF", "severity": "HIGH", "entity_type": "CLAIM",
        "entity_id": row.claim_id, "field_name": "policy_ref", "observed_value": row.policy_ref,
        "expected_rule": "policy_ref names an existing policy",
        "detail_json": _detail(claimant_id=row.claimant_id, claim_status=row.current_status),
    } for row in orphans.itertuples(index=False)]


def _payments_over_approved(tables: dict[str, pd.DataFrame]) -> list[dict]:
    claim = tables["claim"]
    over = claim[claim["paid_amount_cents"] > claim["approved_amount_cents"]]
    payment = tables["payment"]
    rows = []
    for row in over.itertuples(index=False):
        settled = payment[(payment["claim_id"] == row.claim_id) & (payment["current_status"] == "SETTLED")]
        rows.append({
            "exception_type": "PAYMENT_OVER_APPROVED", "severity": "HIGH", "entity_type": "CLAIM",
            "entity_id": row.claim_id, "field_name": "paid_amount_cents", "observed_value": str(row.paid_amount_cents),
            "expected_rule": "paid_amount_cents is not above approved_amount_cents",
            "detail_json": _detail(approved_amount_cents=int(row.approved_amount_cents),
                                   paid_amount_cents=int(row.paid_amount_cents),
                                   settled_payment_ids=sorted(settled["payment_id"])),
        })
    return rows


def _duplicate_invoices(tables: dict[str, pd.DataFrame]) -> list[dict]:
    """Same provider, external number, date and amount on claims of two or more claimants."""
    invoice = tables["invoice"].merge(tables["claim"][["claim_id", "claimant_id"]], on="claim_id")
    keys = ["provider_id", "external_invoice_no", "invoice_date", "total_cents"]
    rows = []
    for values, group in invoice.groupby(keys):
        if group["claimant_id"].nunique() < 2:
            continue
        for row in group.sort_values("invoice_id").itertuples(index=False):
            rows.append({
                "exception_type": "DUPLICATE_INVOICE", "severity": "HIGH", "entity_type": "INVOICE",
                "entity_id": row.invoice_id, "field_name": "external_invoice_no",
                "observed_value": row.external_invoice_no,
                "expected_rule": "one provider invoice is billed on one claimant's claim",
                "detail_json": _detail(provider_id=values[0], invoice_date=values[2], total_cents=int(values[3]),
                                       invoice_ids=sorted(group["invoice_id"]),
                                       claimant_ids=sorted(set(group["claimant_id"]))),
            })
    return rows


def find_exceptions(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return data_exception rows, sorted and numbered EXC-000001 onwards."""
    rows = _orphan_policy_refs(tables) + _payments_over_approved(tables) + _duplicate_invoices(tables)
    table = pd.DataFrame(rows, columns=COLUMNS[1:]).sort_values(["exception_type", "entity_id"], ignore_index=True)
    table.insert(0, "exception_id", [f"EXC-{number:06d}" for number in range(1, len(table) + 1)])
    return table
