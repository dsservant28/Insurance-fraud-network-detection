"""Command line: python -m fraudnet.generate --seed 20261022 --scale 1.0 --out data/output"""
from __future__ import annotations

import argparse
from pathlib import Path

from fraudnet.generate.config import DEFAULT_SEED, GeneratorConfig
from fraudnet.generate.export import write_input
from fraudnet.generate.ground_truth import write_hidden
from fraudnet.generate.pipeline import generate_with_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic insurance data.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=Path("data/output"))
    args = parser.parse_args()

    tables, labels = generate_with_labels(GeneratorConfig(seed=args.seed, scale=args.scale))
    manifest = write_input(tables, args.out)
    write_hidden(labels, args.out)
    for item in manifest["files"]:
        if "table" in item:
            print(f"{item['table']:<18} {item['rows']:>7} rows")
    print(f"CSV and SQL files: {args.out / 'input'}")
    print(f"SQLite database:   {args.out / 'fraudnet.db'}")
    print(f"Hidden labels:     {args.out / 'hidden'}")


if __name__ == "__main__":
    main()
