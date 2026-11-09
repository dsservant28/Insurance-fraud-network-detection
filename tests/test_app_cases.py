"""The Cases page: every action goes through the real workflow, with the same rules as the command line."""
import sqlite3
from pathlib import Path

import pytest

from fraudnet.app.cases import open_exceptions, open_networks, preview, history_rows, workflow
from fraudnet.run import run

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cases-app")
    run(20261022, 0.1, folder, demo_cases=False, say=lambda *_: None)
    return folder


def _case_events(folder):
    with sqlite3.connect(folder / "fraudnet.db") as db:
        return [row[0] for row in db.execute("SELECT action || ':' || COALESCE(reason_code, '') FROM investigation_events ORDER BY event_id")]


def test_preview_matches_the_workflow_rules(dataset):
    with workflow(dataset) as flow:
        network = open_networks(flow)[0]["network_id"]
        case_id = flow.open_from_network(network, "USR-RSK-01")
        case = flow.case(case_id)
        assert preview(flow, case, "START_REVIEW", "USR-OPS-01", None, None)[0]
        allowed, head, then = preview(flow, case, "CONFIRM", "USR-RSK-02", "CONFIRMED_LINKS", None)
        assert not allowed and "not possible" in head and "INVALID_TRANSITION" in then  # still OPEN
        flow.act(case_id, "START_REVIEW", "USR-RSK-01")
        allowed, head, then = preview(flow, flow.case(case_id), "CONFIRM", "USR-RSK-01", "CONFIRMED_LINKS", None)
        assert not allowed and "second reviewer" in head and "FOUR_EYES_BLOCKED" in then
        allowed, head, then = preview(flow, flow.case(case_id), "NOTE", "USR-ADM-01", None, "x")
        assert not allowed and "nothing is recorded" in then
        assert network not in {n["network_id"] for n in open_networks(flow)}  # one active case per network
        assert open_exceptions(flow)
        html = history_rows(flow.history(case_id))
        assert html.count("#") >= 2 and "Review started" in html


def test_cases_page_opens_works_blocks_and_confirms(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    folder = tmp_path / "data"
    run(20261022, 0.1, folder, demo_cases=False, say=lambda *_: None)  # a fresh database with no cases
    monkeypatch.setenv("FRAUDNET_DATA", str(folder))

    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=90)
    app.run()
    app.switch_page("src/fraudnet/app/pages/cases.py")
    app.session_state["actor"] = "USR-RSK-01"
    app.run()
    assert not app.exception and app.info
    app.button(key="open-network-go").click().run()
    app.selectbox(key="action").set_value("START_REVIEW").run()
    app.button(key="record").click().run()
    app.selectbox(key="action").set_value("CONFIRM").run()
    app.selectbox(key="reason-CONFIRM").set_value("CONFIRMED_LINKS").run()
    app.button(key="record").click().run()
    assert "second reviewer" in app.toast[0].value
    app.session_state["actor"] = "USR-RSK-02"
    app.run()  # a new person: the step resets to the first one they may take, so choose Confirm again
    app.selectbox(key="action").set_value("CONFIRM").run()
    app.selectbox(key="reason-CONFIRM").set_value("CONFIRMED_LINKS").run()
    app.button(key="record").click().run()
    assert not app.exception and "recorded" in app.toast[0].value
    app.session_state["actor"] = "USR-ADM-01"
    app.run()
    app.selectbox(key="action").set_value("NOTE").run()
    app.text_input(key="note").input("checking").run()
    app.button(key="record").click().run()
    assert "Nothing was written" in app.toast[0].value
    assert _case_events(folder) == ["OPEN:", "START_REVIEW:", "BLOCKED:FOUR_EYES_BLOCKED", "CONFIRM:CONFIRMED_LINKS"]
    with workflow(folder) as flow:
        assert all(flow.verify_chain(case["investigation_id"])["intact"] for case in flow.cases())
