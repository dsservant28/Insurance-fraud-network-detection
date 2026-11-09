"""Networks, scoring, explanations and detector output (ARCHITECTURE.md sections 3.3-4 and 7).

Tests may read hidden labels to check results. The detector itself never does: the removed-folder
test proves its output doesn't change when the labels are absent.
"""
import json
import re
import shutil
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from fraudnet.detect.__main__ import detect
from fraudnet.detect.config import load_config
from fraudnet.detect.links import FAMILY, STRONG_FAMILIES
from fraudnet.detect.networks import evidence_links, group_claimants, noisy_or, score_network
from fraudnet.detect.pipeline import make_run_id
from fraudnet.generate.__main__ import run as generate_into
from fraudnet.inputs import load_input

SETTINGS, _ = load_config()
EMPTY = pd.DataFrame(columns=["claim_id", "provider_id", "claimant_id"])
NO_INVOICES = pd.DataFrame(columns=["claimant_id", "provider_id", "amount_ratio", "invoice_id", "peer_median_cents"])


def _link(number, a, b, edge_type, strength, matched="X", recorded=1):
    return {"link_id": f"LNK-{number:06d}", "source_node_id": a, "target_node_id": b, "edge_type": edge_type,
            "family": FAMILY[edge_type], "matched_value": matched, "strength": strength, "in_recorded_edges": recorded,
            "explanation_code": None, "detail_json": "{}"}


def _frame(*links):
    return pd.DataFrame([_link(n, *item) for n, item in enumerate(links, start=1)])


def _score(members, links):
    return score_network(members, evidence_links(links, SETTINGS), EMPTY, NO_INVOICES, set(), SETTINGS)


# ---- theory as arithmetic

def test_flag_rule_needs_corroboration_for_weak_evidence():
    caps, threshold = SETTINGS["links"]["caps"], SETTINGS["score"]["flag_threshold"]
    repetition = SETTINGS["network"]["repetition_factor"]
    # Single-fact weak links (one address, one incident, early-claim timing) can never flag alone.
    for edge_type in ("SHARED_ADDRESS", "SAME_INCIDENT", "EARLY_CLAIM_PAIR"):
        assert caps[edge_type] < threshold
    # A story link already joins two facts (same provider and a near-copied narrative), so it may flag
    # alone, but only once it repeats across enough claimants.
    assert caps["SIMILAR_NARRATIVE"] >= threshold > caps["SIMILAR_NARRATIVE"] * repetition
    assert noisy_or([caps["SAME_INCIDENT"], caps["SHARED_ADDRESS"]]) < threshold
    # Strong evidence passes alone at full rarity but not when the link type is common.
    strong = [cap for edge_type, cap in caps.items() if FAMILY[edge_type] in STRONG_FAMILIES]
    assert min(strong) * SETTINGS["rarity"]["floor"] < threshold <= min(strong)


def test_noisy_or_adds_independent_evidence_without_passing_one():
    assert noisy_or([0.5, 0.5]) == 0.75 and noisy_or([]) == 0.0 and noisy_or([0.9, 0.9, 0.9]) < 1.0


def test_more_members_do_not_raise_the_score_by_themselves():
    small = _score(["CLT-000001", "CLT-000002", "CLT-000003"],
                   _frame(("CLT-000001", "CLT-000002", "SHARED_BANK", 0.85), ("CLT-000001", "CLT-000003", "SHARED_BANK", 0.85),
                          ("CLT-000002", "CLT-000003", "SHARED_BANK", 0.85)))
    people = [f"CLT-{n:06d}" for n in range(1, 9)]
    links = [(a, b, "SHARED_BANK", 0.85) for i, a in enumerate(people) for b in people[i + 1:]]
    assert _score(people, _frame(*links)).score == small.score


def test_a_weak_pair_counts_half_until_it_repeats():
    pair = _score(["CLT-000001", "CLT-000002"], _frame(("CLT-000001", "CLT-000002", "SHARED_ADDRESS", 0.2)))
    assert pair.families["LOCATION"] == round(0.2 * SETTINGS["network"]["repetition_factor"], 4)
    trio = _score(["CLT-000001", "CLT-000002", "CLT-000003"],
                  _frame(("CLT-000001", "CLT-000002", "SHARED_ADDRESS", 0.2), ("CLT-000002", "CLT-000003", "SHARED_ADDRESS", 0.2)))
    assert trio.families["LOCATION"] == 0.2


