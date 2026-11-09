"""Network dossier: is this group really suspicious, who is in it, what links them, and what happened when."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.charts import TIMELINE_EVENTS, timeline
from fraudnet.app.data import cases_for_network, data_dir, load_overview
from fraudnet.app.graph import FAMILY_COLOUR, html as graph_html
from fraudnet.app.plain import FAMILY_LABEL, reason


@st.cache_data(show_spinner=False)
def _overview(folder: str):
    return load_overview(Path(folder))


data = _overview(str(data_dir()))
if not data.networks:
    st.info("The detector found no networks in this dataset.")
    st.stop()

state = st.session_state
ids = [network.network_id for network in data.networks]
by_id = {network.network_id: network for network in data.networks}
if state.get("network") not in by_id:
    state["network"] = ids[0]


def _label(network_id: str) -> str:
    n = by_id[network_id]
    return f"{n.network_id} · {n.priority if n.flagged else 'not flagged'} · {n.score:.4f}"


def _picked() -> None:
    state["network"] = state["dossier_pick"]


network = by_id[state["network"]]

# ---- header
top_left, top_right = st.columns([3, 1.2], vertical_alignment="bottom")
with top_right:
    st.selectbox("Network", ids, index=ids.index(network.network_id), format_func=_label, key="dossier_pick", on_change=_picked)
with top_left:
    chip = theme.chip(network.priority) if network.flagged else '<span class="fn-chip-outline">not flagged</span>'
    colour = theme.PRIORITY.get(network.priority, theme.NOT_FLAGGED) if network.flagged else theme.NOT_FLAGGED
    st.html(f"""
<div class="fn-kicker">Network dossier · rank {network.rank} of {len(data.networks)} · {len(network.members)} people</div>
<div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 6px 0 8px">
  <span class="fn-title fn-mono" style="font-size: 40px; margin: 0">{theme.esc(network.network_id)}</span>{chip}
  <span class="fn-mono" style="font-size: 28px; font-weight: 600; color: {colour}">{network.score:.4f}</span>
</div>
<p class="fn-lede">{theme.esc(reason(network))}</p>""")

cases = cases_for_network(data.folder, network.network_id)
if cases:
    case = cases[0]
    st.html(f'<div class="fn-strip"><span class="fn-chip-outline">Case {theme.esc(case["investigation_id"])} · '
            f'{theme.esc(case["current_status"])} · opened by {theme.esc(case["opened_by"])}</span></div>')
else:
    st.html('<div class="fn-strip"><span class="fn-chip-outline">No case open on this network yet</span></div>')

# ---- graph and the case for suspicion
ROW_HEIGHT = 800  # the graph and the evidence panels share one height, so the timeline sits straight below both
graph_col, side = st.columns([1.85, 1], gap="large")

with graph_col:
    with st.container(border=True, height=ROW_HEIGHT):
        st.html('<div class="fn-panel-head"><h2>Who is linked to whom</h2><span class="fn-kicker">live graph</span></div>')
        st.iframe(graph_html(network), height=624)  # our own generated HTML; data text is set with textContent
        evidence_edges = [edge for edge in network.detail["graph"]["edges"] if edge.get("evidence")]
        families = sorted({edge.get("family") for edge in evidence_edges})
        missing = sum(1 for edge in evidence_edges if edge.get("recorded") == 0)
        unrecordable = sum(1 for edge in evidence_edges if edge.get("recorded") is None)
        keys = "".join(
            f'<span style="display: inline-flex; align-items: center; gap: 6px"><span style="width: 22px; height: 4px; '
            f'border-radius: 2px; background: {FAMILY_COLOUR.get(f, "#5A6678")}"></span>{theme.esc(FAMILY_LABEL.get(f, f))}</span>'
            for f in families)
        recordable = len(evidence_edges) - unrecordable
        register = (f"{missing} of {recordable} links of a kind the relationship register records are missing from it: "
                    "the detector found them by rebuilding links from raw data." if missing else
                    f"All {recordable} links of a kind the relationship register records are in it." if recordable else "")
        if unrecordable:
            register += (f" {unrecordable} more {'is a kind' if unrecordable == 1 else 'are kinds'} the register never "
                         "records (similar stories, early claims, shared invoices).")
        st.html(f"""<div style="display: flex; flex-wrap: wrap; gap: 16px; font-size: 12.5px; color: {theme.MUTED}; padding: 4px 2px">
{keys}
<span style="display: inline-flex; align-items: center; gap: 6px"><span style="width: 22px; border-top: 2px dotted #5A6678"></span>Used a provider (context, never evidence)</span>
</div>
<div style="font-size: 13px; color: {theme.MUTED}; padding: 2px 2px 4px">Line width shows link strength. {theme.esc(register)}</div>""")

with side, st.container(border=True, height=ROW_HEIGHT):
    # How the score is built: each kind of evidence closes part of the doubt that is left.
    steps = network.detail.get("waterfall", [])
    segments, rows, doubt = "", "", 1.0
    for step in steps:
        added = float(step["added"])
        if added <= 0:
            continue  # nothing to show: e.g. no supporting facts
        share = added / doubt if doubt > 0 else 0.0
        doubt -= added
        colour = FAMILY_COLOUR.get(step["family"], theme.TEXT) if step["family"] != "SUPPORT" else theme.TEXT
        segments += f'<div style="width: {added * 100:.2f}%; background: {colour}"></div>'
        rows += (f'<div style="display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 6px 0">'
                 f'<span style="width: 12px; height: 12px; border-radius: 3px; background: {colour}"></span>'
                 f'<span>{theme.esc(FAMILY_LABEL.get(step["family"], step["family"]))}'
                 f'<span style="display: block; color: {theme.FAINT}; font-size: 12px">removes {share:.0%} of the doubt left</span></span>'
                 f'<span class="fn-mono" style="font-weight: 600">+{added:.4f}</span></div>')
    st.html(f"""
