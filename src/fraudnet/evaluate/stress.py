"""Stress evaluation: the frozen detector on data it was not designed for. Plan: docs/STRESS_PLAN.md.

Every condition is generated in memory, written to CSV and read back exactly as the detector reads
input files, then scored against its labels with the same matching rules as docs/EVALUATION.md.
The predictions registered in docs/STRESS_PLAN.md section 5 are encoded in PREDICTIONS and checked
automatically: a prediction is a hit only when the mean over the stress seeds lies inside its range.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from fraudnet.detect.config import load_config
from fraudnet.detect.pipeline import run_detector
from fraudnet.evaluate.metrics import Ranked, labelled_groups, score
from fraudnet.generate.config import DEFAULT_SEED, GeneratorConfig
from fraudnet.generate.pipeline import generate_with_labels
from fraudnet.generate.scenario import LEVELS, STRENGTHS, TITLES, Scenario
from fraudnet.inputs import read_csv_table

STRESS_SEEDS = (1111, 2222, 3333, 4444, 5555)
CONFIRMATION_SEEDS = (6161, 7272, 8383, 9494, 10505)  # only for scoring a v0.2 (STRESS_PLAN.md rule 4)
FROZEN_COMMIT = "ddf09cc25bb0280ce1e6a479aaa8f0e28f13fa41"
THRESHOLDS = tuple(round(0.30 + 0.05 * step, 2) for step in range(14))
CAPACITY = (10, 20, 50)
SENSITIVITY_STEP = 0.3
SENSITIVE_CHANGE = 0.05
RING_RULES = tuple(f"R-RING-0{number}" for number in range(1, 7))
BASELINE = "baseline"


def conditions() -> list[Scenario | None]:
    return [None] + [Scenario(name, level) for name, levels in LEVELS.items() for level in levels]


def condition_label(scenario: Scenario | None) -> str:
    return BASELINE if scenario is None else scenario.label


# ---- one condition on one seed

def _roundtrip(tables: dict[str, pd.DataFrame], labels: pd.DataFrame, folder: Path):
    """Write every table to CSV and read it back the way the detector reads input files."""
    digest = hashlib.sha256()
    loaded = {}
    for name in sorted(tables):
        data = tables[name].to_csv(index=False, lineterminator="\n").encode("utf-8")
        digest.update(name.encode("utf-8") + b"\0" + data)
        (folder / f"{name}.csv").write_bytes(data)
        loaded[name] = read_csv_table(folder / f"{name}.csv", name)
    (folder / "labels.csv").write_bytes(labels.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    labels = pd.read_csv(folder / "labels.csv", dtype=str, keep_default_na=False)
    return loaded, labels, digest.hexdigest()


def _ranked(network: pd.DataFrame, members: pd.DataFrame) -> list[Ranked]:
    claimants = members[members["member_role"] == "CLAIMANT"].groupby("network_id")["node_id"].apply(frozenset)
    ordered = network.sort_values("rank")
    return [Ranked(row.network_id, claimants.get(row.network_id, frozenset()), bool(row.flagged))
            for row in ordered.itertuples()]


def _popular_provider_alarms(labels: pd.DataFrame, network: pd.DataFrame, members: pd.DataFrame) -> dict:
    popular = set(labels.loc[(labels["rule_id"] == "B-PROV-01") & (labels["entity_type"] == "PROVIDER"), "entity_id"])
    flagged = set(network.loc[network["flagged"] == 1, "network_id"])
    hits = members[members["network_id"].isin(flagged) & members["node_id"].isin(popular)]["node_id"].nunique()
    return {"groups": len(popular), "flagged": int(hits),
            "false_positive_rate": round(hits / len(popular), 4) if popular else None}


def _inside_links(edges: pd.DataFrame, members: set[str]) -> pd.DataFrame:
    return edges[edges["source_node_id"].isin(members) & edges["target_node_id"].isin(members)]


def _why_missed(group, edges: pd.DataFrame, networks: list[dict]) -> str:
    inside = _inside_links(edges, set(group.claimants))
    if inside.empty:
        return "no link of any kind among the members"
    if (inside["explanation_factor"] < 1).all():
        codes = ", ".join(sorted(set(inside["explanation_code"].dropna())))
        return f"every link among the members was explained away ({codes})"
    best = max(networks, key=lambda item: item["jaccard"], default=None)
    if best and best["jaccard"] >= 0.5 and not best["flagged"]:
        return f"found as a network but scored {best['score']:.3f}, below the flag threshold"
    if best and best["flagged"]:
        return f"flagged networks cover only part of the ring (best Jaccard {best['jaccard']:.2f})"
    if inside["strength"].max() < 0.15:
        return f"links too weak to join anyone (strongest {inside['strength'].max():.3f})"
    return "links present but no network formed around enough members"


def _gallery(result: dict, groups, labels: pd.DataFrame, output) -> dict:
    """Every missed ring and every false alarm, with the detector's own evidence."""
    network = output.network.set_index("network_id")
    members = output.network_member
    claimants = members[members["member_role"] == "CLAIMANT"]
    edges = output.detected_edge
    reasons = labels.drop_duplicates("group_id").set_index("group_id")["reason"].to_dict()
    reasons.update(labels[labels["ring_id"] != ""].drop_duplicates("ring_id").set_index("ring_id")["reason"].to_dict())
    found = {row["group_id"] for row in result["matches"] if row["flagged"] and row["is_fraud"]}
    misses = []
    for group in groups:
        if group.kind != "RING" or group.group_id in found:
            continue
        touching = claimants[claimants["node_id"].isin(group.claimants)]["network_id"].unique()
        overlaps = []
        for network_id in touching:
            inside = frozenset(claimants.loc[claimants["network_id"] == network_id, "node_id"])
            overlaps.append({"network_id": network_id, "score": float(network.loc[network_id, "score"]),
                             "flagged": bool(network.loc[network_id, "flagged"]),
                             "families": network.loc[network_id, "families"],
                             "jaccard": round(len(inside & group.claimants) / len(inside | group.claimants), 4)})
        inside = _inside_links(edges, set(group.claimants))
        link_summary = {edge_type: {"links": int(len(part)), "strongest": round(float(part["strength"].max()), 4),
                                    "explained": sorted(set(part["explanation_code"].dropna()))}
                        for edge_type, part in inside.groupby("edge_type", sort=True)}
        misses.append({"group_id": group.group_id, "rule_id": group.rule_id, "members": len(group.claimants),
                       "label_reason": reasons.get(group.group_id, ""), "links_among_members": link_summary,
                       "networks": sorted(overlaps, key=lambda item: -item["jaccard"])[:3],
                       "mechanism": _why_missed(group, edges, overlaps)})
    alarms = []
    for row in result["matches"]:
        if not row["flagged"] or row["is_fraud"]:
            continue
        alarms.append({"network_id": row["network_id"], "score": float(network.loc[row["network_id"], "score"]),
                       "members": row["claimants"], "families": network.loc[row["network_id"], "families"],
                       "rule_id": row["rule_id"] or "none (no labelled group)", "jaccard": row["jaccard"],
                       "label_reason": reasons.get(row["group_id"], "") if row["group_id"] else "",
                       "detector_summary": network.loc[row["network_id"], "summary"]})
    return {"missed_rings": misses, "false_alarms": sorted(alarms, key=lambda item: -item["score"])}