def test_partial_coverage_lowers_a_family():
    members = [f"CLT-{n:06d}" for n in range(1, 5)]
    network = _score(members, _frame(("CLT-000001", "CLT-000002", "SHARED_PHONE", 0.75),
                                     ("CLT-000001", "CLT-000003", "SHARED_EMAIL", 0.70),
                                     ("CLT-000003", "CLT-000004", "SHARED_EMAIL", 0.70)))
    assert network.types["SHARED_PHONE"].coverage == round((2 / 4) ** 0.5, 4)
    assert network.families["IDENTITY"] == max(network.types["SHARED_PHONE"].strength,
                                                network.types["SHARED_EMAIL"].strength)


def test_waterfall_adds_up_to_the_score():
    network = _score(["CLT-000001", "CLT-000002", "CLT-000003"],
                     _frame(("CLT-000001", "CLT-000002", "SHARED_PHONE", 0.75),
                            ("CLT-000001", "CLT-000002", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"),
                            ("CLT-000001", "CLT-000003", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001")))
    assert abs(sum(added for _, added in network.contributions) - network.score) < 1e-3


# ---- network building

def test_uncorroborated_shared_incident_joins_nobody():
    crash = [("CLT-000001", "CLT-000002", "SAME_INCIDENT", 0.45, "INC-2026-000001"),
             ("CLT-000001", "CLT-000003", "SAME_INCIDENT", 0.45, "INC-2026-000001"),
             ("CLT-000002", "CLT-000003", "SAME_INCIDENT", 0.45, "INC-2026-000001")]
    assert evidence_links(_frame(*crash), SETTINGS).empty
    staged = _frame(*crash, ("CLT-000001", "CLT-000002", "SHARED_PHONE", 0.75))
    assert len(evidence_links(staged, SETTINGS)) == 4


def test_a_single_coincidental_provider_pair_joins_nobody():
    pair = _frame(("CLT-000001", "CLT-000002", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"))
    assert evidence_links(pair, SETTINGS).empty
    repeated = _frame(("CLT-000001", "CLT-000002", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"),
                      ("CLT-000002", "CLT-000003", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"))
    assert len(evidence_links(repeated, SETTINGS)) == 2


def test_weak_and_explained_links_never_join_claimants():
    links = _frame(("CLT-000001", "CLT-000002", "SHARED_PHONE", 0.075), ("CLT-000003", "CLT-000004", "SHARED_BANK", 0.85))
    assert group_claimants(evidence_links(links, SETTINGS), SETTINGS) == [["CLT-000003", "CLT-000004"]]


def test_oversized_groups_are_split_into_communities():
    left = [f"CLT-{n:06d}" for n in range(1, 9)]
    right = [f"CLT-{n:06d}" for n in range(11, 19)]
    links = [(a, b, "SHARED_BANK", 0.85) for side in (left, right) for i, a in enumerate(side) for b in side[i + 1:]]
    links.append(("CLT-000008", "CLT-000011", "SHARED_ADDRESS", 0.2))  # one weak bridge
    groups = group_claimants(evidence_links(_frame(*links), SETTINGS), SETTINGS)
    assert groups == [left, right]


def test_run_id_follows_input_settings_and_code():
    assert make_run_id("a", "b", "1") == make_run_id("a", "b", "1") != make_run_id("a", "c", "1")
    assert re.fullmatch(r"RUN-[0-9A-F]{12}", make_run_id("a", "b"))


# ---- full detector on generated data

@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    folder = tmp_path_factory.mktemp("detected")
    generate_into(20261022, 0.1, folder)
    run = detect(folder)
    return folder, run


def _read(folder, name):
    return pd.read_csv(folder / "detect" / name, dtype=str, keep_default_na=False)


def _labels(folder):
    labels = pd.read_csv(folder / "hidden/ground_truth.csv", dtype=str)
    claimants = labels[labels["entity_type"] == "CLAIMANT"]
    return claimants.assign(group=claimants["ring_id"].fillna(claimants["group_id"]))


def _matches(members, labels):
    """Best-matching labelled group of a network by claimant Jaccard similarity."""
    best = None
    for group, rows in labels.groupby("group"):
        planted = set(rows["entity_id"])
        jaccard = len(planted & members) / len(planted | members)
        if best is None or jaccard > best[1]:
            best = (group, jaccard, rows["is_fraud"].iloc[0], rows["rule_id"].iloc[0])
    return best


def test_every_planted_fraud_group_is_flagged_and_nothing_benign(dataset):
    folder, _ = dataset
    network, members, labels = _read(folder, "network.csv"), _read(folder, "network_member.csv"), _labels(folder)
    found = set()
    for row in network[network["flagged"] == "1"].itertuples(index=False):
        people = set(members.loc[(members["network_id"] == row.network_id) & (members["member_role"] == "CLAIMANT"),
                                 "node_id"])
        group, jaccard, is_fraud, rule = _matches(people, labels)
        assert jaccard >= 0.5 and is_fraud == "1", (row.network_id, group, jaccard, rule)
        found.add(group)
    fraud_groups = set(labels.loc[labels["is_fraud"] == "1", "group"])
    assert found == fraud_groups


def test_every_explanation_cites_ids_that_exist(dataset):
    folder, _ = dataset
    tables, _ = load_input(folder / "input")
    known = set()
    for table, column in (("claimant", "claimant_id"), ("provider", "provider_id"), ("claim", "claim_id"),
                          ("incident", "incident_id"), ("invoice", "invoice_id"), ("payment", "payment_id"),
                          ("policy", "policy_id")):
        known |= set(tables[table][column])
    pattern = re.compile(r"\b(?:CLT-\d{6}|PRV-\d{6}|CLM-2026-\d{6}|INC-2026-\d{6}|INV-PRV-\d{6}-\d{6}|PAY-2026-\d{6})\b")
    indicators, network = _read(folder, "fraud_indicator.csv"), _read(folder, "network.csv")
    for text in list(indicators["explanation"]) + list(network["summary"]) + list(indicators["evidence_json"]):
        cited = pattern.findall(text)
        assert set(cited) <= known
    assert all(pattern.search(text) for text in indicators["explanation"])
    flagged = set(network.loc[network["flagged"] == "1", "network_id"])
    assert flagged <= set(indicators["network_id"])


def test_exceptions_become_standalone_indicators(dataset):
    folder, _ = dataset
    indicators = _read(folder, "fraud_indicator.csv")
    standalone = indicators[indicators["indicator_code"].isin(["ORPHAN_POLICY_REF", "PAYMENT_OVER_APPROVED"])]
    assert set(standalone["indicator_code"]) == {"ORPHAN_POLICY_REF", "PAYMENT_OVER_APPROVED"}
    assert (standalone["network_id"] == "").all() and (standalone["score_contribution"].astype(float) == 0).all()


def test_hidden_ring_links_are_reported_as_unrecorded(dataset):
    folder, _ = dataset
    labels = _labels(folder)
    hidden = set(labels.loc[labels["rule_id"] == "R-RING-06", "entity_id"])
    edges = _read(folder, "detected_edge.csv")
    inside = edges[edges["source_node_id"].isin(hidden) & edges["target_node_id"].isin(hidden)]
    assert len(inside) and set(inside["in_recorded_edges"]) == {"0"}
    indicators = _read(folder, "fraud_indicator.csv")
    assert (indicators["indicator_code"] == "UNRECORDED_LINK").any()


def test_look_alikes_are_cleared_with_reasons(dataset):
    folder, _ = dataset
    cleared = json.loads((folder / "detect/cleared_groups.json").read_text(encoding="utf-8"))
    codes = {code for group in cleared for code in group["explanations"]}
    assert {"HOUSEHOLD", "BUILDING"} <= codes
    assert all(group["reasons"] and group["members"] for group in cleared)
    assert max(group["score_without_explanations"] for group in cleared) >= SETTINGS["score"]["flag_threshold"]


def test_network_detail_feeds_the_app(dataset):
    folder, _ = dataset
    details = json.loads((folder / "detect/network_detail.json").read_text(encoding="utf-8"))
    for detail in details:
        assert abs(sum(step["added"] for step in detail["waterfall"]) - detail["score"]) < 1e-3
        nodes = {node["id"] for node in detail["graph"]["nodes"]}
        assert all(edge["source"] in nodes and edge["target"] in nodes for edge in detail["graph"]["edges"])
        assert detail["timeline"] and detail["evidence"]


def test_database_tables_load_with_foreign_keys(dataset):
    folder, run = dataset
    with sqlite3.connect(folder / "fraudnet.db") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT run_id FROM detector_run").fetchall() == [(run["run_id"],)]
        assert connection.execute("SELECT COUNT(*) FROM network").fetchone()[0] == run["counts"]["networks"]


def test_detector_output_is_identical_without_the_hidden_folder(dataset, tmp_path):
    """The labels play no part: a copy holding only input/ gives byte-identical output."""
    folder, _ = dataset
    shutil.copytree(folder / "input", tmp_path / "input")
    detect(tmp_path, database=False)
    assert not (tmp_path / "hidden").exists()
    original = sorted(path.name for path in (folder / "detect").iterdir())
    assert original == sorted(path.name for path in (tmp_path / "detect").iterdir())
    for name in original:
        assert (folder / "detect" / name).read_bytes() == (tmp_path / "detect" / name).read_bytes(), name


def test_command_line_runs(dataset):
    folder, run = dataset
    result = subprocess.run([sys.executable, "-m", "fraudnet.detect", "--data", str(folder)],
                            capture_output=True, text=True)
    assert result.returncode == 0 and run["run_id"] in result.stdout


def test_one_provider_fact_is_not_counted_twice():
    """Early-claim links already rest on the shared provider, so provider concentration adds nothing."""
    members = ["CLT-000001", "CLT-000002", "CLT-000003"]
    links = _frame(("CLT-000001", "CLT-000002", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"),
                   ("CLT-000002", "CLT-000003", "EARLY_CLAIM_PAIR", 0.55, "PRV-000001"))
    used = pd.DataFrame({"claim_id": ["C1", "C2", "C3"], "provider_id": ["PRV-000001"] * 3, "claimant_id": members})
    network = score_network(members, evidence_links(links, SETTINGS), used, NO_INVOICES, set(), SETTINGS)
    assert [item.code for item in network.support] == [] and network.score < SETTINGS["score"]["flag_threshold"]
    bank = _frame(("CLT-000001", "CLT-000002", "SHARED_BANK", 0.85), ("CLT-000002", "CLT-000003", "SHARED_BANK", 0.85))
    network = score_network(members, evidence_links(bank, SETTINGS), used, NO_INVOICES, set(), SETTINGS)
    assert [item.code for item in network.support] == ["PROVIDER_CONCENTRATION"]  # an independent fact here


GROUPING_SCRIPT = """
import json, sys
import numpy as np, pandas as pd
from fraudnet.detect.config import load_config
from fraudnet.detect.networks import group_claimants
rng = np.random.default_rng(7)
people = [f"CLT-{n:06d}" for n in range(1, 61)]
rows = [(people[i], people[j], round(float(rng.uniform(0.2, 0.9)), 3))
        for i in range(60) for j in range(i + 1, 60) if rng.random() < 0.09]
links = pd.DataFrame(rows, columns=["source_node_id", "target_node_id", "strength"])
settings, _ = load_config()
print(json.dumps(group_claimants(links, settings)))
"""


def test_louvain_split_is_the_same_in_every_process():
    # Python randomises string hashing per process. Oversized groups are split by Louvain, whose result must not
    # depend on that, so the same grouping runs under three different hash seeds.
    import os
    import subprocess
    import sys
    outputs = set()
    for hash_seed in ("1", "8", "15"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run([sys.executable, "-c", GROUPING_SCRIPT], capture_output=True, text=True, env=env,
                                cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout)
    assert len(outputs) == 1
    groups = __import__("json").loads(outputs.pop())
    assert len(groups) > 1  # the 60-person component really was split
