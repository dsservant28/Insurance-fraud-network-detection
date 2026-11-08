"""Claim- and invoice-level facts (ARCHITECTURE.md section 3.2).

They describe single records. Network scoring uses them as support, but they never create a
network on their own.
"""
from __future__ import annotations

import pandas as pd


def claim_facts(tables: dict[str, pd.DataFrame], settings: dict) -> pd.DataFrame:
    """One row per claim with its dates, its provider count, and whether it came soon after policy start."""
    claims = tables["claim"].merge(tables["incident"][["incident_id", "incident_type", "incident_date"]],
                                   on="incident_id")
    gap = claims["days_policy_start_to_incident"]
    claims["early_claim"] = (gap.notna() & (gap >= 0) & (gap <= settings["links"]["early_claim_max_days"])).astype(bool)
    columns = ["claim_id", "claimant_id", "incident_id", "incident_type", "incident_date", "reported_date",
               "policy_id", "days_policy_start_to_incident", "days_incident_to_report", "claimed_amount_cents",
               "early_claim"]
    return claims[columns].sort_values("claim_id", ignore_index=True)


def invoice_facts(tables: dict[str, pd.DataFrame], settings: dict) -> pd.DataFrame:
    """One row per invoice with its total against the median of its peers.

    Peers are invoices for the same incident type from the same type of provider, so a repair bill
    is compared with other repair bills for the same kind of incident.
    """
    invoices = (tables["invoice"]
                .merge(tables["provider"][["provider_id", "provider_type"]], on="provider_id")
                .merge(tables["claim"][["claim_id", "claimant_id", "incident_id"]], on="claim_id")
                .merge(tables["incident"][["incident_id", "incident_type"]], on="incident_id"))
    peers = invoices.groupby(["incident_type", "provider_type"])["total_cents"]
    invoices["peer_median_cents"] = peers.transform(lambda totals: totals.astype(float).median())
    invoices["peer_count"] = peers.transform("size").astype(int)
    invoices["amount_ratio"] = (invoices["total_cents"].astype(float) / invoices["peer_median_cents"]).round(4)
    invoices["inflated"] = invoices["amount_ratio"] >= settings["indicators"]["inflated_ratio"]
    columns = ["invoice_id", "claim_id", "claimant_id", "provider_id", "provider_type", "incident_type",
               "external_invoice_no", "invoice_date", "total_cents", "peer_median_cents", "peer_count",
               "amount_ratio", "inflated"]
    return invoices[columns].sort_values("invoice_id", ignore_index=True)
