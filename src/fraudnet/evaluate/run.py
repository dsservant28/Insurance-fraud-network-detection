"""Evaluate one dataset, or many seeds, and aggregate the results."""
from __future__ import annotations

import json
import statistics
import tempfile
from pathlib import Path

import pandas as pd

from fraudnet.detect.__main__ import detect
from fraudnet.detect.config import DEFAULT_CONFIG, load_config
from fraudnet.detect.links import rebuild_links
from fraudnet.evaluate import checks, comparisons
from fraudnet.evaluate.metrics import Ranked, labelled_groups, read_labels, score
from fraudnet.generate.__main__ import run as generate_into
from fraudnet.inputs import load_input, manifest_sha256

DETECT_FILES = ("network", "network_member", "fraud_indicator", "detected_edge")
HEADLINE = ("precision", "recall", "fraud_group_recall", "false_positive_rate", "false_negative_rate",
            "average_precision", "r_precision", "ndcg_at_r", "precision_at_10", "mean_match_jaccard")


def _read_detect(data_dir: Path) -> dict[str, pd.DataFrame]:
    return {name: pd.read_csv(data_dir / "detect" / f"{name}.csv", dtype=str, keep_default_na=False)
            for name in DETECT_FILES}


def ranked_from_output(detect_tables: dict[str, pd.DataFrame]) -> list[Ranked]:
    """The detector's written output, in rank order: exactly what an analyst would see."""
    members = detect_tables["network_member"]
    claimants = members[members["member_role"] == "CLAIMANT"].groupby("network_id")["node_id"].apply(frozenset)
    network = detect_tables["network"].assign(rank=lambda frame: frame["rank"].astype(int)).sort_values("rank")
    return [Ranked(row.network_id, claimants[row.network_id], row.flagged == "1") for row in network.itertuples()]


def _provider_false_alarms(labels: pd.DataFrame, detect_tables: dict[str, pd.DataFrame]) -> dict:
    """B-PROV-01 has no claimants, so it's checked through network context members instead."""
    popular = set(labels.loc[(labels["rule_id"] == "B-PROV-01") & (labels["entity_type"] == "PROVIDER"), "entity_id"])
    network, members = detect_tables["network"], detect_tables["network_member"]
    flagged = set(network.loc[network["flagged"] == "1", "network_id"])
    hits = members[members["network_id"].isin(flagged) & members["node_id"].isin(popular)]
    return {"popular_providers": len(popular), "in_flagged_networks": int(hits["node_id"].nunique()),
            "false_positive_rate": round(hits["node_id"].nunique() / len(popular), 4) if popular else None}


def evaluate_dataset(data_dir: Path, with_comparisons: bool = True) -> dict:
    """Score the detector output in <data_dir>/detect against <data_dir>/hidden."""
    data_dir = Path(data_dir)
    run_file = data_dir / "detect" / "detector_run.json"
    current = run_file.exists() and json.loads(run_file.read_text(encoding="utf-8"))["input_manifest_sha256"] \
        == manifest_sha256(data_dir / "input")
    if not current:  # Never score output that belongs to other input data.
        detect(data_dir)
    tables, manifest = load_input(data_dir / "input")
    labels = read_labels(data_dir)
    groups = labelled_groups(labels)
    detect_tables = _read_detect(data_dir)
    detector = score(ranked_from_output(detect_tables), groups)
    detector["per_rule"]["B-PROV-01"] = _provider_false_alarms(labels, detect_tables)
    result = {
        "seed": manifest["generator"]["seed"], "scale": manifest["generator"]["scale"],
        "labelled_groups": {kind: sum(group.kind == kind for group in groups) for kind in ("RING", "BENIGN", "EDGE_CASE")},
        "detector": detector,
        "edge_cases": checks.edge_cases(tables, labels, detect_tables, detector),
        "exceptions": checks.reconcile_exceptions(tables, labels),
        "explanations": checks.explanation_check(tables, detect_tables),
    }
    if with_comparisons:
        settings, _ = load_config(DEFAULT_CONFIG)
        links = rebuild_links(tables, settings).links
        result["comparisons"] = {
            "any_shared_value": score(comparisons.any_shared_value(links), groups),
            "recorded_edges_only": score(comparisons.recorded_edges_only(tables), groups),
        }
        result["principles_off"] = {name: score(comparisons.ranked_detector(tables, comparisons.principle_off(settings, name)), groups)
                                    for name in comparisons.PRINCIPLES}
    return result


def _summary(values: list[float | None]) -> dict:
    present = [value for value in values if value is not None]
    if not present:
        return {"mean": None, "std": None, "min": None, "max": None}
    return {"mean": round(statistics.fmean(present), 4),
            "std": round(statistics.pstdev(present), 4) if len(present) > 1 else 0.0,
            "min": round(min(present), 4), "max": round(max(present), 4)}


def aggregate(results: list[dict]) -> dict:
    """Mean, standard deviation and range of headline metrics across seeds, for every method."""
    def collect(pick):
        return {metric: _summary([pick(result).get(metric) for result in results]) for metric in HEADLINE}
    summary = {"seeds": [result["seed"] for result in results], "detector": collect(lambda result: result["detector"])}
    if all("comparisons" in result for result in results):
        summary["comparisons"] = {name: collect(lambda result, name=name: result["comparisons"][name])
                                  for name in comparisons.COMPARISONS}
        summary["principles_off"] = {name: collect(lambda result, name=name: result["principles_off"][name])
                                     for name in comparisons.PRINCIPLES}
    rules = sorted({rule for result in results for rule in result["detector"]["per_rule"]})
    summary["per_rule"] = {}
    for rule in rules:
        key = "recall" if rule.startswith(("R-", "EC-3")) else "false_positive_rate"
        summary["per_rule"][rule] = {key: _summary([result["detector"]["per_rule"].get(rule, {}).get(key)
                                                    for result in results])}
    summary["checks_passed"] = {
        name: all(result[section][name]["status"] == "PASS" for result in results)
        for section, names in (("edge_cases", ("EC-1", "EC-2", "EC-3", "EC-4", "EC-5")),)
        for name in names}
    summary["checks_passed"]["exceptions_reconciled"] = all(
        item["status"] == "PASS" for result in results for item in result["exceptions"].values())
    summary["checks_passed"]["explanations"] = all(result["explanations"]["status"] == "PASS" for result in results)
    return summary


def evaluate_seeds(seeds: list[int], scale: float, workdir: Path | None = None, with_comparisons: bool = True) -> list[dict]:
    """Generate, detect and evaluate each unseen seed in a scratch folder."""
    results = []
    with tempfile.TemporaryDirectory(prefix="fraudnet-eval-") as scratch:
        base = Path(workdir) if workdir else Path(scratch)
        for seed in seeds:
            folder = base / f"seed-{seed}"
            generate_into(seed, scale, folder)
            detect(folder, database=False)
            results.append(evaluate_dataset(folder, with_comparisons))
    return results
