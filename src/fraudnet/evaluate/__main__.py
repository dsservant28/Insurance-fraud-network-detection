"""Command line: python -m fraudnet.evaluate --data data/output [--seeds 606 707 808 909 1010] [--doc docs/EVALUATION.md]
              python -m fraudnet.evaluate stress [--seeds ...] [--predictions v0.2] [--compare FILE] [--doc FILE]

Scores <data>/detect against <data>/hidden, then generates, detects and scores each unseen seed at
the same scale. Writes <data>/evaluation/. `stress` runs the stress test in docs/STRESS_PLAN.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fraudnet.evaluate.report import write_report
from fraudnet.evaluate.stress import write_json


def summary_for_app(development: dict, unseen: dict | None) -> dict:
    """Only aggregate results: headline measures, comparisons, principle-off runs and edge-case checks."""
    pick = ("precision", "recall", "false_positive_rate", "r_precision", "mean_match_jaccard")
    out = {"development": {"seed": development["seed"], **{k: development["detector"][k] for k in pick},
                           "flagged_networks": development["detector"]["flagged_networks"],
                           "edge_cases": {k: {"rule": v["rule"], "status": v["status"]} for k, v in development["edge_cases"].items()},
                           "comparisons": {k: {m: v[m] for m in ("precision", "recall")} for k, v in development.get("comparisons", {}).items()},
                           "principles_off": {k: {m: v[m] for m in ("precision", "recall")} for k, v in development.get("principles_off", {}).items()}}}
    if unseen:
        mean = lambda block: {m: block[m]["mean"] for m in ("precision", "recall")}  # noqa: E731
        out["unseen"] = {"seeds": unseen["seeds"], **{k: unseen["detector"][k]["mean"] for k in pick},
                         "comparisons": {k: mean(v) for k, v in unseen.get("comparisons", {}).items()},
                         "principles_off": {k: mean(v) for k, v in unseen.get("principles_off", {}).items()},
                         "checks_passed": unseen["checks_passed"]}
    return out
from fraudnet.evaluate.run import aggregate, evaluate_dataset, evaluate_seeds

# Never looked at while designing or tuning the detector. 777 and 4242 (D-028) and 101-505 (D-029) were
# looked at during fixes, so they are retired as test seeds.
UNSEEN_SEEDS = (606, 707, 808, 909, 1010)


def stress(args) -> None:
    """python -m fraudnet.evaluate stress [--seeds ...] [--workers N] [--doc docs/STRESS.md]"""
    from fraudnet.evaluate.stress import STRESS_SEEDS, run_stress, write_json
    from fraudnet.evaluate.stress_report import write_stress_report

    sys.stdout.reconfigure(errors="replace")  # the Windows console can't print every symbol in the predictions
    seeds = args.seeds if args.seeds_given else list(STRESS_SEEDS)
    result = run_stress(seeds, workers=args.workers, sensitivity=not args.no_sensitivity, predictions=args.predictions)
    write_json(result, args.data / "evaluation" / f"stress_{args.predictions}.json")
    command = "python -m fraudnet.evaluate " + " ".join(sys.argv[1:])
    compare = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    write_stress_report(result, command.strip(), args.doc or args.data / "evaluation" / "stress_report.md", compare)
    hits = sum(item["hit"] for item in result["predictions"])
    print(f"Stress seeds {seeds}: predictions hit {hits} of {len(result['predictions'])}")
    for item in result["predictions"]:
        print(f"  {'HIT ' if item['hit'] else 'MISS'} {item['pid']:<10} {item['predicted']}  actual {item['actual']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate detector output against the hidden labels.")
    parser.add_argument("command", nargs="?", choices=("stress",), help="stress: run the stress test (STRESS_PLAN.md)")
    parser.add_argument("--data", type=Path, default=Path("data/output"))
    parser.add_argument("--seeds", type=int, nargs="*", default=None,
                        help="seeds to generate and score at the same scale (none: development seed only)")
    parser.add_argument("--no-comparisons", action="store_true", help="skip comparison methods and principle-off runs")
    parser.add_argument("--doc", type=Path, help="also write the Markdown report here")
    parser.add_argument("--workers", type=int, help="stress: parallel worker processes")
    parser.add_argument("--no-sensitivity", action="store_true", help="stress: skip the setting sensitivity runs")
    parser.add_argument("--predictions", choices=("v0.1", "v0.2"), default="v0.1",
                        help="stress: which registered prediction set to check")
    parser.add_argument("--compare", type=Path, help="stress: an earlier version's summary to show side by side")
    args = parser.parse_args()
    args.seeds_given = args.seeds is not None
    if args.command == "stress":
        stress(args)
        return
    if args.seeds is None:
        args.seeds = list(UNSEEN_SEEDS)

    with_comparisons = not args.no_comparisons
    development = evaluate_dataset(args.data, with_comparisons)
    scale = json.loads((args.data / "input/input_manifest.json").read_text(encoding="utf-8"))["generator"]["scale"]
    results = evaluate_seeds(args.seeds, scale, with_comparisons=with_comparisons) if args.seeds else []
    unseen = aggregate(results) if results else None
    command = "python -m fraudnet.evaluate " + " ".join(sys.argv[1:])
    write_report(args.data / "evaluation", development, results, unseen, command.strip(), args.doc)
    if args.doc:  # a compact, committed summary beside the report: the app's Evaluation lab reads it
        write_json(summary_for_app(development, unseen), args.doc.with_suffix(".json"))

    detector = development["detector"]
    print(f"Development seed {development['seed']}: precision {detector['precision']}, ring recall {detector['recall']}, "
          f"look-alike FP rate {detector['false_positive_rate']}, AP {detector['average_precision']}")
    if unseen:
        mean = {name: unseen["detector"][name]["mean"] for name in ("precision", "recall", "false_positive_rate")}
        print(f"Unseen seeds {unseen['seeds']}: mean {mean}; checks {unseen['checks_passed']}")
    print(f"Report: {args.data / 'evaluation' / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