def _sweep(rows: list[dict], scores: dict[str, float], groups) -> list[dict]:
    """Precision and ring recall if the flag threshold were t, for the networks the detector formed."""
    rings = {group.group_id for group in groups if group.kind == "RING"}
    out = []
    for threshold in THRESHOLDS:
        flagged = [row for row in rows if scores[row["network_id"]] >= threshold]
        hits = {row["group_id"] for row in flagged if row["is_fraud"]}
        out.append({"threshold": threshold, "flagged": len(flagged),
                    "precision": round(sum(row["is_fraud"] for row in flagged) / len(flagged), 4) if flagged else None,
                    "recall": round(len(hits & rings) / len(rings), 4) if rings else None})
    return out


def detect_and_score(tables, labels, input_sha: str, settings: dict, config_sha: str, details: bool = True) -> dict:
    output = run_detector(tables, settings, input_sha, config_sha)
    groups = labelled_groups(labels)
    result = score(_ranked(output.network, output.network_member), groups)
    result["per_rule"]["B-PROV-01"] = _popular_provider_alarms(labels, output.network, output.network_member)
    benign = [rule for rule, item in result["per_rule"].items() if rule.startswith("B-")]
    result["max_benign_fp"] = max((result["per_rule"][rule]["false_positive_rate"] or 0.0) for rule in benign)
    relevant = [row["is_fraud"] for row in result["matches"]]
    result["capacity"] = {str(cutoff): int(sum(relevant[:cutoff])) for cutoff in CAPACITY}
    result["fraud_groups"] = sum(group.is_fraud for group in groups)
    if details:
        scores = dict(zip(output.network["network_id"], output.network["score"].astype(float)))
        result["sweep"] = _sweep(result["matches"], scores, groups)
        result["gallery"] = _gallery(result, groups, labels, output)
    result.pop("matches")
    return result


