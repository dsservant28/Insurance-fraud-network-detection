"""Replace temporary keys with final immutable IDs and calculate derived statuses."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fraudnet.generate.ids import make_id, make_invoice_id
from fraudnet.generate.lifecycle import DerivedTables
from fraudnet.generate.master import MasterTables


def _ids_by_date(table: pd.DataFrame, key: str, date_column: str, entity: str,
                 rng: np.random.Generator) -> dict[int, str]:
    """Number rows in date order, as real systems do. Same-day ties are broken at random."""
    ordered = table.assign(_tie=rng.permutation(len(table))).sort_values([date_column, "_tie"])
    return {int(value): make_id(entity, number) for number, value in enumerate(ordered[key], start=1)}


def _invoice_ids(invoice: pd.DataFrame, provider_ids: dict[int, str], rng: np.random.Generator) -> dict[int, str]:
    """Each provider has its own counter, in invoice date order."""
    ordered = invoice.assign(
        _provider=invoice["provider_key"].map(provider_ids),
        _tie=rng.permutation(len(invoice)),
    ).sort_values(["_provider", "invoice_date", "_tie"])
    result, counters = {}, {}
    for key, provider_id in zip(ordered["invoice_key"], ordered["_provider"]):
        counters[provider_id] = counters.get(provider_id, 0) + 1
        result[int(key)] = make_invoice_id(provider_id, counters[provider_id])
    return result


def _nullable_map(values: pd.Series, mapping: dict[int, str]) -> list[str | None]:
    return [None if pd.isna(value) else mapping[int(value)] for value in values]


def _shuffled_ids(keys: pd.Series, entity: str, rng: np.random.Generator) -> dict[int, str]:
    """Map keys to IDs in a seeded random order, so ID numbers carry no information."""
    numbers = rng.permutation(len(keys)) + 1
    return {int(key): make_id(entity, int(number)) for key, number in zip(keys, numbers)}


def _dates_to_text(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    for column in table.columns:
        if column in {"date_of_birth", "customer_since", "effective_from", "effective_to", "active_from",
                      "active_to", "incident_date", "reported_date", "assigned_date", "invoice_date",
                      "payment_date"}:
            table[column] = [value.isoformat() if value is not None and not pd.isna(value) else None
                             for value in table[column]]
    return table


def _latest_status(events: pd.DataFrame, parent: str) -> pd.Series:
    """Current status is always the status in the highest-numbered event for each parent."""
    return events.sort_values([parent, "seq"]).groupby(parent)["to_status"].last()


def _finalize_events(events: pd.DataFrame, parent_key: str, parent_id: str, ids: dict[int, str],
                     entity: str) -> pd.DataFrame:
    table = events.assign(**{parent_id: events[parent_key].map(ids)}).sort_values([parent_id, "seq"], ignore_index=True)
    table.insert(0, "event_id", [make_id(entity, number) for number in range(1, len(table) + 1)])
    return table[["event_id", parent_id, "seq", "from_status", "to_status", "event_at",
                  "actor_role", "actor_id", "reason_code"]]


def finalize(master: MasterTables, derived: DerivedTables,
             rng: np.random.Generator) -> tuple[dict[str, pd.DataFrame], dict[str, dict[int, str]]]:
    """Assign every final ID. Returns the exported tables and the key-to-ID maps used for labels."""
    claimant_ids = _shuffled_ids(master.claimant["claimant_key"], "claimant", rng)
    provider_ids = _shuffled_ids(master.provider["provider_key"], "provider", rng)
    policy_ids = _shuffled_ids(master.policy["policy_key"], "policy", rng)

    claimant = master.claimant.assign(claimant_id=master.claimant["claimant_key"].map(claimant_ids))
    claimant = claimant[["claimant_id", "full_name", "date_of_birth", "customer_since"]]

    contact = master.claimant_contact.assign(
        claimant_id=master.claimant_contact["claimant_key"].map(claimant_ids)
    ).sort_values(["claimant_id", "effective_from"], ignore_index=True)
    contact.insert(0, "contact_id", [make_id("contact", n) for n in range(1, len(contact) + 1)])
    contact = contact[["contact_id", "claimant_id", "effective_from", "effective_to", "address_line",
                       "city", "postal_code", "phone", "email", "bank_token"]]

    provider = master.provider.assign(provider_id=master.provider["provider_key"].map(provider_ids))
    provider = provider[["provider_id", "provider_name", "provider_type", "address_line", "city",
                         "postal_code", "phone", "email", "bank_token", "active_from", "active_to"]]

    events = master.policy_events.assign(policy_id=master.policy_events["policy_key"].map(policy_ids))
    events = events.sort_values(["policy_id", "seq"], ignore_index=True)
    events.insert(0, "event_id", [make_id("policy_event", n) for n in range(1, len(events) + 1)])
    events = events[["event_id", "policy_id", "seq", "from_status", "to_status", "event_at",
                     "actor_role", "actor_id", "reason_code"]]

    policy = master.policy.assign(policy_id=master.policy["policy_key"].map(policy_ids))
    policy["current_status"] = policy["policy_id"].map(_latest_status(events, "policy_id"))
    policy = policy[["policy_id", "policy_type", "effective_from", "effective_to",
                     "coverage_limit_cents", "deductible_cents", "current_status"]]

    bridge = master.claimant_policy.assign(
        claimant_id=master.claimant_policy["claimant_key"].map(claimant_ids),
        policy_id=master.claimant_policy["policy_key"].map(policy_ids),
    )
    bridge = bridge[["claimant_id", "policy_id", "role", "effective_from", "effective_to"]]

    incident_ids = _ids_by_date(derived.incident, "incident_key", "incident_date", "incident", rng)
    claim_ids = _ids_by_date(derived.claim, "claim_key", "reported_date", "claim", rng)
    invoice_ids = _invoice_ids(derived.invoice, provider_ids, rng)
    payment_ids = _ids_by_date(derived.payment, "payment_key", "payment_date", "payment", rng)

    incident = derived.incident.assign(incident_id=derived.incident["incident_key"].map(incident_ids))
    incident = incident[["incident_id", "incident_type", "incident_date", "city", "postal_code",
                         "narrative", "vehicle_ref"]]

    # policy_id is derived: it holds policy_ref only when that policy really exists.
    # EC-1 claims have no policy key; their policy_ref is the number the claimant submitted.
    claim = derived.claim.assign(
        claim_id=derived.claim["claim_key"].map(claim_ids),
        incident_id=derived.claim["incident_key"].map(incident_ids),
        claimant_id=derived.claim["claimant_key"].map(claimant_ids),
        policy_ref=[submitted if pd.isna(key) else policy_ids[int(key)]
                    for key, submitted in zip(derived.claim["policy_key"], derived.claim["plan_policy_ref"])],
        days_policy_start_to_incident=derived.claim["days_policy_start_to_incident"].astype("Int64"),
    )
    known_policies = set(policy_ids.values())
    claim["policy_id"] = [ref if ref in known_policies else None for ref in claim["policy_ref"]]
    claim = claim[["claim_id", "incident_id", "claimant_id", "policy_ref", "policy_id", "reported_date",
                   "claimed_amount_cents", "approved_amount_cents", "paid_amount_cents", "balance_cents",
                   "days_incident_to_report", "days_policy_start_to_incident", "current_status"]]

    claim_provider = derived.claim_provider.assign(
        claim_id=derived.claim_provider["claim_key"].map(claim_ids),
        provider_id=derived.claim_provider["provider_key"].map(provider_ids),
    )[["claim_id", "provider_id", "service_role", "assigned_date"]]

    invoice = derived.invoice.assign(
        invoice_id=derived.invoice["invoice_key"].map(invoice_ids),
        provider_id=derived.invoice["provider_key"].map(provider_ids),
        claim_id=derived.invoice["claim_key"].map(claim_ids),
    )[["invoice_id", "provider_id", "claim_id", "external_invoice_no", "invoice_date", "total_cents",
       "covered_cents", "current_status"]]

    invoice_line = derived.invoice_line.assign(
        invoice_id=derived.invoice_line["invoice_key"].map(invoice_ids),
    )[["invoice_id", "line_no", "service_code", "quantity", "unit_price_cents", "line_amount_cents", "is_covered"]]

    payment = derived.payment.assign(
        payment_id=derived.payment["payment_key"].map(payment_ids),
        claim_id=derived.payment["claim_key"].map(claim_ids),
        invoice_id=derived.payment["invoice_key"].map(invoice_ids),
        payee_claimant_id=_nullable_map(derived.payment["payee_claimant_key"], claimant_ids),
        payee_provider_id=_nullable_map(derived.payment["payee_provider_key"], provider_ids),
    )[["payment_id", "claim_id", "invoice_id", "payee_type", "payee_claimant_id", "payee_provider_id",
       "payee_bank_token", "amount_cents", "payment_date", "current_status"]]

    ids = {"claimant": claimant_ids, "provider": provider_ids, "claim": claim_ids, "invoice": invoice_ids,
           "payment": payment_ids}
    return {
        "incident": _dates_to_text(incident).sort_values("incident_id", ignore_index=True),
        "claim": _dates_to_text(claim).sort_values("claim_id", ignore_index=True),
        "claim_provider": _dates_to_text(claim_provider).sort_values(["claim_id", "provider_id", "service_role"],
                                                                     ignore_index=True),
        "invoice": _dates_to_text(invoice).sort_values("invoice_id", ignore_index=True),
        "invoice_line": invoice_line.sort_values(["invoice_id", "line_no"], ignore_index=True),
        "payment": _dates_to_text(payment).sort_values("payment_id", ignore_index=True),
        "claim_events": _finalize_events(derived.claim_events, "claim_key", "claim_id", claim_ids, "claim_event"),
        "invoice_events": _finalize_events(derived.invoice_events, "invoice_key", "invoice_id", invoice_ids,
                                           "invoice_event"),
        "payment_events": _finalize_events(derived.payment_events, "payment_key", "payment_id", payment_ids,
                                           "payment_event"),
        "claimant": _dates_to_text(claimant).sort_values("claimant_id", ignore_index=True),
        "claimant_contact": _dates_to_text(contact),
        "provider": _dates_to_text(provider).sort_values("provider_id", ignore_index=True),
        "policy": _dates_to_text(policy).sort_values("policy_id", ignore_index=True),
        "claimant_policy": _dates_to_text(bridge).sort_values(["claimant_id", "policy_id"], ignore_index=True),
        "policy_events": events,
    }, ids
