"""Cases: work investigations under the four-eyes rule, with a sealed, append-only history.

Layout: a header with three controls, a five-column board (one column per status), then two equal
halves: the selected case on the left, the next step on the right. Every action goes through the real
investigation workflow, so the rules here are the rules everywhere.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.cases import (
    ACTION_LABEL, ROLE_LABEL, STATUS_COLOUR, STATUS_LABEL, STATUSES, exception_sentence, history_rows, names,
    needs_reason, open_exceptions, open_networks, plain, preview, reasons, workflow,
)
from fraudnet.app.data import data_dir, load_overview
from fraudnet.app.plain import reason as network_reason
from fraudnet.investigate.workflow import STAFF, WorkflowError, export_history

folder = data_dir()
if not (folder / "fraudnet.db").exists():
    st.info("No database yet. Run `python -m fraudnet.run` first.")
    st.stop()


@st.cache_data(show_spinner=False)
def _overview(path: str):
    return load_overview(Path(path))


state = st.session_state
state.setdefault("actor", "USR-OPS-01")
people = names(folder)
networks_now = {n.network_id: n for n in _overview(str(folder)).networks}

flash = state.pop("flash", None)
if flash:
    st.toast(flash[1], icon={"ok": ":material/check_circle:", "blocked": ":material/block:"}.get(flash[0], ":material/error:"))

with workflow(folder) as flow:
    cases = flow.cases()
    history_json = json.dumps(export_history(flow), indent=2, sort_keys=True, default=str)
    free_networks, free_exceptions = open_networks(flow), open_exceptions(flow)

open_count = sum(1 for case in cases if not case["current_status"].startswith("CLOSED"))


def _open(kind: str, target: str) -> None:
    try:
        with workflow(folder) as flow:
            new = flow.open_from_network(target, state["actor"]) if kind == "network" else flow.open_from_exception(target, state["actor"])
        state["case"], state["flash"] = new, ("ok", f"{new} opened by {state['actor']}")
    except WorkflowError as error:
        state["flash"] = ("error", f"Refused: {error}")


# ---- header: title on the left, three controls on the right
left, right = st.columns([1.35, 1], gap="large", vertical_alignment="bottom")
with left:
    st.html(f"""<div class="fn-kicker">Cases</div>
<div class="fn-title">{open_count} open · {len(cases)} in total</div>
<p class="fn-lede">Pick a case, choose a step, and see whether the rules allow it before you press.</p>""")
with right:
    st.selectbox("Acting as", list(STAFF), key="actor", format_func=lambda a: f"{a} · {ROLE_LABEL[STAFF[a][0]]}")
    one, two = st.columns(2, gap="small")
    with one.popover("Open a case", icon=":material/add:", width="stretch"):
        by_network, by_exception = st.tabs([f"Network ({len(free_networks)})", f"Data exception ({len(free_exceptions)})"])
        with by_network:
            if free_networks:
                labels = {n["network_id"]: f"{n['network_id']} · {n['priority']} · {n['score']:.4f}" for n in free_networks}
                pick = st.selectbox("Network", list(labels), format_func=labels.get, key="open-network")
                st.button("Open case", key="open-network-go", type="primary", width="stretch", on_click=_open, args=("network", pick))
            else:
                st.caption("Every flagged network already has an active case.")
        with by_exception:
            if free_exceptions:
                labels = {e["exception_id"]: f"{e['exception_id']} · {plain(e['exception_type'])}" for e in free_exceptions}
                pick = st.selectbox("Exception", list(labels), format_func=labels.get, key="open-exception")
                st.button("Open case", key="open-exception-go", type="primary", width="stretch", on_click=_open, args=("exception", pick))
            else:
                st.caption("Every data exception already has an active case.")
    two.download_button("Download history", history_json, file_name="investigations.json", mime="application/json",
                        icon=":material/download:", width="stretch")

if not cases:
    st.info("No cases yet. Use **Open a case** to start one from a flagged network or a data exception.")
    st.stop()

if state.get("case") not in {case["investigation_id"] for case in cases}:
    working = [case for case in cases if not case["current_status"].startswith("CLOSED")]
    state["case"] = (working or cases)[0]["investigation_id"]

# ---- the board: one equal column per status
with st.container(border=True):
    for column, status in zip(st.columns(len(STATUSES), gap="medium"), STATUSES):
        here = [case for case in cases if case["current_status"] == status]
        with column:
            st.html(f'<div style="border-top: 3px solid {STATUS_COLOUR[status]}; padding-top: 10px; margin-bottom: 4px; '
                    f'display: flex; justify-content: space-between; align-items: baseline">'
                    f'<span style="font-size: 13.5px; font-weight: 600">{theme.esc(STATUS_LABEL[status])}</span>'
                    f'<span class="fn-mono" style="font-size: 12px; color: {theme.FAINT}">{len(here)}</span></div>')
            for case in here:
                target = case["network_id"] or plain(case["exception_type"])
                st.button(f"{case['investigation_id']} · {case['priority']}", key=f"case-{case['investigation_id']}",
                          help=f"{target} · opened by {case['opened_by']}", width="stretch",
                          type="primary" if case["investigation_id"] == state["case"] else "secondary",
                          on_click=lambda cid=case["investigation_id"]: state.update(case=cid))
            if not here:
                st.html(f'<div style="height: 38px; border: 1px dashed #2C3646; border-radius: 10px; display: flex; '
                        f'align-items: center; justify-content: center; font-size: 12.5px; color: {theme.FAINT}">No cases</div>')

with workflow(folder) as flow:
    case = flow.case(state["case"])
    events = flow.history(case["investigation_id"])
    chain = flow.verify_chain(case["investigation_id"])
    subjects = flow.subjects(case["investigation_id"])
    if case["network_id"] and case["network_id"] in networks_now:
        about = network_reason(networks_now[case["network_id"]])
    elif case["exception_id"]:
        about = exception_sentence(flow, case["exception_id"])
    else:
        about = case["trigger_summary"].split(". ")[0] + "."

PANEL_HEIGHT = 560
left, right = st.columns(2, gap="large")

# ---- left half: the case
with left:
    with st.container(border=True, height=PANEL_HEIGHT):
        source = (f"Network {case['network_id']} · score {case['trigger_score']:.4f}" if case["network_id"]
                  else f"Data exception {case['exception_id']}")
        who = "".join(f'<span class="fn-name">{theme.esc(people.get(s["node_id"], s["node_id"]))}</span>'
                      for s in subjects if s["subject_role"] == "CLAIMANT")
        badge = (f'<span style="color: #7FE0B5">● sealed · {len(events)} of {len(events)} hashes check out</span>' if chain["intact"]
                 else f'<span style="color: #FF6A3D">● broken at {theme.esc(chain["event_id"])}</span>')
        st.html(f"""
