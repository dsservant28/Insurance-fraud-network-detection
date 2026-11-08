"""Rebuild links between claimants from raw input values (ARCHITECTURE.md sections 2 and 3.1).

The recorded `relationship_edge` register is treated as a possibly incomplete hint: every link here
is rebuilt from contact rows, claims, incidents and invoices, and only then compared with it
(`in_recorded_edges`). Each link carries its source rows, matched value, the benign explanation
checked for it, and a strength from its cap, its rarity in this dataset and that explanation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from itertools import combinations

import pandas as pd

from fraudnet.detect.normalise import (
    IDENTITY_KEYS, NarrativeSimilarity, address_key, narrative_words, surname, tells_a_story,
)

OPEN_END = "9999-12-31"
FAMILY = {
    "SHARED_BANK": "IDENTITY", "SHARED_PHONE": "IDENTITY", "SHARED_EMAIL": "IDENTITY",
    "SHARED_CONTACT_PROVIDER": "IDENTITY", "DUPLICATE_INVOICE": "BILLING", "SIMILAR_NARRATIVE": "STORY",
    "EARLY_CLAIM_PAIR": "TIMING", "SAME_INCIDENT": "INCIDENT", "SHARED_ADDRESS": "LOCATION",
    "SHARED_PROVIDER": "PROVIDER",  # only with provider_as_link, an evaluation switch (P4 off)
}
STRONG_FAMILIES = frozenset({"IDENTITY", "BILLING"})
CONTACT_LINKS = {"bank_token": "SHARED_BANK", "phone": "SHARED_PHONE", "email": "SHARED_EMAIL"}
RECORDED_TYPES = frozenset({"SHARED_BANK", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_ADDRESS", "SHARED_CONTACT_PROVIDER"})
COLUMNS = ["link_id", "source_node_id", "target_node_id", "edge_type", "family", "matched_value", "normalized_value",
           "valid_from", "valid_to", "source_refs_json", "detail_json", "in_recorded_edges", "cap", "rarity",
           "explanation_code", "explanation_factor", "strength"]


@dataclass
class LinkSet:
    links: pd.DataFrame
    rarity: dict[str, dict]            # edge_type -> {"claimants", "share", "rarity"}
    busy_provider_min_customers: float
    provider_customers: dict[str, int] = field(default_factory=dict)


class _Collector:
    """One link per (source, target, type, matched value), covering every source row that shows it."""

    def __init__(self) -> None:
        self.items: dict[tuple, dict] = {}

    def add(self, source: str, target: str, edge_type: str, matched: str, normalized: str, start: str, end: str,
            refs, detail: dict, explanation: tuple[str | None, float] = (None, 1.0)) -> None:
        key = (source, target, edge_type, matched)
        if key not in self.items:
            self.items[key] = {"source_node_id": source, "target_node_id": target, "edge_type": edge_type,
                               "matched_value": matched, "normalized_value": normalized, "valid_from": start,
                               "valid_to": end, "refs": set(refs), "detail": dict(detail),
                               "explanation_code": explanation[0], "explanation_factor": explanation[1]}
            return
        item = self.items[key]
        item["valid_from"], item["valid_to"] = min(item["valid_from"], start), max(item["valid_to"], end)
        item["refs"].update(refs)
        if "similarity" in detail and detail["similarity"] > item["detail"].get("similarity", 0):
            item["detail"] = dict(detail)
        # One unexplained occurrence is enough for the link to stand at full strength.
        if explanation[1] > item["explanation_factor"]:
            item["explanation_code"], item["explanation_factor"] = explanation


def _days(a: str, b: str) -> int:
    return abs((pd.Timestamp(a) - pd.Timestamp(b)).days)


def _contacts(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    contact = tables["claimant_contact"].merge(tables["claimant"][["claimant_id", "full_name"]], on="claimant_id")
    rows = contact.assign(
        address_key=[address_key(*values) for values in zip(contact["address_line"], contact["city"],
                                                            contact["postal_code"])],
        surname=contact["full_name"].map(surname),
        end=contact["effective_to"].fillna(OPEN_END),
    )
    for column, to_key in IDENTITY_KEYS.items():
        rows[f"{column}_key"] = rows[column].map(to_key, na_action="ignore")
    return rows.sort_values(["claimant_id", "contact_id"], ignore_index=True)


def _overlapping_pairs(rows: pd.DataFrame, key_column: str):
    """(key, row a, row b, start, end) for rows of two claimants with one key in overlapping periods; a < b."""
    for value, group in rows.dropna(subset=[key_column]).groupby(key_column, sort=True):
        if group["claimant_id"].nunique() < 2:
            continue
        for a, b in combinations(group.to_dict("records"), 2):
            if a["claimant_id"] == b["claimant_id"]:
                continue
            start, end = max(a["effective_from"], b["effective_from"]), min(a["end"], b["end"])
            if start <= end:  # Different periods, such as a past tenant, are not a link.
                yield value, a, b, start, end, group


def _contact_links(rows: pd.DataFrame, settings: dict, out: _Collector) -> None:
    explain = settings["explanations"]
    households: set[tuple[str, str]] = set()
    for value, a, b, start, end, group in _overlapping_pairs(rows, "address_key"):
        residents = group[(group["effective_from"] <= end) & (group["end"] >= start)]["claimant_id"].nunique()
        same_family = a["surname"] == b["surname"]
        if same_family:
            households.add((a["claimant_id"], b["claimant_id"]))
        if residents >= explain["building_min_residents"]:
            explanation = ("BUILDING", explain["building_factor"])
        elif same_family:
            explanation = ("HOUSEHOLD", explain["household_factor"])
        else:
            explanation = (None, 1.0)
        out.add(a["claimant_id"], b["claimant_id"], "SHARED_ADDRESS", f"{a['address_line']} / {b['address_line']}",
                value, start, end, [f"claimant_contact:{a['contact_id']}.address_line",
                                    f"claimant_contact:{b['contact_id']}.address_line"],
                {"residents_at_once": int(residents), "surnames": [a["surname"], b["surname"]]}, explanation)

    for column, edge_type in CONTACT_LINKS.items():
        for value, a, b, start, end, _ in _overlapping_pairs(rows, f"{column}_key"):
            household = (a["claimant_id"], b["claimant_id"]) in households
            explanation = ("HOUSEHOLD", explain["household_factor"]) if household else (None, 1.0)
            out.add(a["claimant_id"], b["claimant_id"], edge_type, a[column], value, start, end,
                    [f"claimant_contact:{a['contact_id']}.{column}", f"claimant_contact:{b['contact_id']}.{column}"],
                    {"field": column, "surnames": [a["surname"], b["surname"]]}, explanation)


def _provider_contact_links(rows: pd.DataFrame, provider: pd.DataFrame, out: _Collector) -> None:
    """A claimant holding a provider's phone, email or bank account."""
    provider = provider.assign(end=provider["active_to"].fillna(OPEN_END))
    for column, to_key in IDENTITY_KEYS.items():
        owners: dict[str, list[dict]] = {}
        for record in provider.to_dict("records"):
            owners.setdefault(to_key(record[column]), []).append(record)
        for row in rows.dropna(subset=[f"{column}_key"]).to_dict("records"):
            for owner in owners.get(row[f"{column}_key"], []):
                start, end = max(row["effective_from"], owner["active_from"]), min(row["end"], owner["end"])
                if start <= end:
                    out.add(row["claimant_id"], owner["provider_id"], "SHARED_CONTACT_PROVIDER", row[column],
                            row[f"{column}_key"], start, end,
                            [f"claimant_contact:{row['contact_id']}.{column}", f"provider:{owner['provider_id']}.{column}"],
                            {"field": column})


