"""The evaluator: matching, metrics, edge-case checks and the full command (DATA_DICTIONARY section 13)."""
import json
import subprocess
import sys

import pytest

from fraudnet.evaluate.metrics import LabelledGroup, Ranked, jaccard, match, score
from fraudnet.evaluate.run import aggregate, evaluate_dataset
from fraudnet.generate.__main__ import run as generate_into


def _group(group_id, rule, fraud, *members):
    return LabelledGroup(group_id, rule, fraud, frozenset(members))


def _net(network_id, flagged, *members):
    return Ranked(network_id, frozenset(members), flagged)


GROUPS = [_group("RING-001", "R-RING-01", True, "A", "B", "C"), _group("RING-002", "R-RING-02", True, "D", "E", "F"),
          _group("GRP-0001", "B-HOUSE-01", False, "G", "H")]


def test_jaccard_and_the_match_threshold():
    assert jaccard(frozenset("AB"), frozenset("BC")) == 1 / 3
    rows = match([_net("N1", True, "A", "B", "X"), _net("N2", True, "D", "X", "Y", "Z")], GROUPS)
    assert rows[0]["group_id"] == "RING-001" and rows[1]["group_id"] is None  # 1/6 is below 0.5


def test_each_group_matches_one_network_only():
    rows = match([_net("N1", True, "A", "B", "C"), _net("N2", True, "A", "B")], GROUPS)
    assert [row["group_id"] for row in rows] == ["RING-001", None]


def test_pieces_of_a_ring_stay_false_alarms_but_are_counted_as_fragments():
    ranked = [_net("N1", True, "A", "B", "C"), _net("N2", True, "D", "E"), _net("N3", True, "D", "X"),
              _net("N4", True, "E", "F")]
    result = score(ranked, GROUPS)
    # N2 matches RING-002 (2/3); N4 is a second piece of RING-002, so it is a fragment; N3 holds an outsider.
    assert result["precision"] == 0.5 and result["fragment_networks"] == 1
    assert result["precision_counting_fragments"] == 0.75


def test_metrics_count_false_alarms_and_misses():
    ranked = [_net("N1", True, "A", "B", "C"), _net("N2", True, "G", "H"), _net("N3", False, "D", "E", "F")]
    result = score(ranked, GROUPS)
    assert result["precision"] == 0.5 and result["recall"] == 0.5
    assert result["false_positive_rate"] == 1.0 and result["false_negative_rate"] == 0.5
    assert result["average_precision"] == round((1 / 1 + 2 / 3) / 2, 4)
    assert result["per_rule"]["R-RING-02"]["recall"] == 0.0 and result["per_rule"]["B-HOUSE-01"]["false_positive_rate"] == 1.0


def test_perfect_ranking_scores_one():
    result = score([_net("N1", True, "A", "B", "C"), _net("N2", True, "D", "E", "F")], GROUPS)
    assert result["precision"] == result["recall"] == result["average_precision"] == result["r_precision"] == 1.0
    assert result["ndcg_at_r"] == 1.0 and result["false_positive_rate"] == 0.0


# ---- on generated data

@pytest.fixture(scope="module")
def evaluated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("evaluated")
    generate_into(20261022, 0.1, folder)
    return folder, evaluate_dataset(folder)


def test_detector_meets_its_targets_on_the_sample(evaluated):
    _, result = evaluated
    detector = result["detector"]
    assert detector["recall"] >= 0.9 and detector["false_positive_rate"] <= 0.05 and detector["precision"] >= 0.85


def test_every_edge_case_and_check_passes(evaluated):
    _, result = evaluated
    assert {case: item["status"] for case, item in result["edge_cases"].items()} == dict.fromkeys(
        ("EC-1", "EC-2", "EC-3", "EC-4", "EC-5"), "PASS")
    assert all(item["status"] == "PASS" for item in result["exceptions"].values())
    assert result["explanations"]["status"] == "PASS"


def test_the_full_detector_beats_every_comparison(evaluated):
    _, result = evaluated
    detector = result["detector"]
    for name, item in {**result["comparisons"], **result["principles_off"]}.items():
        precision, recall = item["precision"] or 0.0, item["recall"] or 0.0
        assert detector["precision"] >= precision and detector["recall"] >= recall, name
        assert detector["precision"] > precision or detector["recall"] > recall, name


def test_aggregate_reports_mean_and_spread(evaluated):
    _, result = evaluated
    summary = aggregate([result, result])
    assert summary["detector"]["recall"]["mean"] == result["detector"]["recall"]
    assert summary["detector"]["recall"]["std"] == 0.0 and summary["checks_passed"]["EC-4"] is True


def test_command_writes_the_report(evaluated, tmp_path):
    folder, _ = evaluated
    doc = tmp_path / "EVALUATION.md"
    result = subprocess.run([sys.executable, "-m", "fraudnet.evaluate", "--data", str(folder), "--seeds",
                             "--no-comparisons", "--doc", str(doc)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((folder / "evaluation/evaluation_report.json").read_text(encoding="utf-8"))
    assert report["development"]["detector"]["recall"] == 1.0
    assert "# Evaluation report" in doc.read_text(encoding="utf-8")
    assert (folder / "evaluation/network_matches.csv").exists()