<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
  <span class="fn-mono" style="font-size: 20px; font-weight: 600">{theme.esc(case['investigation_id'])}</span>
  {theme.chip(case['priority'])}
  <span class="fn-chip" style="background: {STATUS_COLOUR[case['current_status']]}">{theme.esc(STATUS_LABEL[case['current_status']])}</span>
</div>
<div class="fn-mono" style="font-size: 12px; color: {theme.FAINT}; margin-top: 6px">{theme.esc(source)} · opened by {theme.esc(case['opened_by'])}</div>
<p style="margin: 12px 0 0; font-size: 15px; line-height: 1.5">{theme.esc(about)}</p>
<div class="fn-names">{who}</div>
<div style="display: flex; justify-content: space-between; align-items: baseline; margin: 18px 0 2px">
  <span class="fn-kicker">History</span><span class="fn-mono" style="font-size: 12px">{badge}</span>
</div>
{history_rows(events)}""")
        with st.expander("Evidence recorded when the case opened"):
            st.html(f'<div style="font-size: 13px; color: {theme.MUTED}">{theme.esc(case["trigger_summary"])}</div>')

# ---- right half: the next step
with right:
    with st.container(border=True, height=PANEL_HEIGHT):
        actor = state["actor"]
        if state.get("step_for") != (case["investigation_id"], actor):
            # Start on the first step this person may take here (a missing reason still counts: they choose it next).
            with workflow(folder) as flow:
                usable = [a for a in ACTION_LABEL
                          if flow._refusal(case, a, STAFF[actor][0], actor, reasons(a)[0] if needs_reason(a) else None, "x") is None]
            state["action"] = usable[0] if usable else "NOTE"
            state["step_for"] = (case["investigation_id"], actor)
        st.html(f'<div class="fn-panel-head"><h2>Next step</h2><span class="fn-kicker">as {theme.esc(actor)}</span></div>')
        action = st.selectbox("Step", list(ACTION_LABEL), format_func=ACTION_LABEL.get, key="action")
        if needs_reason(action):
            choice = st.selectbox("Reason", [None, *reasons(action)], key=f"reason-{action}",
                                  format_func=lambda r: "Choose a reason" if r is None else plain(r))
        else:
            st.selectbox("Reason", ["Not needed for this step"], disabled=True, key=f"reason-none-{action}")
            choice = None
        note = st.text_input("Note", key="note", placeholder="Required for a note, optional otherwise") or None
        with workflow(folder) as flow:
            allowed, headline, consequence = preview(flow, case, action, actor, choice, note)
        colour = "#7FE0B5" if allowed else "#FF9A66"
        four_eyes = ""
        if action == "CONFIRM":
            same = actor == case["opened_by"]
            four_eyes = (f'<div class="fn-mono" style="font-size: 12px; color: {theme.MUTED}; margin-top: 6px">Four-eyes: opened by '
                         f'{theme.esc(case["opened_by"])} · confirming as {theme.esc(actor)} '
                         f'<span style="color: {"#FF9A66" if same else "#7FE0B5"}">{"= same person" if same else "≠ different people"}</span></div>')
        st.html(f"""<div style="padding: 12px 14px; border-radius: 10px; border: 1px solid {colour}; background: {theme.RAISED}; margin: 6px 0 10px">
  <div style="font-size: 14px; font-weight: 600; color: {colour}">{theme.esc(headline)}</div>
  <div style="font-size: 12.5px; color: {theme.MUTED}; margin-top: 3px">{theme.esc(consequence)}</div>{four_eyes}
</div>""")
        if st.button("Record this step", type="primary", width="stretch", key="record"):
            try:
                with workflow(folder) as flow:
                    outcome = flow.act(case["investigation_id"], action, actor, choice, note)
                state["flash"] = (("ok", f"{outcome.event_id} recorded") if outcome.accepted else
                                  ("blocked", f"Refused and recorded as {outcome.event_id}: {outcome.message}"))
            except WorkflowError as error:
                state["flash"] = ("error", f"Refused: {error}. Nothing was written.")
            st.rerun()
        if case["network_id"]:
            if st.button(f"Open the dossier for {case['network_id']}", icon=":material/hub:", key="to-dossier", width="stretch"):
                state["network"] = case["network_id"]
                st.switch_page("src/fraudnet/app/pages/network_dossier.py")
