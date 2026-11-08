"""The one-command pipeline: every stage runs in order and leaves its outputs."""
import json

from fraudnet.run import run


def test_one_command_runs_every_stage(tmp_path):
    lines = []
    result = run(20261022, 0.1, tmp_path, reproducibility=False, unseen_seeds=[], demo_cases=True, say=lines.append)
    assert result["validation"] == "PASS" and result["precision"] == 1.0 and result["recall"] == 1.0
    assert [line[:3] for line in lines if line[1:2] == "/"] == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    for path in ("input/input_manifest.json", "hidden/ground_truth.csv", "reports/validation_summary.json",
                 "reports/source_manifest.json", "detect/network.csv", "evaluation/evaluation_report.json", "fraudnet.db"):
        assert (tmp_path / path).exists(), path
    run_info = json.loads((tmp_path / "detect" / "detector_run.json").read_text(encoding="utf-8"))
    assert run_info["run_id"] == result["run_id"]
