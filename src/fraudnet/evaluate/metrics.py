"""Match detected networks to labelled groups and compute the metrics in DATA_DICTIONARY section 13.

A network matches a labelled group when the Jaccard similarity of their claimants is at least 0.5.
Networks are matched in rank order and each group matches at most one network, so a duplicate
network for an already-found ring counts as a false alarm, not a second success.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

MATCH_JACCARD = 0.5
RANK_CUTOFFS = (5, 10)


@dataclass
class LabelledGroup:
    group_id: str
    rule_id: str
    is_fraud: bool
    claimants: frozenset[str]

    @property
    def kind(self) -> str:
        if self.rule_id.startswith("R-RING"):
            return "RING"
        return "BENIGN" if self.rule_id.startswith("B-") else "EDGE_CASE"


@dataclass
class Ranked:
    """One detected network as the evaluator sees it: its claimants, rank order and flag."""
    network_id: str
    claimants: frozenset[str]
    flagged: bool


def read_labels(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "hidden" / "ground_truth.csv", dtype=str, keep_default_na=False)


def labelled_groups(labels: pd.DataFrame) -> list[LabelledGroup]:
    """Every labelled group that has claimants. Provider-only groups (B-PROV-01) are checked separately."""
    claimants = labels[labels["entity_type"] == "CLAIMANT"]
    key = claimants["ring_id"].where(claimants["ring_id"] != "", claimants["group_id"])
    groups = []
    for group_id, rows in claimants.groupby(key, sort=True):
        groups.append(LabelledGroup(group_id, rows["rule_id"].iloc[0], rows["is_fraud"].iloc[0] == "1",
                                    frozenset(rows["entity_id"])))
    return groups


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def match(ranked: list[Ranked], groups: list[LabelledGroup]) -> list[dict]:
    """For each network in rank order, the best still-unmatched group with Jaccard ≥ 0.5, if any."""
    taken: set[str] = set()
    by_member: dict[str, list[LabelledGroup]] = {}
    for group in groups:
        for member in group.claimants:
            by_member.setdefault(member, []).append(group)
    rows = []
    for position, network in enumerate(ranked, start=1):
        candidates = {group.group_id: group for member in network.claimants for group in by_member.get(member, [])}
        best, best_score = None, 0.0
        for group in sorted(candidates.values(), key=lambda item: item.group_id):
            score = jaccard(network.claimants, group.claimants)
            if group.group_id not in taken and score > best_score:
                best, best_score = group, score
        matched = best if best is not None and best_score >= MATCH_JACCARD else None
        if matched:
            taken.add(matched.group_id)
        rows.append({"rank": position, "network_id": network.network_id, "flagged": network.flagged,
                     "claimants": len(network.claimants),
                     "group_id": matched.group_id if matched else None,
                     "rule_id": matched.rule_id if matched else None,
                     "is_fraud": bool(matched and matched.is_fraud),
                     "jaccard": round(best_score, 4) if matched else round(best_score, 4)})
    return rows


def _ap(relevant: list[bool], total: int) -> float:
    hits, total_precision = 0, 0.0
    for position, hit in enumerate(relevant, start=1):
        if hit:
            hits += 1
            total_precision += hits / position
    return total_precision / total if total else 0.0


def _ndcg(relevant: list[bool], total: int, cutoff: int) -> float:
    gain = sum(1 / math.log2(position + 1) for position, hit in enumerate(relevant[:cutoff], start=1) if hit)
    ideal = sum(1 / math.log2(position + 1) for position in range(1, min(total, cutoff) + 1))
    return gain / ideal if ideal else 0.0


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def score(ranked: list[Ranked], groups: list[LabelledGroup]) -> dict:
    """Headline, ranking and per-rule metrics for one ranked list of networks."""
    rows = match(ranked, groups)
    flagged = [row for row in rows if row["flagged"]]
    rings = [group for group in groups if group.kind == "RING"]
    fraud = [group for group in groups if group.is_fraud]
    benign = [group for group in groups if group.kind == "BENIGN"]
    found = {row["group_id"] for row in flagged if row["is_fraud"]}
    false_benign = {row["group_id"] for row in flagged if row["group_id"] and not row["is_fraud"]}
    ring_ids = {group.group_id for group in rings}

    relevant = [row["is_fraud"] for row in rows]
    top_n = len(fraud)  # R-precision: as many places as there are fraud groups to find
    result = {
        "flagged_networks": len(flagged),
        "true_positive_networks": sum(row["is_fraud"] for row in flagged),
        "false_positive_networks": sum(not row["is_fraud"] for row in flagged),
        "unmatched_flagged_networks": sum(row["group_id"] is None for row in flagged),
        "precision": _rate(sum(row["is_fraud"] for row in flagged), len(flagged)),
        "recall": _rate(len(found & ring_ids), len(rings)),
        "fraud_group_recall": _rate(len(found), len(fraud)),
        "false_positive_rate": _rate(len(false_benign), len(benign)),
        "false_negative_rate": _rate(len(rings) - len(found & ring_ids), len(rings)),
        "average_precision": round(_ap(relevant, len(fraud)), 4),
        "fraud_groups_in_top_n": {"n": top_n, "found": sum(relevant[:top_n]), "share": _rate(sum(relevant[:top_n]), top_n)},
        "r_precision": _rate(sum(relevant[:top_n]), top_n),
        "ndcg_at_r": round(_ndcg(relevant, len(fraud), top_n), 4),
        "mean_match_jaccard": round(sum(row["jaccard"] for row in flagged if row["is_fraud"])
                                    / max(1, sum(row["is_fraud"] for row in flagged)), 4),
    }
    for cutoff in RANK_CUTOFFS:
        result[f"precision_at_{cutoff}"] = _rate(sum(relevant[:cutoff]), cutoff)
        result[f"recall_at_{cutoff}"] = _rate(sum(relevant[:cutoff]), len(fraud))
        result[f"ndcg_at_{cutoff}"] = round(_ndcg(relevant, len(fraud), cutoff), 4)

    per_rule = {}
    for rule in sorted({group.rule_id for group in groups}):
        members = [group for group in groups if group.rule_id == rule]
        hit = {row["group_id"] for row in flagged} & {group.group_id for group in members}
        name = "recall" if members[0].is_fraud else "false_positive_rate"
        per_rule[rule] = {"groups": len(members), "flagged": len(hit), name: _rate(len(hit), len(members))}
    result["per_rule"] = per_rule
    result["matches"] = rows
    return result
