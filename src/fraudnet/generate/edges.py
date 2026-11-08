"""Build graph_node and the recorded relationship_edge register from final input tables.

Edge types and rules: docs/DATA_DICTIONARY.md sections 3.8 and 5.3. Every edge is derived from
source rows and cites them in `source_ref`. The register is true but deliberately incomplete:
links inside each R-RING-06 ring are left out (EC-4), and the detector must find them itself.
"""
from __future__ import annotations

from itertools import combinations

import pandas as pd

from fraudnet.generate.pools import STREET_SUFFIXES

CLAIMANT_PAIR_TYPES = {"address": "SHARED_ADDRESS", "phone": "SHARED_PHONE", "email": "SHARED_EMAIL",
                       "bank_token": "SHARED_BANK"}
NODE_SOURCES = (("claimant", "claimant_id", "CLAIMANT"), ("policy", "policy_id", "POLICY"),
                ("incident", "incident_id", "INCIDENT"), ("provider", "provider_id", "PROVIDER"),
                ("payment", "payment_id", "PAYMENT"))
_FULL_SUFFIX = {short.lower(): full.lower() for full, short in STREET_SUFFIXES.items()}
_OPEN = "9999-12-31"


def normal_address(line: str, city: str, postal_code: str) -> str:
    """`12 Oak St` and `12 OAK STREET` in the same city and postal code are one address."""
    words = line.lower().split()
    words[-1] = _FULL_SUFFIX.get(words[-1], words[-1])
    return f"{' '.join(words)}|{city.lower()}|{postal_code}"


class _Register:
    def __init__(self) -> None:
        self.edges: dict[tuple[str, str, str], dict] = {}

    def add(self, source: str, target: str, edge_type: str, valid_from: str, valid_to, source_ref: str) -> None:
        """Keep one edge per (source, target, type), covering the widest period seen."""
        valid_to = None if pd.isna(valid_to) else valid_to
        key = (source, target, edge_type)
        if key not in self.edges:
            self.edges[key] = {"source_node_id": source, "target_node_id": target, "edge_type": edge_type,
                               "valid_from": valid_from, "valid_to": valid_to, "source_ref": source_ref}
            return
        edge = self.edges[key]
        edge["valid_from"] = min(edge["valid_from"], valid_from)
        if edge["valid_to"] is not None:
            edge["valid_to"] = None if valid_to is None else max(edge["valid_to"], valid_to)


def _shared_claimant_values(contact: pd.DataFrame, register: _Register, hidden_pairs: set[frozenset]) -> None:
    rows = contact.assign(address=[normal_address(*values) for values in
                                   zip(contact["address_line"], contact["city"], contact["postal_code"])])
    for field, edge_type in CLAIMANT_PAIR_TYPES.items():
        source_field = "address_line" if field == "address" else field
        for _, group in rows.dropna(subset=[field]).groupby(field):
            if group["claimant_id"].nunique() < 2:
                continue
            for a, b in combinations(group.to_dict("records"), 2):
                if a["claimant_id"] == b["claimant_id"]:
                    continue
                start = max(a["effective_from"], b["effective_from"])
                end = min(a["effective_to"] if not pd.isna(a["effective_to"]) else _OPEN,
                          b["effective_to"] if not pd.isna(b["effective_to"]) else _OPEN)
                if start > end:  # Different periods, such as a past tenant: no link.
                    continue
                if frozenset((a["claimant_id"], b["claimant_id"])) in hidden_pairs:
                    continue
                first, second = sorted((a, b), key=lambda row: row["claimant_id"])
                register.add(first["claimant_id"], second["claimant_id"], edge_type, start,
                             None if end == _OPEN else end,
                             f"claimant_contact:{first['contact_id']}.{source_field};"
                             f"claimant_contact:{second['contact_id']}.{source_field}")


def build_graph(tables: dict[str, pd.DataFrame], hidden_pairs: set[frozenset]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return graph_node and relationship_edge. `hidden_pairs` are claimant pairs whose links are left out."""
    nodes = pd.concat([pd.DataFrame({"node_id": tables[table][column], "node_type": node_type})
                       for table, column, node_type in NODE_SOURCES], ignore_index=True)
    nodes = nodes.sort_values("node_id", ignore_index=True)
    register = _Register()

    for row in tables["claimant_policy"].itertuples(index=False):
        register.add(row.claimant_id, row.policy_id, "HOLDS_POLICY", row.effective_from, row.effective_to,
                     f"claimant_policy:{row.claimant_id}|{row.policy_id}.role")

    used = tables["claim_provider"].merge(tables["claim"][["claim_id", "claimant_id"]], on="claim_id")
    for row in used.sort_values(["assigned_date", "claim_id"]).itertuples(index=False):
        register.add(row.claimant_id, row.provider_id, "USED_PROVIDER", row.assigned_date, None,
                     f"claim_provider:{row.claim_id}|{row.provider_id}.provider_id")

    parties = tables["claim"].merge(tables["incident"][["incident_id", "incident_date"]], on="incident_id")
    parties = parties[parties.groupby("incident_id")["claimant_id"].transform("nunique") > 1]
    for row in parties.sort_values("claim_id").itertuples(index=False):
        register.add(row.claimant_id, row.incident_id, "INCIDENT_PARTY", row.incident_date, None,
                     f"claim:{row.claim_id}.incident_id")

    contact = tables["claimant_contact"]
    _shared_claimant_values(contact, register, hidden_pairs)

    provider = tables["provider"]
    for field in ("phone", "email", "bank_token"):
        owners = provider.set_index(field)["provider_id"]
        for row in contact.dropna(subset=[field]).itertuples(index=False):
            value = getattr(row, field)
            if value in owners.index:
                register.add(row.claimant_id, owners[value], "SHARED_CONTACT_PROVIDER", row.effective_from,
                             row.effective_to, f"claimant_contact:{row.contact_id}.{field}")

    # A payment to a claimant landed in an account someone else also holds. A provider paid into its
    # own registered account is normal; a claimant sharing that account is already SHARED_CONTACT_PROVIDER.
    claimant_banks = contact.dropna(subset=["bank_token"]).groupby("bank_token")["claimant_id"].apply(set)
    provider_banks = provider.groupby("bank_token")["provider_id"].apply(set)
    for row in tables["payment"][tables["payment"]["payee_type"] == "CLAIMANT"].itertuples(index=False):
        token, payee = row.payee_bank_token, row.payee_claimant_id
        others = (claimant_banks.get(token, set()) | provider_banks.get(token, set())) - {payee}
        for owner in sorted(others):
            if frozenset((payee, owner)) in hidden_pairs:
                continue
            register.add(row.payment_id, owner, "PAID_TO_SHARED_ACCOUNT", row.payment_date, None,
                         f"payment:{row.payment_id}.payee_bank_token")

    edges = pd.DataFrame(list(register.edges.values()))
    edges = edges.sort_values(["edge_type", "source_node_id", "target_node_id"], ignore_index=True)
    edges.insert(0, "edge_id", [f"EDG-{number:06d}" for number in range(1, len(edges) + 1)])
    return nodes, edges
