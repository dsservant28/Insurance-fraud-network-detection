"""Build networks from evidence links and score them (ARCHITECTURE.md sections 3.3-3.4).

Only evidence links join claimants (P7): holding a policy or using a provider never does. Each
network is scored with a noisy-OR over signal families, so independent kinds of evidence add up,
weak families need corroboration (P4, P5), and adding members never raises a score by itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from fraudnet.detect.links import STRONG_FAMILIES

PRIORITIES = (("CRITICAL", 0.9), ("HIGH", 0.8), ("MEDIUM", 0.7), ("LOW", 0.0))


@dataclass
class TypeEvidence:
    edge_type: str
    family: str
    best: float            # strongest link of this type inside the network
    touched: list[str]     # claimants with at least one such link
    coverage: float
    repetition: float
    strength: float        # best × coverage × repetition
    links: pd.DataFrame


@dataclass
class Support:
    code: str
    value: float
    evidence: dict


@dataclass
class Network:
    members: list[str]
    links: pd.DataFrame                      # links between members, and from members to providers
    types: dict[str, TypeEvidence]
    families: dict[str, float]
    support: list[Support]
    support_strength: float
    score: float
    contributions: list[tuple[str, float]] = field(default_factory=list)  # family, score added (waterfall)
    context: dict[str, str] = field(default_factory=dict)                  # node_id -> member_role
    network_id: str = ""
    rank: int = 0
    priority: str = "LOW"
    flagged: bool = False


def evidence_links(links: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Links strong enough to count, without shared incidents that nothing else corroborates.

    One incident links all of its parties to each other at once, so the repetition principle says
    nothing about it. An incident's links count only when two of its parties are also linked by
    another family; otherwise an ordinary three-car crash would attach bystanders to a network.
    Provider-based weak links (similar stories, early claims) are the same: a single coincidental pair
    at one provider joins nobody unless another family links the same two people (P5).
    """
    net = settings["network"]
    standing = links[links["strength"] >= net["min_link_strength"]]
    incident = standing["edge_type"] == "SAME_INCIDENT"
    provider_based = standing["edge_type"].isin(["SIMILAR_NARRATIVE", "EARLY_CLAIM_PAIR"])
    other = set(zip(standing.loc[~incident, "source_node_id"], standing.loc[~incident, "target_node_id"]))
    corroborated = {value for value, rows in standing[incident].groupby("matched_value")
                    if any(pair in other for pair in zip(rows["source_node_id"], rows["target_node_id"]))}
    keep = ~incident | standing["matched_value"].isin(corroborated)

    pairs_by_type: dict[str, set] = {}
    for row in standing[~provider_based].itertuples(index=False):
        pairs_by_type.setdefault(row.edge_type, set()).add((row.source_node_id, row.target_node_id))
    for (edge_type, value), rows in standing[provider_based].groupby(["edge_type", "matched_value"]):
        people = set(rows["source_node_id"]) | set(rows["target_node_id"])
        if len(people) >= net["repetition_min_claimants"]:
            continue
        for index, pair in zip(rows.index, zip(rows["source_node_id"], rows["target_node_id"])):
            if not any(pair in pairs for pairs in pairs_by_type.values()):
                keep[index] = False
    return standing[keep]


def group_claimants(links: pd.DataFrame, settings: dict) -> list[list[str]]:
    """Connected groups over evidence links, with oversized groups split by Louvain communities."""
    net = settings["network"]
    pairs = links[links["target_node_id"].str.startswith("CLT-")]
    graph = nx.Graph()
    for row in pairs.itertuples(index=False):
        weight = max(row.strength, graph.get_edge_data(row.source_node_id, row.target_node_id, {}).get("weight", 0))
        graph.add_edge(row.source_node_id, row.target_node_id, weight=weight)
    groups = []
    for component in sorted(nx.connected_components(graph), key=min):
        if len(component) <= net["max_claimants"]:
            groups.append(sorted(component))
            continue
        subgraph = graph.subgraph(sorted(component))
        parts = nx.community.louvain_communities(subgraph, weight="weight", resolution=net["louvain_resolution"],
                                                 seed=net["louvain_seed"])
        groups.extend(sorted(part) for part in parts if len(part) >= 2)
    return sorted(groups, key=lambda group: group[0])


def _type_evidence(members: list[str], inside: pd.DataFrame, settings: dict) -> dict[str, TypeEvidence]:
    net, result = settings["network"], {}
    for edge_type, rows in inside.groupby("edge_type", sort=True):
        family = rows["family"].iloc[0]
        touched = sorted({node for node in pd.concat([rows["source_node_id"], rows["target_node_id"]])
                          if node in set(members)})
        coverage = math.sqrt(len(touched) / len(members))
        repeated = family in STRONG_FAMILIES or len(touched) >= net["repetition_min_claimants"]
        repetition = 1.0 if repeated else net["repetition_factor"]
        best = float(rows["strength"].max())
        result[edge_type] = TypeEvidence(edge_type, family, best, touched, round(coverage, 4), repetition,
                                         round(best * coverage * repetition, 4), rows)
    return result