def run_condition(task: tuple[int, str | None, float | str | None]) -> dict:
    seed, name, level = task
    scenario = Scenario(name, level) if name else None
    settings, config_sha = load_config()
    tables, labels = generate_with_labels(GeneratorConfig(seed=seed, scale=1.0, scenario=scenario))
    with tempfile.TemporaryDirectory(prefix="fraudnet-stress-") as folder:
        tables, labels, input_sha = _roundtrip(tables, labels, Path(folder))
    result = detect_and_score(tables, labels, input_sha, settings, config_sha)
    return {"seed": seed, "condition": condition_label(scenario), "scenario": name, "level": level, **result}


# ---- setting sensitivity (development seed)

def numeric_settings(settings: dict, prefix: tuple = ()) -> list[tuple]:
    found = []
    for key, value in sorted(settings.items()):
        path = prefix + (key,)
        if isinstance(value, dict):
            found += numeric_settings(value, path)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and key != "louvain_seed":
            found.append(path)
    return found


def _moved(value, factor: float, path: tuple):
    if isinstance(value, int):
        moved = round(value * factor)
        return moved if moved != value else value + (1 if factor > 1 else -1)
    moved = value * factor
    if path[-1] == "busy_provider_percentile":
        return min(moved, 0.99)
    if value <= 1 and path[-1] not in ("louvain_resolution", "reference_log10"):
        return min(moved, 1.0)
    return moved


def _with(settings: dict, path: tuple, value) -> dict:
    changed = copy.deepcopy(settings)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return changed


def _sensitivity_task(task) -> dict:
    path, factor = task
    settings, config_sha = load_config()
    tables, labels, input_sha = _development_world()
    original = settings
    for key in path:
        original = original[key]
    moved = _moved(original, factor, path)
    result = detect_and_score(tables, labels, input_sha, _with(settings, path, moved), config_sha, details=False)
    return {"setting": ".".join(path), "from": original, "to": moved, "precision": result["precision"],
            "recall": result["recall"], "max_benign_fp": result["max_benign_fp"]}


_DEV_CACHE: dict = {}


def _development_world():
    if "world" not in _DEV_CACHE:
        tables, labels = generate_with_labels(GeneratorConfig(seed=DEFAULT_SEED, scale=1.0))
        with tempfile.TemporaryDirectory(prefix="fraudnet-stress-dev-") as folder:
            _DEV_CACHE["world"] = _roundtrip(tables, labels, Path(folder))
    return _DEV_CACHE["world"]


# ---- aggregation and predictions

def _mean(values):
    present = [value for value in values if value is not None]
    return round(statistics.fmean(present), 4) if present else None


def _spread(values):
    present = [value for value in values if value is not None]
    return round(statistics.pstdev(present), 4) if len(present) > 1 else 0.0


