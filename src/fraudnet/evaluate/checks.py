"""Edge-case results, exception reconciliation and the explanation check (DATA_DICTIONARY sections 11.2 and 13)."""
from __future__ import annotations

import json
import re
from itertools import combinations

import pandas as pd

from fraudnet.validate.exceptions import find_exceptions

ID_PATTERN = re.compile(r"\b(?:CLT-\d{6}|PRV-\d{6}|CLM-2026-\d{6}|INC-2026-\d{6}|INV-PRV-\d{6}-\d{6}|PAY-2026-\d{6}"
                        r"|POL-\d{6})\b")


def _ids(labels: pd.DataFrame, rule: str, entity_type: str) -> set[str]:
    rows = labels[(labels["rule_id"] == rule) & (labels["entity_type"] == entity_type)]
    return set(rows["entity_id"])


def reconcile_exceptions(tables: dict[str, pd.DataFrame], labels: pd.DataFrame) -> dict:
    """Every exception has a label (no silent corruption) and every labelled exception was found (no lost labels)."""
    exceptions = find_exceptions(tables)
    found = {kind: set(rows["entity_id"]) for kind, rows in exceptions.groupby("exception_type")}
    expected = {"ORPHAN_POLICY_REF": _ids(labels, "EC-1", "CLAIM"), "PAYMENT_OVER_APPROVED": _ids(labels, "EC-2", "CLAIM"),
                "DUPLICATE_INVOICE": _ids(labels, "EC-3", "INVOICE")}
    result = {}
    for kind, labelled in expected.items():
        seen = found.get(kind, set())
        result[kind] = {"labelled": len(labelled), "found": len(seen), "unlabelled_exceptions": sorted(seen - labelled),
                        "missed_labels": sorted(labelled - seen), "status": "PASS" if seen == labelled else "FAIL"}
    return result


def edge_cases(tables, labels, detect: dict[str, pd.DataFrame], score: dict) -> dict:
    """EC-1 to EC-5, each with the evidence the detector produced for it."""
    indicators, edges = detect["fraud_indicator"], detect["detected_edge"]
    flagged_claims = {code: set() for code in ("ORPHAN_POLICY_REF", "PAYMENT_OVER_APPROVED")}
    for row in indicators[indicators["indicator_code"].isin(list(flagged_claims))].itertuples(index=False):
        flagged_claims[row.indicator_code].add(json.loads(row.evidence_json)["claim_id"])

    def found(code, rule):
        labelled = _ids(labels, rule, "CLAIM")
        return {"labelled_claims": len(labelled), "found": len(labelled & flagged_claims[code]),
                "status": "PASS" if labelled <= flagged_claims[code] else "FAIL"}

    per_rule = score["per_rule"]
    hidden = labels[(labels["issue_type"] == "EC-4") & (labels["entity_type"] == "CLAIMANT")]
    expected_pairs = {tuple(sorted(pair)) for _, rows in hidden.groupby("ring_id")
                      for pair in combinations(rows["entity_id"], 2)}
    identity = edges[edges["edge_type"].isin(["SHARED_BANK", "SHARED_PHONE"]) & edges["in_recorded_edges"].eq("0")]
    recovered = set(zip(identity["source_node_id"], identity["target_node_id"])) & expected_pairs
    recorded = tables["relationship_edge"]
    leaked = set(zip(recorded["source_node_id"], recorded["target_node_id"])) & expected_pairs

    sites = _ids(labels, "B-ADDR-01", "CLAIMANT")
    address = edges[(edges["edge_type"] == "SHARED_ADDRESS") & edges["source_node_id"].isin(sites)
                    & edges["target_node_id"].isin(sites)]
    ec3 = per_rule.get("EC-3", {})
    ec5 = per_rule.get("B-ADDR-01", {})
    return {
        "EC-1": {"rule": "Orphan policy reference routed to an exception", **found("ORPHAN_POLICY_REF", "EC-1")},
        "EC-2": {"rule": "Payment above approved amount routed to payment review",
                 **found("PAYMENT_OVER_APPROVED", "EC-2")},
        "EC-3": {"rule": "Duplicate invoice groups flagged as networks", "groups": ec3.get("groups", 0),
                 "found": ec3.get("flagged", 0), "status": "PASS" if ec3.get("recall") == 1.0 else "FAIL"},
        "EC-4": {"rule": "Hidden ring links recovered and marked missing from the recorded edges",
                 "expected_pairs": len(expected_pairs), "recovered_pairs": len(recovered),
                 "recovery": round(len(recovered) / len(expected_pairs), 4) if expected_pairs else None,
                 "pairs_wrongly_in_recorded_edges": len(leaked),
                 "status": "PASS" if expected_pairs and recovered == expected_pairs and not leaked else "FAIL"},
        "EC-5": {"rule": "Common addresses not flagged on address alone", "sites": ec5.get("groups", 0),
                 "flagged": ec5.get("flagged", 0),
                 "address_links_explained_as_building": round(float(address["explanation_code"].eq("BUILDING").mean()), 4)
                 if len(address) else None,
                 "status": "PASS" if ec5.get("flagged", 1) == 0 else "FAIL"},
    }


def explanation_check(tables: dict[str, pd.DataFrame], detect: dict[str, pd.DataFrame]) -> dict:
    """Every flagged network has evidence, and every ID cited anywhere in the output exists in the input."""
    known = set()
    for table, column in (("claimant", "claimant_id"), ("provider", "provider_id"), ("claim", "claim_id"),
                          ("incident", "incident_id"), ("invoice", "invoice_id"), ("payment", "payment_id"),
                          ("policy", "policy_id")):
        known |= set(tables[table][column])
    claims = tables["claim"]
    known |= set(claims["policy_ref"])  # EC-1 names a policy that doesn't exist, and says so
    network, indicators = detect["network"], detect["fraud_indicator"]
    texts = list(network["summary"]) + list(indicators["explanation"]) + list(indicators["evidence_json"])
    cited = {match for text in texts for match in ID_PATTERN.findall(text)}
    flagged = set(network.loc[network["flagged"] == "1", "network_id"])
    with_evidence = set(indicators["network_id"])
    no_id = [row.indicator_id for row in indicators.itertuples(index=False) if not ID_PATTERN.search(row.explanation)]
    return {"flagged_networks": len(flagged), "flagged_without_indicators": sorted(flagged - with_evidence),
            "ids_cited": len(cited), "unknown_ids": sorted(cited - known), "indicators_without_ids": no_id,
            "status": "PASS" if flagged <= with_evidence and cited <= known and not no_id else "FAIL"}