def _support(members: list[str], inside: pd.DataFrame, used: pd.DataFrame, invoices: pd.DataFrame,
             busy: set[str], settings: dict) -> list[Support]:
    """Claim-level facts that add weight to a network the links already formed (section 3.2)."""
    values, found = settings["support"], []
    unrecorded = inside[inside["in_recorded_edges"].eq(0).fillna(False)]
    if len(unrecorded):
        found.append(Support("UNRECORDED_LINK", values["unrecorded_link"],
                             {"link_ids": unrecorded["link_id"].tolist(),
                              "edge_types": sorted(set(unrecorded["edge_type"])),
                              "pairs": [[a, b] for a, b in zip(unrecorded["source_node_id"],
                                                               unrecorded["target_node_id"])]}))

    mine = used[used["claimant_id"].isin(members)]
    if mine.empty:
        return found
    users = mine.groupby("provider_id")["claimant_id"].nunique().sort_index()
    top = users.idxmax()
    share = users[top] / len(members)
    concentrated = (users[top] >= values["concentration_min_claimants"] and share >= values["concentration_min_share"]
                    and top not in busy)
    if concentrated:
        found.append(Support("PROVIDER_CONCENTRATION", values["provider_concentration"],
                             {"provider_id": top, "claimants_using": int(users[top]), "members": len(members),
                              "share": round(float(share), 4)}))
    at_top = invoices[invoices["claimant_id"].isin(members) & (invoices["provider_id"] == top)]
    if len(at_top) and at_top["amount_ratio"].median() >= settings["indicators"]["inflated_ratio"]:
        found.append(Support("INFLATED_AMOUNT", values["inflated_amount"],
                             {"provider_id": top, "invoice_ids": at_top["invoice_id"].tolist(),
                              "median_ratio": round(float(at_top["amount_ratio"].median()), 4),
                              "peer_median_cents": sorted({int(v) for v in at_top["peer_median_cents"]})}))
    return found


def noisy_or(strengths) -> float:
    remaining = 1.0
    for strength in strengths:
        remaining *= 1.0 - strength
    return 1.0 - remaining


def score_network(members: list[str], links: pd.DataFrame, used: pd.DataFrame, invoices: pd.DataFrame,
                  busy: set[str], settings: dict) -> Network:
    """Score one group. `links` are evidence links (see `evidence_links`)."""
    member_set = set(members)
    inside = links[links["source_node_id"].isin(member_set)
                   & (links["target_node_id"].isin(member_set) | links["target_node_id"].str.startswith("PRV-"))]
    types = _type_evidence(members, inside, settings)
    families: dict[str, float] = {}
    for evidence in types.values():
        families[evidence.family] = max(families.get(evidence.family, 0.0), evidence.strength)
    support = _support(members, inside, used, invoices, busy, settings)
    support_strength = min(settings["support"]["cap"], noisy_or(item.value for item in support)) if families else 0.0

    contributions, running = [], 0.0
    for family, strength in sorted(families.items(), key=lambda item: (-item[1], item[0])) + [("SUPPORT", support_strength)]:
        after = noisy_or([running, strength])
        contributions.append((family, round(after - running, 4)))
        running = after
    return Network(members, inside, types, families, support, round(support_strength, 4), round(running, 4),
                   contributions)


def _context(network: Network) -> dict[str, str]:
    """Providers and incidents that carry the evidence, added to the network as context members."""
    context = {}
    for row in network.links.itertuples(index=False):
        if row.edge_type == "SHARED_CONTACT_PROVIDER":
            context[row.target_node_id] = "LINKED_PROVIDER"
        elif row.edge_type in {"SIMILAR_NARRATIVE", "EARLY_CLAIM_PAIR"}:
            context.setdefault(row.matched_value, "SHARED_PROVIDER")
        elif row.edge_type == "DUPLICATE_INVOICE":
            context.setdefault(row.matched_value.split()[0], "BILLING_PROVIDER")
        elif row.edge_type == "SAME_INCIDENT":
            context[row.matched_value] = "SHARED_INCIDENT"
    for item in network.support:
        if item.code == "PROVIDER_CONCENTRATION":
            context.setdefault(item.evidence["provider_id"], "SHARED_PROVIDER")
    return dict(sorted(context.items()))


def priority_of(score: float) -> str:
    return next(name for name, floor in PRIORITIES if score >= floor)


def build_networks(links: pd.DataFrame, used: pd.DataFrame, invoices: pd.DataFrame, busy: set[str],
                   settings: dict) -> list[Network]:
    """Score every group and rank them: score, then size, then lowest member ID. IDs follow rank."""
    evidence = evidence_links(links, settings)
    networks = [score_network(group, evidence, used, invoices, busy, settings)
                for group in group_claimants(evidence, settings)]
    networks.sort(key=lambda item: (-item.score, -len(item.members), item.members[0]))
    for rank, network in enumerate(networks, start=1):
        network.rank, network.network_id = rank, f"NET-{rank:06d}"
        network.priority = priority_of(network.score)
        network.flagged = network.score >= settings["score"]["flag_threshold"]
        network.context = _context(network)
    return networks