def metric(runs: list[dict], name: str):
    """Mean over seeds of one measure. Names: precision, recall, mean_match_jaccard, max_benign_fp,
    flagged_max, recall:<rule>, fp:<rule>, min_recall:<rule>|<rule>, single_id_share."""
    if name == "flagged_max":
        return max(run["flagged_networks"] for run in runs)
    if name.startswith("recall:"):
        return _mean([run["per_rule"].get(name[7:], {}).get("recall") for run in runs])
    if name.startswith("fp:"):
        return _mean([run["per_rule"].get(name[3:], {}).get("false_positive_rate") for run in runs])
    if name.startswith("min_recall:"):
        values = [metric(runs, f"recall:{rule}") for rule in name[11:].split("|")]
        return None if None in values else min(values)
    if name == "single_id_share":
        missed = [miss for run in runs for miss in run["gallery"]["missed_rings"]]
        if not missed:
            return None
        single = [miss for miss in missed if miss["rule_id"] == "R-RING-01" and ";" not in miss["label_reason"]]
        return round(len(single) / len(missed), 4)
    return _mean([run[name] for run in runs])


@dataclass(frozen=True)
class Prediction:
    pid: str
    hypothesis: str
    condition: str          # scenario name; with levels it applies to each listed level
    levels: tuple
    measure: str
    low: float
    high: float
    text: str


def _p(pid, hypothesis, condition, levels, measure, low, high, text):
    return Prediction(pid, hypothesis, condition, tuple(levels), measure, low, high, text)