def claims_with_incidents(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return tables["claim"].merge(
        tables["incident"][["incident_id", "incident_type", "incident_date", "city", "narrative"]], on="incident_id")


def _incident_links(claims: pd.DataFrame, settings: dict, out: _Collector) -> None:
    for incident_id, group in claims.groupby("incident_id", sort=True):
        people = sorted(set(group["claimant_id"]))
        if len(people) < settings["links"]["incident_min_parties"]:
            continue  # Two parties is an ordinary crash.
        day = group["incident_date"].iloc[0]
        claims_of = group.groupby("claimant_id")["claim_id"].apply(sorted)
        for a, b in combinations(people, 2):
            out.add(a, b, "SAME_INCIDENT", incident_id, incident_id, day, day,
                    [f"claim:{claim_id}.incident_id" for claim_id in claims_of[a] + claims_of[b]],
                    {"parties": len(people), "claims": claims_of[a] + claims_of[b]})


def _invoice_links(tables: dict[str, pd.DataFrame], claims: pd.DataFrame, out: _Collector) -> None:
    invoices = tables["invoice"].merge(claims[["claim_id", "claimant_id"]], on="claim_id")
    keys = ["provider_id", "external_invoice_no", "invoice_date", "total_cents"]
    for (provider_id, number, day, total), group in invoices.groupby(keys, sort=True):
        if group["claimant_id"].nunique() < 2:
            continue
        records = group.sort_values(["claimant_id", "invoice_id"]).to_dict("records")
        for a, b in combinations(records, 2):
            if a["claimant_id"] == b["claimant_id"]:
                continue
            out.add(a["claimant_id"], b["claimant_id"], "DUPLICATE_INVOICE", f"{provider_id} {number}",
                    f"{provider_id}|{number}|{day}|{int(total)}", day, day,
                    [f"invoice:{a['invoice_id']}.external_invoice_no", f"invoice:{b['invoice_id']}.external_invoice_no"],
                    {"provider_id": provider_id, "external_invoice_no": number, "invoice_date": day,
                     "total_cents": int(total), "invoices": [a["invoice_id"], b["invoice_id"]],
                     "claims": [a["claim_id"], b["claim_id"]]})


def provider_use(tables: dict[str, pd.DataFrame], claims: pd.DataFrame) -> pd.DataFrame:
    used = tables["claim_provider"][["claim_id", "provider_id"]].drop_duplicates().merge(claims, on="claim_id")
    return used.sort_values(["provider_id", "claimant_id", "claim_id"], ignore_index=True)


def _story_links(used: pd.DataFrame, similarity: NarrativeSimilarity, busy: set[str], settings: dict,
                 out: _Collector) -> None:
    """Near-identical narratives on different incidents at the same provider (P4)."""
    explain, minimum = settings["explanations"], settings["links"]["story_min_similarity"]
    used = used.assign(words=used["narrative"].map(narrative_words))
    stories = used["words"].map(lambda words: tells_a_story(words, settings["links"]["story_min_words"]))
    used = used.loc[stories.astype(bool)]
    for (provider_id, _), group in used.groupby(["provider_id", "incident_type"], sort=True):
        for a, b in combinations(group.to_dict("records"), 2):
            if a["claimant_id"] == b["claimant_id"] or a["incident_id"] == b["incident_id"]:
                continue
            score = similarity.similarity(a["words"], b["words"])
            if score < minimum:
                continue
            apart = _days(a["incident_date"], b["incident_date"])
            if a["city"] == b["city"] and apart <= explain["common_event_days"]:
                explanation = ("COMMON_EVENT", explain["common_event_factor"])
            elif provider_id in busy:
                explanation = ("BUSY_PROVIDER", explain["busy_provider_factor"])
            else:
                explanation = (None, 1.0)
            out.add(a["claimant_id"], b["claimant_id"], "SIMILAR_NARRATIVE", provider_id, provider_id,
                    min(a["incident_date"], b["incident_date"]), max(a["incident_date"], b["incident_date"]),
                    [f"incident:{a['incident_id']}.narrative", f"incident:{b['incident_id']}.narrative",
                     f"claim_provider:{a['claim_id']}|{provider_id}.provider_id",
                     f"claim_provider:{b['claim_id']}|{provider_id}.provider_id"],
                    {"similarity": round(score, 4), "claims": [a["claim_id"], b["claim_id"]],
                     "incidents": [a["incident_id"], b["incident_id"]], "cities": [a["city"], b["city"]],
                     "days_apart": apart}, explanation)


def _timing_links(used: pd.DataFrame, busy: set[str], settings: dict, out: _Collector) -> None:
    """Two claims soon after their policies started, at the same provider in the same window (P4)."""
    links, explain = settings["links"], settings["explanations"]
    gap = used["days_policy_start_to_incident"]
    early = used[gap.notna() & (gap >= 0) & (gap <= links["early_claim_max_days"])]
    for provider_id, group in early.groupby("provider_id", sort=True):
        for a, b in combinations(group.to_dict("records"), 2):
            if a["claimant_id"] == b["claimant_id"]:
                continue
            apart = _days(a["incident_date"], b["incident_date"])
            if apart > links["timing_window_days"]:
                continue
            explanation = ("BUSY_PROVIDER", explain["busy_provider_factor"]) if provider_id in busy else (None, 1.0)
            out.add(a["claimant_id"], b["claimant_id"], "EARLY_CLAIM_PAIR", provider_id, provider_id,
                    min(a["incident_date"], b["incident_date"]), max(a["incident_date"], b["incident_date"]),
                    [f"claim:{a['claim_id']}.days_policy_start_to_incident",
                     f"claim:{b['claim_id']}.days_policy_start_to_incident"],
                    {"claims": [a["claim_id"], b["claim_id"]],
                     "days_after_policy_start": [int(a["days_policy_start_to_incident"]),
                                                 int(b["days_policy_start_to_incident"])],
                     "days_apart": apart}, explanation)


def _repeated_stories(out: _Collector, settings: dict) -> None:
    """A busy provider explains a coincidental pair of similar stories, not the same story told by
    three or more of its customers who all match one another (P3 with P5). Common events stay explained."""
    minimum = settings["network"]["repetition_min_claimants"]
    by_provider: dict[str, list[dict]] = {}
    for item in out.items.values():
        if item["edge_type"] == "SIMILAR_NARRATIVE":
            by_provider.setdefault(item["matched_value"], []).append(item)
    for items in by_provider.values():
        pairs = {(item["source_node_id"], item["target_node_id"]) for item in items}
        neighbours: dict[str, set[str]] = {}
        for a, b in pairs:
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
        for item in items:
            if item["explanation_code"] != "BUSY_PROVIDER":
                continue
            a, b = item["source_node_id"], item["target_node_id"]
            shared = neighbours[a] & neighbours[b]  # claimants whose story matches both a and b
            if len(shared) + 2 >= minimum and all((min(x, y), max(x, y)) in pairs
                                                  for x in shared for y in shared if x != y):
                item["explanation_code"], item["explanation_factor"] = None, 1.0
                item["detail"]["repeated_story_claimants"] = len(shared) + 2


def _recorded(tables: dict[str, pd.DataFrame], frame: pd.DataFrame) -> list:
    edges = tables["relationship_edge"]
    recorded = set(zip(edges["source_node_id"], edges["target_node_id"], edges["edge_type"]))
    parties = edges[edges["edge_type"] == "INCIDENT_PARTY"]
    party = set(zip(parties["source_node_id"], parties["target_node_id"]))
    flags = []
    for row in frame.itertuples(index=False):
        if row.edge_type in RECORDED_TYPES:
            flags.append(int((row.source_node_id, row.target_node_id, row.edge_type) in recorded))
        elif row.edge_type == "SAME_INCIDENT":
            flags.append(int((row.source_node_id, row.matched_value) in party
                             and (row.target_node_id, row.matched_value) in party))
        else:
            flags.append(None)  # No recorded edge type describes this link.
    return flags


def _rarity(frame: pd.DataFrame, claimant_count: int, settings: dict) -> dict[str, dict]:
    """How rare each link type is: the share of claimants with an unexplained link of that type (P6)."""
    reference, floor = settings["rarity"]["reference_log10"], settings["rarity"]["floor"]
    result = {}
    for edge_type, group in frame.groupby("edge_type", sort=True):
        standing = group[group["explanation_factor"] >= 1.0]
        pool = standing if len(standing) else group
        people = set(pool["source_node_id"]) | set(pool["target_node_id"])
        people = {node for node in people if node.startswith("CLT-")}
        share = len(people) / max(claimant_count, 1)
        value = 1.0 if share <= 0 else min(1.0, max(floor, -math.log10(share) / reference))
        result[edge_type] = {"claimants": len(people), "share": round(share, 4), "rarity": round(value, 4)}
    return result


def _plain_provider_links(used: pd.DataFrame, busy: set[str], settings: dict, out: _Collector) -> None:
    """Every pair of customers of one provider, with no shared anomaly required.

    Off by default. The evaluator switches it on to measure what principle P4 adds: this is the
    naive design in which a busy provider merges unrelated people into one network.
    """
    explain = settings["explanations"]
    pairs = used[["provider_id", "claimant_id", "claim_id"]].drop_duplicates(["provider_id", "claimant_id"])
    pairs = pairs.merge(pairs, on="provider_id", suffixes=("_a", "_b"))
    pairs = pairs[pairs["claimant_id_a"] < pairs["claimant_id_b"]]
    for row in pairs.itertuples(index=False):
        explanation = ("BUSY_PROVIDER", explain["busy_provider_factor"]) if row.provider_id in busy else (None, 1.0)
        out.add(row.claimant_id_a, row.claimant_id_b, "SHARED_PROVIDER", row.provider_id, row.provider_id,
                "2026-01-01", OPEN_END, [f"claim_provider:{row.claim_id_a}|{row.provider_id}.provider_id",
                                         f"claim_provider:{row.claim_id_b}|{row.provider_id}.provider_id"],
                {"provider_id": row.provider_id}, explanation)


def rebuild_links(tables: dict[str, pd.DataFrame], settings: dict) -> LinkSet:
    """Every evidence link in the input, with its explanation and strength."""
    out = _Collector()
    rows = _contacts(tables)
    _contact_links(rows, settings, out)
    _provider_contact_links(rows, tables["provider"], out)

    claims = claims_with_incidents(tables)
    _incident_links(claims, settings, out)
    _invoice_links(tables, claims, out)

    used = provider_use(tables, claims)
    customers = used.groupby("provider_id")["claimant_id"].nunique()
    busy_min = float(customers.quantile(settings["explanations"]["busy_provider_percentile"])) if len(customers) else 0.0
    busy = set(customers[customers > busy_min].index)
    similarity = NarrativeSimilarity(tables["incident"]["narrative"])
    _story_links(used, similarity, busy, settings, out)
    _repeated_stories(out, settings)
    _timing_links(used, busy, settings, out)
    if settings["links"].get("provider_as_link", False):
        _plain_provider_links(used, busy, settings, out)

    records = []
    for item in out.items.values():
        record = {name: value for name, value in item.items() if name not in {"refs", "detail"}}
        record["valid_to"] = None if record["valid_to"] == OPEN_END else record["valid_to"]
        record["source_refs_json"] = json.dumps(sorted(item["refs"]))
        record["detail_json"] = json.dumps(item["detail"], sort_keys=True)
        records.append(record)
    frame = pd.DataFrame(records, columns=[c for c in COLUMNS if c not in {
        "link_id", "family", "in_recorded_edges", "cap", "rarity", "strength"}])
    frame = frame.sort_values(["edge_type", "source_node_id", "target_node_id", "matched_value"], ignore_index=True)
    frame["family"] = frame["edge_type"].map(FAMILY)
    frame["in_recorded_edges"] = pd.array(_recorded(tables, frame), dtype="Int64")

    rarity = _rarity(frame, len(tables["claimant"]), settings)
    caps = {**settings["links"]["caps"], "SHARED_PROVIDER": settings["links"].get("shared_provider_cap", 0.35)}
    frame["cap"] = frame["edge_type"].map(caps)
    frame["rarity"] = frame["edge_type"].map({name: value["rarity"] for name, value in rarity.items()})
    frame["strength"] = (frame["cap"] * frame["rarity"] * frame["explanation_factor"]).round(4)
    frame.insert(0, "link_id", [f"LNK-{number:06d}" for number in range(1, len(frame) + 1)])
    return LinkSet(frame[COLUMNS], rarity, busy_min, {key: int(value) for key, value in customers.items()})
