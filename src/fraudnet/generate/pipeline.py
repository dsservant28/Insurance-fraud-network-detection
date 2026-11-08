"""Run the generator stages in a fixed order with one seeded random generator."""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.edges import build_graph
from fraudnet.generate.finalize import finalize
from fraudnet.generate.ground_truth import build_labels
from fraudnet.generate.lifecycle import build_lifecycle
from fraudnet.generate.master import build_master
from fraudnet.generate.plant import OVERPAID_CLAIMS, add_group, plan_planting
from fraudnet.generate.transactions import build_transaction_source


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _planted(table: pd.DataFrame, key: str, ids: dict[int, str]) -> dict[str, int]:
    rows = table[table["plan_group"].notna()]
    return {ids[int(value)]: int(group) for value, group in zip(rows[key], rows["plan_group"])}


def generate_with_labels(config: GeneratorConfig) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return the input tables and, separately, the hidden labels."""
    rng = np.random.default_rng(config.seed)
    master = build_master(config, rng)
    plan = plan_planting(config, rng, master)
    source = build_transaction_source(config, rng, master, plan)
    derived = build_lifecycle(rng, master, source, max(1, round(OVERPAID_CLAIMS * config.scale)))
    tables, ids = finalize(master, derived, rng)

    planted_rows = {"CLAIM": _planted(derived.claim, "claim_key", ids["claim"]),
                    "INVOICE": _planted(derived.invoice, "invoice_key", ids["invoice"]),
                    "PAYMENT": {}}
    claims = derived.claim.set_index("claim_key")
    for claim_key, payment_key in derived.overpayments:
        row = claims.loc[claim_key]
        group = add_group(plan, "EC-2", f"Claim {{claims}} was paid {_dollars(row['paid_amount_cents'])} against "
                                        f"an approved {_dollars(row['approved_amount_cents'])}: payment {{payments}} "
                                        f"repeats an earlier settled payment for the same invoice.")
        planted_rows["CLAIM"][ids["claim"][claim_key]] = group.group_no
        planted_rows["PAYMENT"][ids["payment"][payment_key]] = group.group_no
    labels = build_labels(plan, planted_rows, ids)

    hidden = labels[(labels["issue_type"] == "EC-4") & (labels["entity_type"] == "CLAIMANT")]
    hidden_pairs = {frozenset(pair) for _, ring in hidden.groupby("ring_id")
                    for pair in combinations(ring["entity_id"], 2)}
    tables["graph_node"], tables["relationship_edge"] = build_graph(tables, hidden_pairs)
    return tables, labels


def generate(config: GeneratorConfig) -> dict[str, pd.DataFrame]:
    return generate_with_labels(config)[0]