ALL = STRENGTHS
PREDICTIONS = (
    _p("P-S1a.1", "H8", "S1a", ALL, "precision", 0.97, 1, "precision ≥ 0.97 at every level"),
    _p("P-S1a.2", "H8", "S1a", ALL, "recall", 0.97, 1, "recall ≥ 0.97 at every level"),
    _p("P-S1a.3", "H8", "S1a", ALL, "max_benign_fp", 0, 0.01, "every innocent rule's FP rate ≤ 0.01"),
    _p("P-S1b-1.1", "H1", "S1b", (0.5,), "recall", 0.60, 0.90, "recall 0.60–0.90"),
    _p("P-S1b-1.2", "H1", "S1b", (0.5,), "precision", 0.55, 0.90, "precision 0.55–0.90"),
    _p("P-S1b-1.3", "H1", "S1b", (0.5,), "fp:B-HOUSE-01", 0.04, 0.25, "B-HOUSE-01 FP rate 0.04–0.25"),
    _p("P-S1b-2.1", "H1", "S1b", (1.0,), "recall:R-RING-01", 0.30, 0.80, "R-RING-01 recall 0.30–0.80"),
    _p("P-S1b-2.2", "H1", "S1b", (1.0,), "recall:R-RING-02", 0.90, 1, "R-RING-02 recall ≥ 0.9"),
    _p("P-S1b-2.3", "H9", "S1b", (1.0,), "recall:R-RING-03", 0.30, 0.90, "R-RING-03 recall 0.30–0.90"),
    _p("P-S1c-1.1", "H1", "S1c", (0.5,), "recall", 0.55, 0.85, "recall 0.55–0.85"),
    _p("P-S1c-1.2", "H1", "S1c", (0.5,), "fp:B-HOUSE-01", 0.04, 0.25, "B-HOUSE-01 FP rate 0.04–0.25"),
    _p("P-S1c-2.1", "H9", "S1c", (1.0,), "recall", 0.10, 0.30, "recall 0.10–0.30"),
    _p("P-S1c-2.2", "H1", "S1c", (1.0,), "precision", 0.85, 1, "precision ≥ 0.85"),
    _p("P-S2-1.1", "H3", "S2", (0.5,), "recall", 0.55, 0.85, "recall 0.55–0.85"),
    _p("P-S2-1.2", "H3", "S2", (0.5,), "recall:R-RING-02", 0, 0.25, "R-RING-02 recall ≤ 0.25"),
    _p("P-S2-2.1", "H3", "S2", (1.0,), "recall", 0.15, 0.50, "recall 0.15–0.50"),
    _p("P-S2-2.2", "H3", "S2", (1.0,), "precision", 0.95, 1, "precision ≥ 0.95"),
    _p("P-S2-2.3", "H3", "S2", (1.0,), "mean_match_jaccard", 0, 0.8499, "mean match Jaccard below 0.85"),
    _p("P-S2-3", "H3", "S2", (0.25,), "recall:R-RING-02", 0, 0.60, "R-RING-02 recall ≤ 0.60"),
    _p("P-S3a.1", "H7", "S3a", ("pairs",), "recall", 0.70, 0.90, "recall 0.70–0.90"),
    _p("P-S3a.2", "H7", "S3a", ("pairs",), "recall:R-RING-02", 0, 0.10, "R-RING-02 recall ≤ 0.10"),
    _p("P-S3a.3", "H7", "S3a", ("pairs",), "min_recall:R-RING-01|R-RING-04|R-RING-05|R-RING-06", 0.90, 1,
       "R-RING-01, -04, -05 and -06 recall ≥ 0.9"),
    _p("P-S3b.1", "H6", "S3b", ("large",), "recall", 0.30, 0.80, "recall 0.30–0.80"),
    _p("P-S3b.2", "H6", "S3b", ("large",), "precision", 0.55, 0.90, "precision 0.55–0.90"),
    _p("P-S3c-1.1", "H4", "S3c", ("x2",), "recall", 0.95, 1, "recall ≥ 0.95"),
    _p("P-S3c-1.2", "H4", "S3c", ("x2",), "precision", 0.95, 1, "precision ≥ 0.95"),
    _p("P-S3c-2.1", "H4", "S3c", ("x3",), "recall", 0.85, 0.99, "recall 0.85–0.99 at 3×"),
    _p("P-S3c-2.2", "H4", "S3c", ("x4",), "recall", 0.80, 0.97, "recall 0.80–0.97 at 4×"),
    _p("P-S3c-2.3", "H4", "S3c", ("x3", "x4"), "single_id_share", 0.5, 1,
       "most missed rings are single-identifier R-RING-01 rings"),
    _p("P-S3c-2.4", "H4", "S3c", ("x3", "x4"), "precision", 0.95, 1, "precision ≥ 0.95"),
    _p("P-S4a.1", "H5", "S4a", ("B-ROOM-01",), "fp:B-ROOM-01", 0.30, 0.65, "B-ROOM-01 FP rate 0.30–0.65"),
    _p("P-S4a.2", "H5", "S4a", ("B-ROOM-01",), "recall", 0.97, 1, "recall ≥ 0.97"),
    _p("P-S4b.1", "H5", "S4b", ("B-FAMILY-02",), "fp:B-FAMILY-02", 0.80, 1, "B-FAMILY-02 FP rate ≥ 0.80"),
    _p("P-S4b.2", "H5", "S4b", ("B-FAMILY-02",), "precision", 0.45, 0.75, "precision 0.45–0.75"),
    _p("P-S4c.1", "H4", "S4c", ("B-FLEET-01",), "fp:B-FLEET-01", 0, 0.30, "B-FLEET-01 FP rate ≤ 0.30"),
    _p("P-S4c.2", "H4", "S4c", ("B-FLEET-01",), "recall", 0.85, 0.99, "recall 0.85–0.99"),
    _p("P-S4d.1", "H5", "S4d", ("B-AGENT-01",), "fp:B-AGENT-01", 0.80, 1, "B-AGENT-01 FP rate ≥ 0.80"),
    _p("P-S4d.2", "H5", "S4d", ("B-AGENT-01",), "precision", 0.45, 0.75, "precision 0.45–0.75"),
    _p("P-S5a.1", "H8", "S5a", ALL, "recall", 0.97, 1, "recall ≥ 0.97 at every level"),
    _p("P-S5a.2", "H8", "S5a", ALL, "precision", 0.97, 1, "precision ≥ 0.97 at every level"),
    _p("P-S5b.1", "H4", "S5b", (1.0,), "recall", 0.65, 0.90, "recall 0.65–0.90"),
    _p("P-S5b.2", "H4", "S5b", (1.0,), "recall:R-RING-04", 0, 0.25, "R-RING-04 recall ≤ 0.25"),
    _p("P-S5b.3", "H4", "S5b", (1.0,), "recall:R-RING-06", 0.90, 1, "R-RING-06 recall ≥ 0.9"),
    _p("P-S5c-1", "H2", "S5c", (0.25,), "precision", 0, 0.70, "precision ≤ 0.70"),
    _p("P-S5c-2.1", "H2", "S5c", (1.0,), "precision", 0, 0.40, "precision ≤ 0.40"),
    _p("P-S5c-2.2", "H2", "S5c", (1.0,), "recall", 0.60, 0.90, "recall 0.60–0.90"),
    _p("P-S0", "H8", "S0", ("no fraud",), "flagged_max", 0, 1, "at most 1 flagged network per seed"),
)
EXPECTED_SENSITIVE = {"score.flag_threshold", "links.caps.SHARED_BANK", "links.caps.SHARED_PHONE",
                      "links.caps.SHARED_EMAIL", "links.caps.SIMILAR_NARRATIVE", "links.story_min_similarity",
                      "rarity.reference_log10"}
