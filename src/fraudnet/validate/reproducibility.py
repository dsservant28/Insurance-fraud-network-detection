"""Reproducibility check (DATA_DICTIONARY.md 11.3): run the generator twice and compare every file.

This module runs the generator itself, so it does compare hidden files too. It only compares
checksums and never reads label contents, so it carries no label into validation results.
"""
from __future__ import annotations

import hashlib
import platform
import tempfile
from pathlib import Path

import networkx
import numpy
import pandas as pd

from fraudnet.generate.__main__ import run as generate_into

COMPARED_FOLDERS = ("input", "hidden", "reports")


def file_checksums(output_dir: Path) -> dict[str, str]:
    """SHA-256 of every exported file. The .db file is excluded: the database file is not byte-stable across runs."""
    output_dir = Path(output_dir)
    return {path.relative_to(output_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in COMPARED_FOLDERS if (output_dir / folder).exists()
            for path in sorted((output_dir / folder).rglob("*")) if path.is_file()
            and not (folder == "reports" and path.name != "source_manifest.json")}


def check_reproducibility(seed: int, scale: float, compare_with: Path | None = None) -> dict:
    """Generate twice into new folders and compare checksums. A different seed must give different data."""
    with tempfile.TemporaryDirectory(prefix="fraudnet_repro_") as work:
        work = Path(work)
        first, second, other = work / "run_a", work / "run_b", work / "other_seed"
        generate_into(seed, scale, first)
        generate_into(seed, scale, second)
        generate_into(seed + 1, scale, other)
        sums_a, sums_b, sums_other = file_checksums(first), file_checksums(second), file_checksums(other)
        rows = {item: sum(1 for _ in open(first / item, encoding="utf-8")) - 1
                for item in sums_a if item.startswith("input/csv/")}

    mismatched = sorted(name for name in sums_a.keys() | sums_b.keys() if sums_a.get(name) != sums_b.get(name))
    changed_with_seed = sorted(name for name in sums_a if name.startswith("input/csv/") and sums_a[name] != sums_other.get(name))
    report = {
        "seed": seed,
        "scale": scale,
        "software": {"python": platform.python_version(), "numpy": numpy.__version__,
                     "pandas": pd.__version__, "networkx": networkx.__version__},
        "files_compared": len(sums_a),
        "files_identical": len(sums_a) - len(mismatched),
        "mismatched_files": mismatched,
        "csv_row_counts": rows,
        "different_seed": seed + 1,
        "csv_files_changed_by_different_seed": len(changed_with_seed),
        "checksums": sums_a,
    }
    if compare_with is not None:
        existing = file_checksums(compare_with)
        report["matches_existing_output"] = all(existing.get(name) == digest for name, digest in sums_a.items())
    report["status"] = "PASS" if not mismatched and changed_with_seed and report.get("matches_existing_output", True) else "FAIL"
    return report
