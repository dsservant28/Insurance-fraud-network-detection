"""One command for the whole pipeline: python -m fraudnet.run --seed 20261022 --scale 1.0 --out data/output

Stages, in order:
1. Generate: input files, hidden labels and the source manifest.
2. Validate: 12 checks plus the data_exception list. Optionally, regenerate twice and compare checksums.
3. Detect: rebuilt links, scored networks and explanations. Reads input only.
4. Seed demo investigation cases.
5. Evaluate against the labels. The only stage that reads them.

Each stage also has its own command (see README).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fraudnet.detect.__main__ import detect
from fraudnet.evaluate.report import write_report
from fraudnet.evaluate.run import aggregate, evaluate_dataset, evaluate_seeds
from fraudnet.generate.__main__ import run as generate_into
from fraudnet.generate.config import DEFAULT_SEED
from fraudnet.investigate.demo import DemoClock, seed_demo
from fraudnet.investigate.schema import connect
from fraudnet.investigate.workflow import Workflow
from fraudnet.validate.__main__ import validate
from fraudnet.validate.reproducibility import check_reproducibility


def run(seed: int, scale: float, out: Path, reproducibility: bool = False, unseen_seeds: list[int] | None = None,
        demo_cases: bool = True, say=print, evaluate: bool = True) -> dict:
    out = Path(out)
    say(f"1/5 generate  seed {seed}, scale {scale} -> {out}")
    manifest = generate_into(seed, scale, out)
    rows = {item["table"]: item["rows"] for item in manifest["files"] if item["path"].startswith("csv/")}
    say(f"    {rows.get('claimant', 0):,} claimants, {rows.get('claim', 0):,} claims, "
        f"{rows.get('provider', 0):,} providers, {rows.get('relationship_edge', 0):,} relationship edges")

    say("2/5 validate")
    summary = validate(out)
    failed = [check["id"] for check in summary["checks"] if check["status"] != "PASS"]
    say(f"    {len(summary['checks']) - len(failed)} of {len(summary['checks'])} checks pass; "
        f"exceptions reported: {summary['exceptions']}")
    result = {"validation": summary["status"]}
    if reproducibility:
        report = check_reproducibility(seed, scale, compare_with=out)
        (out / "reports" / "reproducibility_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                                   encoding="utf-8")
        say(f"    reproducibility {report['status']}: {report['files_identical']}/{report['files_compared']} files identical")
        result["reproducibility"] = report["status"]

    say("3/5 detect")
    detect(out)
    run_info = json.loads((out / "detect" / "detector_run.json").read_text(encoding="utf-8"))
    counts = run_info["counts"]
    say(f"    {run_info['run_id']}: {counts['networks']} networks, {counts['flagged_networks']} flagged, "
        f"{counts['cleared_groups']} look-alike groups cleared")

    if demo_cases:
        say("4/5 investigate  seed demo cases")
        connection = connect(out / "fraudnet.db")
        opened = seed_demo(Workflow(connection, clock=DemoClock()))
        connection.close()
        say(f"    cases opened: {', '.join(opened) if opened else 'none'}")
    else:
        say("4/5 investigate  skipped")

    result["run_id"] = run_info["run_id"]
    if not evaluate:  # the hosted app reads the committed evaluation summaries instead
        say("5/5 evaluate  skipped")
        return result
    say("5/5 evaluate")
    development = evaluate_dataset(out, with_comparisons=True)
    results = evaluate_seeds(unseen_seeds, scale) if unseen_seeds else []
    command = "python -m fraudnet.run " + " ".join(sys.argv[1:])
    write_report(out / "evaluation", development, results, aggregate(results) if results else None, command.strip())
    detector = development["detector"]
    say(f"    precision {detector['precision']}, ring recall {detector['recall']}, "
        f"look-alike FP rate {detector['false_positive_rate']}; report: {out / 'evaluation'}")
    result.update({"run_id": run_info["run_id"], "precision": detector["precision"], "recall": detector["recall"]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run every stage: generate, validate, detect, investigate, evaluate.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=Path("data/output"))
    parser.add_argument("--reproducibility", action="store_true", help="regenerate twice and compare every file")
    parser.add_argument("--unseen-seeds", type=int, nargs="*", default=[],
                        help="also evaluate these seeds (docs/EVALUATION.md uses 606 707 808 909 1010)")
    parser.add_argument("--no-demo-cases", action="store_true", help="don't seed demo investigation cases")
    args = parser.parse_args()
    result = run(args.seed, args.scale, args.out, args.reproducibility, args.unseen_seeds, not args.no_demo_cases)
    ok = result["validation"] == "PASS" and result.get("reproducibility", "PASS") == "PASS"
    print(f"Done: {'PASS' if ok else 'FAIL'}. Open the app with: streamlit run streamlit_app.py")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
