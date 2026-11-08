"""Stress evaluation logic: prediction checks, aggregation and the report, on made-up run results."""
import pytest

from fraudnet.evaluate.stress import (
    PREDICTIONS, Prediction, _check, _moved, _sensitivity_checks, _threshold_checks, conditions, metric,
    numeric_settings, run_condition, summarise,
)
from fraudnet.evaluate.stress_report import markdown
from fraudnet.detect.config import load_config
from fraudnet.generate.scenario import LEVELS


def _run(condition, seed, precision=1.0, recall=1.0, per_rule=None, flagged=10, misses=()):
    rules = {"R-RING-01": {"recall": recall}, "B-HOUSE-01": {"false_positive_rate": 0.0}, **(per_rule or {})}
    return {"condition": condition, "seed": seed, "precision": precision, "recall": recall,
            "mean_match_jaccard": 0.95, "max_benign_fp": max(item.get("false_positive_rate", 0) or 0
                                                             for item in rules.values()),
            "flagged_networks": flagged, "per_rule": rules, "capacity": {"10": 9, "20": 12, "50": 12},
            "fraud_groups": 12, "gallery": {"missed_rings": list(misses), "false_alarms": []},
            "sweep": [{"threshold": 0.6, "flagged": flagged, "precision": precision, "recall": recall}]}


def test_every_registered_prediction_names_a_real_condition_and_range():
    assert len(PREDICTIONS) == len({item.pid for item in PREDICTIONS})
    for item in PREDICTIONS:
        assert item.condition in LEVELS and all(level in LEVELS[item.condition] for level in item.levels)
        assert 0 <= item.low <= item.high


def test_a_prediction_hits_only_inside_its_range_at_every_level():
    prediction = Prediction("P-X", "H1", "S1a", (0.5, 1.0), "precision", 0.9, 1.0, "precision ≥ 0.9")
    good = {"S1a@0.5": [_run("S1a@0.5", 1, 0.95), _run("S1a@0.5", 2, 0.93)], "S1a@1.0": [_run("S1a@1.0", 1, 0.91)]}
    assert _check(prediction, good)["hit"]
    bad = {**good, "S1a@1.0": [_run("S1a@1.0", 1, 0.95), _run("S1a@1.0", 2, 0.80)]}  # mean 0.875
    result = _check(prediction, bad)
    assert not result["hit"] and result["actual"]["1.0"] == 0.875
    assert not _check(prediction, {})["hit"]  # a condition that never ran is a miss, not a pass


def test_metrics_read_rules_minimums_and_flag_counts():
    runs = [_run("S3a@pairs", 1, per_rule={"R-RING-04": {"recall": 0.5}}, flagged=0),
            _run("S3a@pairs", 2, per_rule={"R-RING-04": {"recall": 1.0}}, flagged=2)]
    assert metric(runs, "recall:R-RING-04") == 0.75
    assert metric(runs, "min_recall:R-RING-01|R-RING-04") == 0.75
    assert metric(runs, "flagged_max") == 2 and metric(runs, "fp:B-HOUSE-01") == 0.0


def test_single_identifier_share_counts_r_ring_01_misses_with_one_shared_field():
    misses = [{"rule_id": "R-RING-01", "label_reason": "... share bank_token ACCT-1."},
              {"rule_id": "R-RING-01", "label_reason": "... share phone 1; email 2."},
              {"rule_id": "R-RING-03", "label_reason": "..."}]
    assert metric([_run("S3c@x3", 1, misses=misses)], "single_id_share") == round(1 / 3, 4)


def test_threshold_and_sensitivity_checks():
    sweep = [{"threshold": t, "flagged": 1, "precision": 1.0, "recall": 1.0 if t <= 0.65 else 0.8}
             for t in (0.45, 0.5, 0.55, 0.6, 0.65, 0.7)]
    assert all(item["hit"] for item in _threshold_checks(sweep))
    rows = [{"setting": "score.flag_threshold", "precision": 1.0, "recall": 0.7},
            {"setting": "network.max_claimants", "precision": 0.9, "recall": 1.0},
            {"setting": "rarity.floor", "precision": 1.0, "recall": 0.98}]
    sensitive, checks = _sensitivity_checks(rows, {"precision": 1.0, "recall": 1.0})
    assert sensitive == ["network.max_claimants", "score.flag_threshold"]
    assert checks[0]["hit"] and not checks[1]["hit"] and checks[1]["actual"]["unexpected"] == ["network.max_claimants"]


def test_settings_move_within_their_valid_ranges():
    settings, _ = load_config()
    paths = numeric_settings(settings)
    assert ("score", "flag_threshold") in paths and ("network", "louvain_seed") not in paths
    assert _moved(0.95, 1.3, ("explanations", "busy_provider_percentile")) == 0.99
    assert _moved(0.85, 1.3, ("links", "caps", "SHARED_BANK")) == 1.0
    assert _moved(3, 0.7, ("network", "repetition_min_claimants")) == 2
    assert _moved(1.5, 1.3, ("rarity", "reference_log10")) == pytest.approx(1.95)


def test_summary_and_report_cover_every_condition():
    runs = [_run(condition, seed) for condition in ("baseline", "S1a@0.5") for seed in (1, 2)]
    summary = summarise(runs)
    assert set(summary["table"]) == {"baseline", "S1a@0.5"}
    result = {**summary, "frozen_commit": "a" * 40, "config_sha256": "b" * 64, "seeds": [1, 2],
              "development": {"sweep": [{"threshold": 0.6, "flagged": 1, "precision": 1.0, "recall": 1.0}],
                              "precision": 1.0, "recall": 1.0},
              "sensitivity": {"rows": [], "sensitive": []}}
    text = markdown(result, "python -m fraudnet.evaluate stress")
    assert "Predictions hit:" in text and "S1a Cosmetic identifier formats: 0.5" in text and "**MISS**" in text
    assert len(conditions()) == 1 + sum(len(levels) for levels in LEVELS.values())


def test_one_condition_runs_end_to_end_on_a_non_stress_seed():
    result = run_condition((42, "S0", "no fraud"))
    assert result["condition"] == "S0@no fraud" and result["recall"] is None
    assert result["gallery"] == {"missed_rings": [], "false_alarms": []} and len(result["sweep"]) == 14