HYPOTHESES = {
    "H1": "Messy addresses turn some families into false alarms.",
    "H2": "Placeholder narratives create false story links.",
    "H3": "Reworded stories escape.",
    "H4": "Rarity hides single-identifier rings when sharing becomes common.",
    "H5": "Unrelated co-residents and boilerplate filers are flagged.",
    "H6": "Big rings fragment.",
    "H7": "Two-person story or timing rings are missed by design.",
    "H8": "Cosmetic mess and gaps in the relationship records do not matter.",
    "H9": "Timing rings depend on their shared phone.",
}


def _check(prediction: Prediction, by_condition: dict[str, list[dict]]) -> dict:
    actual = {}
    for level in prediction.levels:
        runs = by_condition.get(Scenario(prediction.condition, level).label, [])
        actual[str(level)] = metric(runs, prediction.measure) if runs else None
    hit = all(value is not None and prediction.low <= value <= prediction.high for value in actual.values())
    return {"pid": prediction.pid, "hypothesis": prediction.hypothesis, "condition": prediction.condition,
            "levels": [str(level) for level in prediction.levels], "measure": prediction.measure,
            "predicted": prediction.text, "low": prediction.low, "high": prediction.high, "actual": actual, "hit": hit}


def _threshold_checks(sweep: list[dict]) -> list[dict]:
    plateau = [row for row in sweep if 0.42 < row["threshold"] <= 0.65]
    above = next(row for row in sweep if row["threshold"] == 0.70)
    return [
        {"pid": "P-T1.1", "hypothesis": "-", "condition": "threshold sweep", "levels": ["dev seed"],
         "measure": "precision and recall", "predicted": "both 1.000 for every threshold in (0.42, 0.65]",
         "actual": {str(row["threshold"]): f"{row['precision']}/{row['recall']}" for row in plateau},
         "hit": all(row["precision"] == 1.0 and row["recall"] == 1.0 for row in plateau)},
        {"pid": "P-T1.2", "hypothesis": "-", "condition": "threshold sweep", "levels": ["dev seed"],
         "measure": "recall", "predicted": "recall falls once the threshold passes 0.65",
         "actual": {"0.7": above["recall"]}, "hit": above["recall"] is not None and above["recall"] < 1.0},
    ]


