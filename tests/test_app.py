"""The investigator console: plain-language reasons, data loading, the score map and the Risk field page."""
from pathlib import Path

import pytest

from fraudnet.app.charts import score_map
from fraudnet.app.data import Network, load_overview
from fraudnet.app.plain import reason

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"


def _network(evidence, names=None, members=None):
    members = members or sorted({m for item in evidence for m in item["claimants"]})
    names = names or {m: f"Person {m[-1]} Surname{m[-1]}" for m in members}
    return Network("NET-000001", 1, 0.9, "HIGH", True, members, names, {"IDENTITY": 0.8}, evidence, [], {})


def _ev(edge_type, *claimants):
    return {"edge_type": edge_type, "claimants": list(claimants)}


def test_reason_merges_shared_values_and_names_partial_groups():
    network = _network([_ev("SHARED_BANK", "A", "B", "C"), _ev("SHARED_PHONE", "A", "B", "C"), _ev("SHARED_ADDRESS", "A", "B")])
    assert reason(network) == ("3 people with different surnames share a bank account and a phone number; "
                               "2 of them also share an address.")


def test_reason_reads_a_provider_account_as_one_fact():
    network = _network([_ev("SHARED_BANK", "A", "B"), _ev("SHARED_CONTACT_PROVIDER", "A", "B")])
    assert reason(network) == "2 people with different surnames share a bank account that belongs to their provider."


def test_reason_mentions_surnames_only_for_shared_contact_details():
    assert reason(_network([_ev("SIMILAR_NARRATIVE", "A", "B", "C")])) == "3 people filed near-identical stories at one provider."
    same = _network([_ev("SHARED_PHONE", "A", "B")], names={"A": "Ann Lee", "B": "Bo Lee"})
    assert reason(same) == "2 people share a phone number."


def test_reason_when_the_main_evidence_covers_only_part_of_the_network():
    network = _network([_ev("SAME_INCIDENT", "A", "B", "C"), _ev("SHARED_BANK", "A", "B")], members=["A", "B", "C", "D"])
    assert reason(network) == ("3 of 4 people with different surnames claimed on the same incident; "
                               "2 of them also share a bank account.")


def test_overview_reads_detector_output_and_the_score_identity_holds():
    data = load_overview(SAMPLE)
    assert data.networks and data.claimants > 0 and data.links == sum(data.run["counts"]["links"].values())
    assert [n.rank for n in data.networks] == sorted(n.rank for n in data.networks)
    for network in data.networks:
        rebuilt = 1 - (1 - network.strongest) * (1 - network.other)
        assert rebuilt == pytest.approx(network.score, abs=2e-4)
        assert reason(network).endswith(".")


def test_score_map_builds_with_a_selection():
    data = load_overview(SAMPLE)
    reasons = {n.network_id: reason(n) for n in data.networks}
    spec = score_map(data.networks, reasons, data.run["flag_threshold"], data.networks[0].network_id).to_dict()
    params = spec.get("params", []) + [p for layer in spec["layer"] for p in layer.get("params", [])]
    assert len(spec["layer"]) == 6 and any(p.get("name") == "pick" for p in params)


def test_risk_field_page_runs_and_selects_a_network(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FRAUDNET_DATA", str(SAMPLE))
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    data = load_overview(SAMPLE)
    flagged = data.flagged
    assert app.session_state["network"] == flagged[0].network_id
    target = flagged[-1].network_id
    app.button(key=f"view-{target}").click().run()
    assert not app.exception and app.session_state["network"] == target
