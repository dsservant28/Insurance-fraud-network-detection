"""Command line: python -m fraudnet.generate --seed 20261022 --scale 1.0 --out data/output"""
from __future__ import annotations

import argparse
from pathlib import Path

from fraudnet.generate.config import DEFAULT_SEED, GeneratorConfig
from fraudnet.generate.export import write_input, write_source_manifest
from fraudnet.generate.ground_truth import write_hidden
from fraudnet.generate.pipeline import generate_with_labels


def run(seed: int, scale: float, out: Path) -> dict:
    """Generate one dataset into `out` and return its input manifest."""
    tables, labels = generate_with_labels(GeneratorConfig(seed=seed, scale=scale))
    manifest = write_input(tables, out, generator={"seed": seed, "scale": scale})
    write_hidden(labels, out)
    write_source_manifest(out, seed, scale, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic insurance data.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--out", type=Path, default=Path("data/output"))
    args = parser.parse_args()

    manifest = run(args.seed, args.scale, args.out)
    for item in manifest["files"]:
        if item["path"].startswith("csv/"):
            print(f"{item['table']:<18} {item['rows']:>7} rows")
    print(f"Input files:     {args.out / 'input'}  (CSV, JSON, SQL)")
    print(f"SQLite database: {args.out / 'fraudnet.db'}")
    print(f"Hidden labels:   {args.out / 'hidden'}")
    print(f"Source manifest: {args.out / 'reports' / 'source_manifest.json'}")


if __name__ == "__main__":
    main()
