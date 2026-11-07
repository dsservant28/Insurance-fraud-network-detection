"""Build and write the hidden labels. Input files and the database never contain any of this."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from fraudnet.generate.ids import make_id
from fraudnet.generate.plant import PlantingPlan

COLUMNS = ["label_id", "label_kind", "rule_id", "ring_id", "group_id", "issue_type", "is_fraud",
           "entity_type", "entity_id", "expected_decision", "reason"]


def build_labels(plan: PlantingPlan, claim_group_numbers: dict[str, int], ids: dict[str, dict[int, str]]) -> pd.DataFrame:
    """One row per labelled entity. Each rule comes from the planting plan, never a random draw."""
    claims_by_group: dict[int, list[str]] = {}
    for claim_id, group_no in claim_group_numbers.items():
        claims_by_group.setdefault(group_no, []).append(claim_id)

    rows = []
    for group in plan.groups:
        claimant_ids = sorted(ids["claimant"][key] for key in group.claimant_keys)
        provider_ids = sorted(ids["provider"][key] for key in group.provider_keys)
        reason = group.reason.replace("{claimants}", ", ".join(claimant_ids)).replace("{providers}", ", ".join(provider_ids))
        entities = [("CLAIMANT", value) for value in claimant_ids]
        if group.label_providers:
            entities += [("PROVIDER", value) for value in provider_ids]
        entities += [("CLAIM", value) for value in sorted(claims_by_group.get(group.group_no, []))]
        rows += [{
            "label_kind": group.label_kind,
            "rule_id": group.rule_id,
            "ring_id": group.ring_id,
            "group_id": group.group_id,
            "issue_type": group.issue_type,
            "is_fraud": group.is_fraud,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "expected_decision": group.expected_decision,
            "reason": reason,
        } for entity_type, entity_id in entities]

    labels = pd.DataFrame(rows)
    labels.insert(0, "label_id", [make_id("label", number) for number in range(1, len(labels) + 1)])
    return labels[COLUMNS]


def write_hidden(labels: pd.DataFrame, output_dir: Path) -> None:
    """Write labels to <output_dir>/hidden, which is separate from <output_dir>/input."""
    hidden_dir = Path(output_dir) / "hidden"
    hidden_dir.mkdir(parents=True, exist_ok=True)
    csv_bytes = labels.to_csv(index=False, lineterminator="\n").encode("utf-8")
    records = labels.astype(object).where(labels.notna(), None).to_dict("records")
    json_bytes = (json.dumps(records, indent=2, sort_keys=True) + "\n").encode("utf-8")
    files = []
    for name, data in (("ground_truth.csv", csv_bytes), ("ground_truth.json", json_bytes)):
        (hidden_dir / name).write_bytes(data)
        files.append({"path": name, "rows": len(labels), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = json.dumps({"files": files}, indent=2, sort_keys=True) + "\n"
    (hidden_dir / "hidden_manifest.json").write_bytes(manifest.encode("utf-8"))
