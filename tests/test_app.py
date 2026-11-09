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


def _graph_network():
    edges = [
        {"id": "LNK-1", "source": "A", "target": "B", "edge_type": "SHARED_BANK", "family": "IDENTITY", "strength": 0.84,
         "recorded": 0, "evidence": True, "explanation": None},
        {"id": "LNK-2", "source": "B", "target": "A", "edge_type": "SHARED_PHONE", "family": "IDENTITY", "strength": 0.75,
         "recorded": 1, "evidence": True, "explanation": None},
        {"id": "LNK-3", "source": "A", "target": "B", "edge_type": "SHARED_ADDRESS", "family": "LOCATION", "strength": 0.2,
         "recorded": 0, "evidence": True, "explanation": None},
        {"id": "LNK-4", "source": "A", "target": "PRV-000001", "edge_type": "USED_PROVIDER", "family": "PROVIDER",
         "strength": None, "recorded": 1, "evidence": False, "explanation": None},
    ]
    nodes = [{"id": "A", "label": "Ann </script><b>Lee", "type": "CLAIMANT"}, {"id": "B", "label": "Bo Kim", "type": "CLAIMANT"},
             {"id": "PRV-000001", "label": "PRV-000001", "type": "PROVIDER"}]
    timeline = [{"date": "2026-07-09", "event": "INCIDENT", "claimant_id": c, "claim_id": f"CLM-{c}", "ref": "INC"} for c in "ABC"]
    network = _network([_ev("SHARED_BANK", "A", "B")], members=["A", "B", "C"])
    network.detail = {"graph": {"nodes": nodes, "edges": edges}, "timeline": timeline}
    return network


def test_graph_draws_one_line_per_pair_and_kind_of_evidence():
    from fraudnet.app.graph import elements
    lines = [e["data"] for e in elements(_graph_network()) if "source" in e["data"]]
    identity = [d for d in lines if d["family"] == "IDENTITY"]
    assert len(lines) == 3 and len(identity) == 1  # bank + phone merged; address separate; provider use as context
    assert identity[0]["missing"] == 1 and len(identity[0]["links"]) == 2 and identity[0]["links"][0].startswith("Shared bank")
    assert [d["context"] for d in lines if d["family"] == "CONTEXT"] == [True]


def test_graph_puts_people_on_a_ring_and_context_in_the_middle():
    import math
    from fraudnet.app.graph import elements, ring_radius
    nodes = {e["data"]["id"]: e for e in elements(_graph_network()) if "source" not in e["data"]}
    radius = ring_radius(2)
    assert all(math.isclose(math.hypot(nodes[c]["position"]["x"], nodes[c]["position"]["y"]), radius, abs_tol=0.2)
               for c in ("A", "B"))
    assert nodes["A"]["position"] == {"x": 0.0, "y": -radius}  # the first member sits at the top
    assert nodes["PRV-000001"]["position"] == {"x": 0.0, "y": 0.0}
    lines = [e["data"] for e in elements(_graph_network()) if "source" in e["data"] and not e["data"]["context"]]
    assert sorted(d["bend"] for d in lines) == [0, 40]  # strongest kind straight, the next one curves


def test_graph_page_text_cannot_break_out_of_the_script():
    from fraudnet.app.graph import html
    page = html(_graph_network())
    data_part = page.split("const els = ", 1)[1].split(";\n", 1)[0]
    assert "</script>" not in data_part and "<\\/script>" in data_part


def test_same_day_incidents_need_half_the_group():
    from fraudnet.app.charts import same_day_incidents, timeline_events
    network = _graph_network()
    bursts = same_day_incidents(network, timeline_events(network))
    assert list(bursts["people"]) == [3] and bursts["text"].iloc[0] == "3 of 3 report an incident"


def test_case_lookup_handles_no_database_no_table_and_a_case(tmp_path):
    import sqlite3
    from fraudnet.app.data import cases_for_network
    assert cases_for_network(tmp_path, "NET-000001") == []
    sqlite3.connect(tmp_path / "fraudnet.db").close()
    assert cases_for_network(tmp_path, "NET-000001") == []
    with sqlite3.connect(tmp_path / "fraudnet.db") as db:
        db.execute("CREATE TABLE investigation (investigation_id TEXT, current_status TEXT, priority TEXT, opened_at TEXT, "
                   "opened_by TEXT, run_id TEXT, network_id TEXT)")
        db.execute("INSERT INTO investigation VALUES ('INVG-2026-000001', 'OPEN', 'HIGH', 't', 'USR-OPS-01', 'RUN-X', 'NET-000001')")
    assert [c["investigation_id"] for c in cases_for_network(tmp_path, "NET-000001")] == ["INVG-2026-000001"]


def test_dossier_page_runs_and_follows_the_picked_network(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("FRAUDNET_DATA", str(SAMPLE))
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    app.run()
    app.switch_page("src/fraudnet/app/pages/network_dossier.py").run()
    assert not app.exception
    last = load_overview(SAMPLE).networks[-1].network_id
    app.selectbox(key="dossier_pick").set_value(last).run()
    assert not app.exception and app.session_state["network"] == last


def test_data_checks_page_shows_checks_and_every_exception(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from fraudnet.app.data import load_reports
    monkeypatch.setenv("FRAUDNET_DATA", str(SAMPLE))
    reports = load_reports(SAMPLE)
    assert reports["summary"]["checks"] and reports["exceptions"]
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    app.run()
    app.switch_page("src/fraudnet/app/pages/data_checks.py").run()
    assert not app.exception
    page = " ".join(str(getattr(element, "value", "")) for element in app.get("html"))
    assert all(row["exception_id"] in page for row in reports["exceptions"])


def test_evaluation_lab_reads_only_committed_summaries():
    from streamlit.testing.v1 import AppTest
    from fraudnet.app.data import load_evaluation
    data = load_evaluation()
    assert data["evaluation"]["development"]["edge_cases"] and data["stress_v01"]["table"] and data["stress_v02"]["table"]
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    app.run()
    app.switch_page("src/fraudnet/app/pages/evaluation_lab.py").run()
    assert not app.exception


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
