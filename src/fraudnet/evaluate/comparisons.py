"""Comparison methods and one-principle-off runs (ARCHITECTURE.md section 5).

Each returns networks in rank order, scored by the same metrics as the detector, so the report
shows what each design principle adds.
"""
from __future__ import annotations

import copy

import networkx as nx
import pandas as pd

from fraudnet.detect.facts import invoice_facts
from fraudnet.detect.links import claims_with_incidents, provider_use, rebuild_links
from fraudnet.detect.networks import build_networks
from fraudnet.evaluate.metrics import Ranked

CONTACT_TYPES = ("SHARED_ADDRESS", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK")


def _components(pairs) -> list[Ranked]:
    """Every connected group of claimants is flagged; bigger groups (more links) rank first."""
    graph = nx.Graph()
    graph.add_edges_from(pairs)
    groups = [(graph.subgraph(component).number_of_edges(), sorted(component))
              for component in nx.connected_components(graph)]
    groups.sort(key=lambda item: (-item[0], item[1][0]))
    return [Ranked(f"CMP-{n:06d}", frozenset(members), True) for n, (_, members) in enumerate(groups, start=1)]


def any_shared_value(links: pd.DataFrame) -> list[Ranked]:
    """Comparison (a): any shared address, phone, email or bank links two claimants. No explanations."""
    rows = links[links["edge_type"].isin(CONTACT_TYPES)]
    return _components(zip(rows["source_node_id"], rows["target_node_id"]))


def recorded_edges_only(tables: dict[str, pd.DataFrame]) -> list[Ranked]:
    """Comparison (b): the recorded relationship_edge register as given, with no rebuilding."""
    edges = tables["relationship_edge"]
    rows = edges[edges["edge_type"].isin(CONTACT_TYPES)]
    return _components(zip(rows["source_node_id"], rows["target_node_id"]))


def ranked_detector(tables: dict[str, pd.DataFrame], settings: dict) -> list[Ranked]:
    link_set = rebuild_links(tables, settings)
    used = provider_use(tables, claims_with_incidents(tables))
    busy = {provider for provider, count in link_set.provider_customers.items()
            if count > link_set.busy_provider_min_customers}
    networks = build_networks(link_set.links, used, invoice_facts(tables, settings), busy, settings)
    return [Ranked(item.network_id, frozenset(item.members), item.flagged) for item in networks]


def principle_off(settings: dict, name: str) -> dict:
    """A copy of the settings with one principle switched off."""
    changed = copy.deepcopy(settings)
    if name == "no_benign_explanations":  # P3
        for key in ("household_factor", "building_factor", "common_event_factor", "busy_provider_factor"):
            changed["explanations"][key] = 1.0
    elif name == "no_repetition":  # P5
        changed["network"]["repetition_factor"] = 1.0
        changed["network"]["repetition_min_claimants"] = 2
    elif name == "provider_as_plain_link":  # P4
        changed["links"]["provider_as_link"] = True
    else:
        raise ValueError(f"unknown principle switch: {name}")
    return changed


PRINCIPLES = {
    "no_benign_explanations": "P3 off: households, buildings, storms and busy providers are not explained away",
    "no_repetition": "P5 off: a weak pattern between two people counts as much as a repeated one",
    "provider_as_plain_link": "P4 off: any two customers of a provider are linked, with no shared anomaly",
}
COMPARISONS = {
    "any_shared_value": "Flag every group joined by any shared address, phone, email or bank",
    "recorded_edges_only": "Flag every group joined by the recorded relationship register as given",
}