<div>
  <div class="fn-panel-head"><h2>How the score is built</h2><span class="fn-kicker">threshold {data.run["flag_threshold"]}</span></div>
  <div style="display: flex; height: 14px; border-radius: 7px; overflow: hidden; background: #1A212C; margin: 10px 0 8px">{segments}</div>
  {rows}
  <div class="fn-sum" style="display: flex; justify-content: space-between"><span>Score</span><span style="color: {theme.TEXT}; font-weight: 600">{network.score:.4f}</span></div>
</div>""")

    items = [(item["edge_type"], item["sentence"], float(item["strength"])) for item in network.evidence]
    items += [(item["code"], item["sentence"], float(item["value"])) for item in network.support]
    cards = "".join(f"""
<div style="padding: 12px 0; border-top: 1px solid #1E2632">
  <div style="display: flex; justify-content: space-between; gap: 8px"><span class="fn-kicker">{theme.esc(code)}</span>
  <span class="fn-mono" style="font-size: 12px; color: {theme.MUTED}">{value:.3f}</span></div>
  <div style="font-size: 13.5px; color: #C9D1DC; margin-top: 4px">{theme.esc(sentence)}</div>
</div>""" for code, sentence, value in items)
    discounted = Counter(link.get("explanation_code") or link.get("explanation") or "explained"
                         for link in network.detail.get("discounted_links", []))
    innocent = ("No innocent explanation applied inside this group. Families, busy buildings, storms and busy "
                "providers were all checked." if not discounted else
                "Explained away inside this group: " + ", ".join(f"{count} × {code}" for code, count in discounted.items()) + ".")
    st.html(f"""
<div style="margin-top: 10px; padding-top: 16px; border-top: 1px solid {theme.LINE}">
  <div class="fn-panel-head"><h2>Evidence</h2><span class="fn-kicker">as the detector wrote it</span></div>
  {cards}
  <div style="padding-top: 12px; border-top: 1px solid #1E2632; font-size: 13px; color: {theme.MUTED}">{theme.esc(innocent)}</div>
</div>""")

# ---- timeline
with st.container(border=True):
    st.html('<div class="fn-panel-head"><h2>What happened, and when</h2><span class="fn-kicker">one row per person</span></div>'
            f'<div style="color: {theme.MUTED}; font-size: 13.5px">Policy starts, incidents, invoices and payments for '
            'everyone in this group. A red line marks a day when most of them reported an incident.</div>')
    symbols = {"triangle-up": "&#9650;", "circle": "&#9679;", "diamond": "&#9670;", "square": "&#9632;"}
    key = "".join(f'<span style="display: inline-flex; align-items: center; gap: 6px"><span style="color: {colour}; font-size: 14px">'
                  f'{symbols[shape]}</span>{label}</span>' for label, shape, colour in TIMELINE_EVENTS.values())
    st.html(f'<div style="display: flex; gap: 18px; flex-wrap: wrap; font-size: 12.5px; color: {theme.MUTED}; margin-top: 6px">{key}</div>')
    chart = timeline(network)
    if chart is None:
        st.html(f'<div style="color: {theme.MUTED}">No dated events for this group.</div>')
    else:
        st.altair_chart(chart, theme=None, width="stretch")

st.html(f"""<div class="fn-foot">Run {theme.esc(data.run["run_id"])} · detector v{theme.esc(data.run["code_version"])} ·
graph drawn with Cytoscape.js (MIT) · this app reads detector output only, never the labels</div>""")
