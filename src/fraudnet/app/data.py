"""Read-only access to one dataset's detector output, for the app.

The app reads `<data>/detect/` and the input manifest only. It never opens the labels folder:
`scripts/policy_check.py` enforces that for everything under `app/`, as for `detect/`.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DATA_ENV = "FRAUDNET_DATA"


def data_dir() -> Path:
    """`FRAUDNET_DATA` if set, else the full dataset in data/output, else the committed sample."""
    if os.environ.get(DATA_ENV):
        return Path(os.environ[DATA_ENV])
    full = REPO / "data" / "output"
    return full if (full / "detect" / "network.csv").exists() else REPO / "data" / "sample"


@dataclass
class Network:
    network_id: str
    rank: int
    score: float
    priority: str
    flagged: bool
    members: list[str]
    names: dict[str, str]
    families: dict[str, float]
    evidence: list[dict]
    support: list[dict]
    context: dict[str, str]
    detail: dict = field(default_factory=dict, repr=False)  # graph, waterfall, timeline, discounted links

    @property
    def strongest(self) -> float:
        """The strongest single family: the x of the score map."""
        return max(self.families.values(), default=0.0)

    @property
    def other(self) -> float:
        """All other evidence combined, so that score = 1 - (1 - strongest)(1 - other) exactly."""
        x = self.strongest
        return 0.0 if x >= 1 else max(0.0, round(1 - (1 - self.score) / (1 - x), 4))


@dataclass
class Overview:
    folder: Path
    run: dict
    networks: list[Network]
    claimants: int
    claims: int
    tables: dict[str, int] = field(default_factory=dict)

    @property
    def flagged(self) -> list[Network]:
        return [network for network in self.networks if network.flagged]

    @property
    def links(self) -> int:
        return sum(self.run["counts"]["links"].values())


def load_overview(folder: Path | None = None) -> Overview:
    folder = Path(folder or data_dir())
    run = json.loads((folder / "detect" / "detector_run.json").read_text(encoding="utf-8"))
    details = json.loads((folder / "detect" / "network_detail.json").read_text(encoding="utf-8"))
    table = pd.read_csv(folder / "detect" / "network.csv").set_index("network_id")
    networks = []
    for detail in details:
        row = table.loc[detail["network_id"]]
        names = {node["id"]: node["label"] for node in detail["graph"]["nodes"] if node["type"] == "CLAIMANT"}
        networks.append(Network(
            network_id=detail["network_id"], rank=int(row["rank"]), score=float(row["score"]),
            priority=str(row["priority"]), flagged=bool(row["flagged"]), members=list(detail["members"]), names=names,
            families=dict(detail["families"]), evidence=list(detail["evidence"]), support=list(detail["support"]),
            context=dict(detail.get("context", {})), detail=detail))
    networks.sort(key=lambda network: network.rank)
    manifest = json.loads((folder / "input" / "input_manifest.json").read_text(encoding="utf-8"))
    rows = {item["table"]: item["rows"] for item in manifest["files"] if "table" in item and item["path"].startswith("csv/")}
    return Overview(folder, run, networks, rows.get("claimant", 0), rows.get("claim", 0), rows)


def load_evaluation() -> dict:
    """The committed evaluation and stress summaries in docs/ (aggregate results only, written by `fraudnet.evaluate`)."""
    docs = REPO / "docs"
    read = lambda path: json.loads(path.read_text(encoding="utf-8")) if path.exists() else None  # noqa: E731
    return {"evaluation": read(docs / "EVALUATION.json"), "stress_v01": read(docs / "stress" / "stress_v0.1.json"),
            "stress_v02": read(docs / "stress" / "stress_v0.2.json")}


def load_reports(folder: Path) -> dict:
    """The validator's reports: summary, exceptions and (when it was run) the reproducibility check."""
    reports = Path(folder) / "reports"
    read = lambda name: json.loads((reports / name).read_text(encoding="utf-8")) if (reports / name).exists() else None  # noqa: E731
    return {"summary": read("validation_summary.json"), "exceptions": read("data_exception.json") or [],
            "reproducibility": read("reproducibility_report.json")}


def exception_cases(folder: Path) -> dict[str, dict]:
    """Latest case for each data exception, if any."""
    database = Path(folder) / "fraudnet.db"
    if not database.exists():
        return {}
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT exception_id, investigation_id, current_status FROM investigation "
                                  "WHERE exception_id IS NOT NULL ORDER BY investigation_id").fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        connection.close()
    return {exception: {"investigation_id": case, "status": status} for exception, case, status in rows}


def cases_for_network(folder: Path, network_id: str) -> list[dict]:
    """Investigation cases opened from this network, newest first. Empty if there is no case table yet."""
    database = Path(folder) / "fraudnet.db"
    if not database.exists():
        return []
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT investigation_id, current_status, priority, opened_at, opened_by, run_id FROM investigation "
            "WHERE network_id = ? ORDER BY investigation_id DESC", (network_id,)).fetchall()
    except sqlite3.OperationalError:  # no investigation table in this database yet
        rows = []
    finally:
        connection.close()
    return [dict(row) for row in rows]