def _sensitivity_checks(rows: list[dict], baseline: dict) -> tuple[list[str], list[dict]]:
    sensitive = sorted({row["setting"] for row in rows
                        if abs((row["precision"] or 0) - (baseline["precision"] or 0)) > SENSITIVE_CHANGE
                        or abs((row["recall"] or 0) - (baseline["recall"] or 0)) > SENSITIVE_CHANGE})
    return sensitive, [
        {"pid": "P-T2.1", "hypothesis": "-", "condition": "settings ±30%", "levels": ["dev seed"],
         "measure": "settings that move precision or recall by more than 0.05", "predicted": "no more than 6",
         "actual": {"count": len(sensitive)}, "hit": len(sensitive) <= 6},
        {"pid": "P-T2.2", "hypothesis": "-", "condition": "settings ±30%", "levels": ["dev seed"],
         "measure": "which settings", "predicted": "all from the expected list",
         "actual": {"unexpected": [name for name in sensitive if name not in EXPECTED_SENSITIVE]},
         "hit": all(name in EXPECTED_SENSITIVE for name in sensitive)},
    ]


def summarise(runs: list[dict]) -> dict:
    by_condition: dict[str, list[dict]] = {}
    for run in sorted(runs, key=lambda item: (item["condition"], item["seed"])):
        by_condition.setdefault(run["condition"], []).append(run)
    table = {}
    for condition, items in by_condition.items():
        rules = sorted({rule for item in items for rule in item["per_rule"]})
        table[condition] = {
            "seeds": [item["seed"] for item in items],
            **{name: {"mean": metric(items, name), "std": _spread([item[name] for item in items])}
               for name in ("precision", "recall", "mean_match_jaccard", "max_benign_fp", "flagged_networks")},
            "per_rule": {rule: metric(items, ("recall:" if rule.startswith(("R-", "EC-3")) else "fp:") + rule)
                         for rule in rules},
            "capacity": {cutoff: _mean([item["capacity"][cutoff] for item in items]) for cutoff in map(str, CAPACITY)},
            "fraud_groups": _mean([item["fraud_groups"] for item in items]),
        }
    return {"by_condition": by_condition, "table": table,
            "predictions": [_check(prediction, by_condition) for prediction in PREDICTIONS]}


def run_stress(seeds=STRESS_SEEDS, workers: int | None = None, sensitivity: bool = True) -> dict:
    tasks = [(seed, scenario.name if scenario else None, scenario.level if scenario else None)
             for scenario in conditions() for seed in seeds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        runs = []
        for done, run in enumerate(pool.map(run_condition, tasks), start=1):
            runs.append(run)
            if done % 20 == 0 or done == len(tasks):
                print(f"stress runs: {done} of {len(tasks)}", file=sys.stderr, flush=True)
        settings, config_sha = load_config()
        development = run_condition((DEFAULT_SEED, None, None))
        sensitivity_rows = []
        if sensitivity:
            sensitivity_tasks = [(path, factor) for path in numeric_settings(settings)
                                 for factor in (1 - SENSITIVITY_STEP, 1 + SENSITIVITY_STEP)]
            sensitivity_rows = list(pool.map(_sensitivity_task, sensitivity_tasks))
    summary = summarise(runs)
    summary["predictions"] += _threshold_checks(development["sweep"])
    sensitive, checks = _sensitivity_checks(sensitivity_rows, development) if sensitivity else ([], [])
    summary["predictions"] += checks
    return {"frozen_commit": FROZEN_COMMIT, "config_sha256": config_sha, "seeds": list(seeds),
            "development": development, "sensitivity": {"rows": sensitivity_rows, "sensitive": sensitive},
            **summary}


def hypotheses_verdicts(predictions: list[dict]) -> dict[str, dict]:
    verdicts = {}
    for key, text in HYPOTHESES.items():
        related = [item for item in predictions if item["hypothesis"] == key]
        verdicts[key] = {"text": text, "predictions": len(related), "hits": sum(item["hit"] for item in related)}
    return verdicts


def write_json(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


__all__ = ["STRESS_SEEDS", "CONFIRMATION_SEEDS", "PREDICTIONS", "TITLES", "run_stress", "summarise",
           "hypotheses_verdicts", "write_json", "run_condition", "detect_and_score", "metric"]
