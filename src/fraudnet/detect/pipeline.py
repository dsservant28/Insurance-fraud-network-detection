"""Run the detector on input tables and assemble every output (ARCHITECTURE.md sections 3-4).

`run_detector` is a pure function of the input tables and settings, so the same data and settings
always give the same output. Writing files and the database happens in `store.py`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from fraudnet import __version__
from fraudnet.detect.explain import (INDICATOR_CODES, cleared_sentence, id_list, money, network_summary, severity,
                                     support_sentence, type_sentence)
from fraudnet.detect.facts import claim_facts, invoice_facts
from fraudnet.detect.links import claims_with_incidents, provider_use, rebuild_links
from fraudnet.detect.networks import Network, build_networks, score_network
from fraudnet.validate.exceptions import find_exceptions


@dataclass
class DetectorOutput:
    run: dict
    detected_edge: pd.DataFrame
    network: pd.DataFrame
    network_member: pd.DataFrame
    fraud_indicator: pd.DataFrame
    cleared_groups: list[dict]
    network_detail: list[dict]


def make_run_id(input_sha256: str, config_sha256: str, code_version: str = __version__) -> str:
    digest = hashlib.sha256(f"{input_sha256}|{config_sha256}|{code_version}".encode("utf-8")).hexdigest()
    return f"RUN-{digest[:12].upper()}"


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True)


def _network_indicators(network: Network, rarity: dict) -> list[dict]:
    rows = []
    for evidence in sorted(network.types.values(), key=lambda item: (-item.strength, item.edge_type)):
        rows.append({
            "network_id": network.network_id, "subject_node_id": evidence.touched[0],
            "indicator_code": INDICATOR_CODES[evidence.edge_type], "severity": severity(evidence.strength),
            "score_contribution": evidence.strength, "explanation": type_sentence(evidence, rarity),
            "evidence_json": _dumps({
                "link_ids": evidence.links["link_id"].tolist(), "edge_type": evidence.edge_type,
                "family": evidence.family, "claimants": evidence.touched,
                "pairs": [[a, b] for a, b in zip(evidence.links["source_node_id"], evidence.links["target_node_id"])],
                "matched_values": sorted(set(evidence.links["matched_value"])),
                "best_link_strength": evidence.best, "coverage": evidence.coverage, "repetition": evidence.repetition,
                "rate": rarity.get(evidence.edge_type)}),
        })
    for item in network.support:
        subject = item.evidence.get("provider_id", network.members[0])
        rows.append({"network_id": network.network_id, "subject_node_id": subject, "indicator_code": item.code,
                     "severity": severity(item.value), "score_contribution": item.value,
                     "explanation": support_sentence(item.code, item.evidence), "evidence_json": _dumps(item.evidence)})
    return rows


def _exception_indicators(tables: dict[str, pd.DataFrame], networks: list[Network]) -> list[dict]:
    """Data exceptions as indicators. Orphan policies and overpayments are errors to route, never fraud scores."""
    exceptions = find_exceptions(tables)
    claimant_of = dict(zip(tables["claim"]["claim_id"], tables["claim"]["claimant_id"]))
    in_network = {member: network.network_id for network in networks if network.flagged for member in network.members}
    rows, seen_groups = [], set()
    for row in exceptions.itertuples(index=False):
        detail = json.loads(row.detail_json)
        if row.exception_type == "DUPLICATE_INVOICE":
            group = tuple(detail["invoice_ids"])
            if group in seen_groups:
                continue
            seen_groups.add(group)
            claimants = detail["claimant_ids"]
            network_id = next((in_network[c] for c in claimants if c in in_network), None)
            explanation = (f"Invoices {id_list(group)} from provider {detail['provider_id']} repeat one invoice number, "
                           f"date and amount ({row.observed_value}) across claimants {id_list(claimants)}.")
            rows.append({"network_id": network_id, "subject_node_id": claimants[0], "indicator_code": row.exception_type,
                         "severity": "HIGH", "score_contribution": 0.0, "explanation": explanation,
                         "evidence_json": _dumps({"exception_id": row.exception_id, **detail})})
            continue
        claimant = claimant_of[row.entity_id]
        if row.exception_type == "ORPHAN_POLICY_REF":
            explanation = (f"Claim {row.entity_id} by {claimant} names policy {row.observed_value}, which does not "
                           f"exist. Route to an exception case and hold payment.")
        else:
            explanation = (f"Claim {row.entity_id} by {claimant} was paid {money(detail['paid_amount_cents'])} "
                           f"against {money(detail['approved_amount_cents'])} approved, through payments "
                           f"{id_list(detail['settled_payment_ids'])}. Review the payment.")
        rows.append({"network_id": None, "subject_node_id": claimant, "indicator_code": row.exception_type,
                     "severity": row.severity, "score_contribution": 0.0, "explanation": explanation,
                     "evidence_json": _dumps({"exception_id": row.exception_id, "claim_id": row.entity_id,
                                              "observed_value": row.observed_value, **detail})})
    return rows


def _members(network: Network) -> list[dict]:
    rows = []
    for member in network.members:
        touching = network.links[(network.links["source_node_id"] == member) | (network.links["target_node_id"] == member)]
        rows.append({"network_id": network.network_id, "node_id": member, "member_role": "CLAIMANT",
                     "member_score": round(float(touching["strength"].max()) if len(touching) else 0.0, 4)})
    for node, role in network.context.items():
        rows.append({"network_id": network.network_id, "node_id": node, "member_role": role, "member_score": 0.0})
    return rows


def _timeline(tables: dict[str, pd.DataFrame], members: list[str]) -> list[dict]:
    claims = claims_with_incidents(tables)
    claims = claims[claims["claimant_id"].isin(members)]
    policy_start = dict(zip(tables["policy"]["policy_id"], tables["policy"]["effective_from"]))
    events = []
    for row in claims.itertuples(index=False):
        if isinstance(row.policy_id, str):
            events.append({"date": policy_start[row.policy_id], "event": "POLICY_START", "claimant_id": row.claimant_id,
                           "claim_id": row.claim_id, "ref": row.policy_id})
        events.append({"date": row.incident_date, "event": "INCIDENT", "claimant_id": row.claimant_id,
                       "claim_id": row.claim_id, "ref": row.incident_id})
        events.append({"date": row.reported_date, "event": "REPORTED", "claimant_id": row.claimant_id,
                       "claim_id": row.claim_id, "ref": row.claim_id})
    claimant_of = dict(zip(claims["claim_id"], claims["claimant_id"]))
    for row in tables["invoice"][tables["invoice"]["claim_id"].isin(claimant_of)].itertuples(index=False):
        events.append({"date": row.invoice_date, "event": "INVOICE", "claimant_id": claimant_of[row.claim_id],
                       "claim_id": row.claim_id, "ref": row.invoice_id, "provider_id": row.provider_id,
                       "amount_cents": int(row.total_cents)})
    for row in tables["payment"][tables["payment"]["claim_id"].isin(claimant_of)].itertuples(index=False):
        events.append({"date": row.payment_date, "event": "PAYMENT", "claimant_id": claimant_of[row.claim_id],
                       "claim_id": row.claim_id, "ref": row.payment_id, "amount_cents": int(row.amount_cents),
                       "status": row.current_status})
    return sorted(events, key=lambda event: (event["date"], event["claim_id"], event["event"], event["ref"]))


def _graph(network: Network, all_links: pd.DataFrame, used: pd.DataFrame, names: dict) -> dict:
    members = set(network.members)
    nodes = [{"id": member, "type": "CLAIMANT", "label": names.get(member, member)} for member in network.members]
    nodes += [{"id": node, "type": "PROVIDER" if node.startswith("PRV-") else "INCIDENT", "label": node,
               "role": role} for node, role in network.context.items()]
    between = all_links[all_links["source_node_id"].isin(members)
                        & (all_links["target_node_id"].isin(members) | all_links["target_node_id"].isin(network.context))]
    edges = [{"id": row.link_id, "source": row.source_node_id, "target": row.target_node_id,
              "edge_type": row.edge_type, "family": row.family, "strength": row.strength,
              "recorded": None if pd.isna(row.in_recorded_edges) else int(row.in_recorded_edges),
              "explanation": None if pd.isna(row.explanation_code) else row.explanation_code,
              "evidence": row.link_id in set(network.links["link_id"])}
             for row in between.itertuples(index=False)]
    for node, role in network.context.items():
        if node.startswith("PRV-"):
            users = sorted(set(used.loc[used["provider_id"] == node, "claimant_id"]) & members)
            edges += [{"id": f"USE-{user}-{node}", "source": user, "target": node, "edge_type": "USED_PROVIDER",
                       "family": "CONTEXT", "strength": 0.0, "recorded": None, "explanation": None, "evidence": False}
                      for user in users]
    return {"nodes": nodes, "edges": edges}


def _detail(network: Network, tables, all_links, used, names, rarity) -> dict:
    explained = all_links[all_links["source_node_id"].isin(network.members)
                          & all_links["target_node_id"].isin(network.members) & all_links["explanation_code"].notna()]
    return {
        "network_id": network.network_id, "rank": network.rank, "score": network.score,
        "priority": network.priority, "flagged": network.flagged, "members": network.members,
        "context": network.context, "families": network.families,
        "waterfall": [{"family": family, "added": added} for family, added in network.contributions],
        "evidence": [{"edge_type": item.edge_type, "family": item.family, "best_link_strength": item.best,
                      "coverage": item.coverage, "repetition": item.repetition, "strength": item.strength,
                      "claimants": item.touched, "sentence": type_sentence(item, rarity)}
                     for item in sorted(network.types.values(), key=lambda item: (-item.strength, item.edge_type))],
        "support": [{"code": item.code, "value": item.value, "sentence": support_sentence(item.code, item.evidence)}
                    for item in network.support],
        "discounted_links": [{"link_id": row.link_id, "edge_type": row.edge_type, "explanation": row.explanation_code,
                              "full_strength": round(row.cap * row.rarity, 4), "strength": row.strength}
                             for row in explained.itertuples(index=False)],
        "timeline": _timeline(tables, network.members),
        "graph": _graph(network, all_links, used, names),
    }


def _cleared_groups(links: pd.DataFrame, flagged: set[str], used, invoices, busy, settings, customers) -> list[dict]:
    """Groups that look like a pattern but are explained, with what they would score without the explanation."""
    explained = links[links["target_node_id"].str.startswith("CLT-") & links["explanation_code"].notna()]
    graph = nx.Graph()
    graph.add_edges_from(zip(explained["source_node_id"], explained["target_node_id"]))
    groups = []
    for component in sorted(nx.connected_components(graph), key=min):
        members = sorted(component)
        if set(members) & flagged:
            continue
        rows = explained[explained["source_node_id"].isin(component)]
        unexplained = rows.assign(strength=(rows["cap"] * rows["rarity"]).round(4))
        would_be = score_network(members, unexplained, used, invoices, busy, settings).score
        groups.append({
            "members": members, "explanations": rows["explanation_code"].value_counts().sort_index().to_dict(),
            "score_without_explanations": would_be, "link_ids": rows["link_id"].tolist(),
            "reasons": [cleared_sentence(code, part, settings, customers)
                        for code, part in rows.groupby("explanation_code", sort=True)],
        })
    groups.sort(key=lambda group: (-group["score_without_explanations"], group["members"][0]))
    for number, group in enumerate(groups, start=1):
        group["group_id"] = f"CLR-{number:06d}"
    return groups


def run_detector(tables: dict[str, pd.DataFrame], settings: dict, input_sha256: str, config_sha256: str) -> DetectorOutput:
    run_id = make_run_id(input_sha256, config_sha256)
    link_set = rebuild_links(tables, settings)
    links = link_set.links
    used = provider_use(tables, claims_with_incidents(tables))
    invoices = invoice_facts(tables, settings)
    busy = {provider for provider, count in link_set.provider_customers.items()
            if count > link_set.busy_provider_min_customers}
    networks = build_networks(links, used, invoices, busy, settings)
    threshold = settings["score"]["flag_threshold"]
    names = dict(zip(tables["claimant"]["claimant_id"], tables["claimant"]["full_name"]))

    network = pd.DataFrame([{
        "network_id": item.network_id, "run_id": run_id, "rank": item.rank, "score": item.score,
        "priority": item.priority, "flagged": int(item.flagged), "member_count": len(item.members),
        "families": ";".join(sorted(item.families)), "summary": network_summary(item, link_set.rarity, threshold),
    } for item in networks], columns=["network_id", "run_id", "rank", "score", "priority", "flagged", "member_count",
                                      "families", "summary"])
    members = pd.DataFrame([row for item in networks for row in _members(item)],
                           columns=["network_id", "node_id", "member_role", "member_score"])
    indicator_rows = [row for item in networks for row in _network_indicators(item, link_set.rarity)]
    indicator_rows += _exception_indicators(tables, networks)
    indicators = pd.DataFrame(indicator_rows, columns=["network_id", "subject_node_id", "indicator_code", "severity",
                                                       "score_contribution", "explanation", "evidence_json"])
    indicators.insert(0, "run_id", run_id)
    indicators.insert(0, "indicator_id", [f"FIN-{n:06d}" for n in range(1, len(indicators) + 1)])
    edges = links.copy()
    edges.insert(0, "run_id", run_id)

    flagged_members = {member for item in networks if item.flagged for member in item.members}
    cleared = _cleared_groups(links, flagged_members, used, invoices, busy, settings, link_set.provider_customers)
    details = [_detail(item, tables, links, used, names, link_set.rarity) for item in networks]
    facts = claim_facts(tables, settings)
    flagged = network[network["flagged"] == 1]
    run = {
        "run_id": run_id, "input_manifest_sha256": input_sha256, "config_sha256": config_sha256,
        "code_version": __version__,
        "counts": {
            "links": links["edge_type"].value_counts().sort_index().to_dict(),
            "unrecorded_links": int(links["in_recorded_edges"].eq(0).sum()),
            "explained_links": links["explanation_code"].value_counts().sort_index().to_dict(),
            "networks": len(network), "flagged_networks": len(flagged),
            "flagged_by_priority": flagged["priority"].value_counts().sort_index().to_dict(),
            "indicators": indicators["indicator_code"].value_counts().sort_index().to_dict(),
            "cleared_groups": len(cleared), "early_claims": int(facts["early_claim"].sum()),
            "inflated_invoices": int(invoices["inflated"].sum()),
        },
        "rarity": link_set.rarity, "busy_provider_min_customers": link_set.busy_provider_min_customers,
        "flag_threshold": threshold,
    }
    return DetectorOutput(run, edges, network, members, indicators, cleared, details)
