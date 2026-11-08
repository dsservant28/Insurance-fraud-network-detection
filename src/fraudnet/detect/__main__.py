"""Command line: python -m fraudnet.detect --data data/output [--config path]

Reads only <data>/input (through its manifest), writes <data>/detect/ and, when the database
exists, the detector tables in <data>/fraudnet.db.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fraudnet.detect.config import DEFAULT_CONFIG, load_config
from fraudnet.detect.pipeline import run_detector
from fraudnet.detect.store import write_database, write_files
from fraudnet.inputs import load_input, manifest_sha256


def detect(data_dir: Path, config_path: Path = DEFAULT_CONFIG, database: bool = True) -> dict:
    """Run the detector on <data_dir>/input and write its output. Returns the run record."""
    data_dir = Path(data_dir)
    tables, _ = load_input(data_dir / "input")
    settings, config_sha = load_config(config_path)
    output = run_detector(tables, settings, manifest_sha256(data_dir / "input"), config_sha)
    write_files(output, data_dir / "detect")
    if database and (data_dir / "fraudnet.db").exists():
        write_database(output, data_dir / "fraudnet.db")
    return output.run


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect fraud networks in generated input data.")
    parser.add_argument("--data", type=Path, default=Path("data/output"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    run = detect(args.data, args.config)
    counts = run["counts"]
    print(f"Run {run['run_id']}: {sum(counts['links'].values())} links rebuilt "
          f"({counts['unrecorded_links']} missing from the recorded edges), {counts['networks']} networks, "
          f"{counts['flagged_networks']} flagged {counts['flagged_by_priority']}, "
          f"{counts['cleared_groups']} look-alike groups cleared.")
    print(f"Output: {args.data / 'detect'}")


if __name__ == "__main__":
    main()
