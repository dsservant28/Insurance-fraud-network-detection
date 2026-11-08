"""Command line: python -m fraudnet.evaluate --data data/output [--seeds 606 707 808 909 1010] [--doc docs/EVALUATION.md]

Scores <data>/detect against <data>/hidden, then generates, detects and scores each unseen seed at
the same scale. Writes <data>/evaluation/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fraudnet.evaluate.report import write_report
from fraudnet.evaluate.run import aggregate, evaluate_dataset, evaluate_seeds

# Never looked at while designing or tuning the detector. 777 and 4242 (D-028) and 101-505 (D-029) were
# looked at during fixes, so they are retired as test seeds.
UNSEEN_SEEDS = (606, 707, 808, 909, 1010)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate detector output against the hidden labels.")
    parser.add_argument("--data", type=Path, default=Path("data/output"))
    parser.add_argument("--seeds", type=int, nargs="*", default=list(UNSEEN_SEEDS),
                        help="unseen seeds to generate and score at the same scale (none: development seed only)")
    parser.add_argument("--no-comparisons", action="store_true", help="skip comparison methods and principle-off runs")
    parser.add_argument("--doc", type=Path, help="also write the Markdown report here")
    args = parser.parse_args()

    with_comparisons = not args.no_comparisons
    development = evaluate_dataset(args.data, with_comparisons)
    scale = json.loads((args.data / "input/input_manifest.json").read_text(encoding="utf-8"))["generator"]["scale"]
    results = evaluate_seeds(args.seeds, scale, with_comparisons=with_comparisons) if args.seeds else []
    unseen = aggregate(results) if results else None
    command = "python -m fraudnet.evaluate " + " ".join(sys.argv[1:])
    write_report(args.data / "evaluation", development, results, unseen, command.strip(), args.doc)

    detector = development["detector"]
    print(f"Development seed {development['seed']}: precision {detector['precision']}, ring recall {detector['recall']}, "
          f"look-alike FP rate {detector['false_positive_rate']}, AP {detector['average_precision']}")
    if unseen:
        mean = {name: unseen["detector"][name]["mean"] for name in ("precision", "recall", "false_positive_rate")}
        print(f"Unseen seeds {unseen['seeds']}: mean {mean}; checks {unseen['checks_passed']}")
    print(f"Report: {args.data / 'evaluation' / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
