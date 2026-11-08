"""Risk field: what needs review, highest risk first, and why. The investigator's starting page."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.charts import score_map
from fraudnet.app.data import Network, data_dir, load_overview
from fraudnet.app.plain import reason


@st.cache_data(show_spinner=False)
def _overview(folder: str):
    return load_overview(Path(folder))


data = _overview(str(data_dir()))
reasons = {network.network_id: reason(network) for network in data.networks}
by_id = {network.network_id: network for network in data.networks}
threshold = float(data.run["flag_threshold"])
flagged = data.flagged
state = st.session_state
state.setdefault("network", flagged[0].network_id if flagged else (data.networks[0].network_id if data.networks else None))

# A click on the map arrives as the chart's widget state; apply it before anything is drawn.
event = state.get("score_map")
picks = (event or {}).get("selection", {}).get("pick", []) if event else []
picked = picks[0].get("network_id") if picks else None
if picked and picked != state.get("map_pick"):
    state["map_pick"] = picked
    state["network"] = picked


def _select(network_id: str) -> None:
    state["network"] = network_id


def _row(network: Network) -> None:
    on = network.network_id == state["network"]
    colour = theme.PRIORITY.get(network.priority, theme.NOT_FLAGGED) if network.flagged else theme.NOT_FLAGGED
    first = round(network.strongest * 100, 1)
    rest = round(network.other * (1 - network.strongest) * 100, 1)
    left, right = st.columns([11, 2], vertical_alignment="center", gap="small")
    left.html(f"""
<div class="fn-row{' fn-row-on' if on else ''}">
  <div class="fn-row-top">
    <span class="fn-rank">{network.rank}</span><span class="fn-id">{theme.esc(network.network_id)}</span>
    {theme.chip(network.priority) if network.flagged else '<span class="fn-chip-outline">not flagged</span>'}
    <span class="fn-score" style="color: {colour}">{network.score:.4f}</span>
  </div>
  <div class="fn-reason">{theme.esc(reasons[network.network_id])}</div>
  <div class="fn-bar"><div style="width: {first}%; background: {colour}"></div><div style="width: {rest}%; background: {colour}; opacity: .45"></div></div>
</div>""")
    right.button("Viewing" if on else "View", key=f"view-{network.network_id}", disabled=on,
                 on_click=_select, args=(network.network_id,), width="stretch")


# ---- header
counts = data.run["counts"]
order = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
strip = "".join(f'<span class="fn-chip" style="background: {theme.PRIORITY[p]}">{counts["flagged_by_priority"].get(p, 0)} {p.lower()}</span>'
                for p in order if counts["flagged_by_priority"].get(p))
st.html(f"""
<div class="fn-kicker">Risk field · {data.claimants:,} claimants · {data.claims:,} claims</div>
<div class="fn-title">{len(flagged)} groups need review</div>
<p class="fn-lede">The detector rebuilt <b>{data.links:,} links</b> between claimants and cleared
<b>{counts["cleared_groups"]} innocent look-alike groups</b> on its own, such as families and busy buildings.
What is left is below, highest risk first.</p>
<div class="fn-strip">{strip}</div>""")

queue, side = st.columns([1.2, 1], gap="large")

with side:
    with st.container(border=True):
        st.html('<div class="fn-panel-head"><h2>Score map</h2><span class="fn-kicker">click a dot</span></div>'
                f'<div style="color: {theme.MUTED}; font-size: 13.5px">Anything above the amber line is flagged. '
                'Further up and to the right means stronger evidence.</div>')
        st.altair_chart(score_map(data.networks, reasons, threshold, state["network"]), key="score_map",
                        on_select="rerun", selection_mode="pick", theme=None, width="stretch")
    chosen = by_id.get(state["network"])
    if chosen:
        names = "".join(f'<span class="fn-name">{theme.esc(chosen.names.get(m, m))}</span>' for m in chosen.members)
        st.html(f"""
<div class="fn-card">
  <div class="fn-kicker">Selected · rank {chosen.rank} of {len(data.networks)}</div>
  <div style="display: flex; align-items: center; gap: 10px; margin-top: 6px; flex-wrap: wrap">
    <h3>{theme.esc(chosen.network_id)}</h3>{theme.chip(chosen.priority) if chosen.flagged else '<span class="fn-chip-outline">not flagged</span>'}
    <span class="fn-mono" style="margin-left: auto; font-weight: 600; font-size: 18px">{chosen.score:.4f}</span>
  </div>
  <p style="margin: 10px 0 0; font-size: 14.5px; color: #C9D1DC">{theme.esc(reasons[chosen.network_id])}</p>
  <div class="fn-names">{names}</div>
  <div class="fn-sum">score = 1 − (1 − {chosen.strongest:.3f}) × (1 − {chosen.other:.3f})</div>
</div>""")

with queue:
    st.html(f'<div class="fn-panel-head"><h2>Review queue</h2><span class="fn-kicker">{len(flagged)} flagged</span></div>')
    with st.container(height=900, border=False):
        for network in flagged:
            _row(network)
        below = [network for network in data.networks if not network.flagged]
        if below:
            st.html(f'<div class="fn-divider fn-kicker">Below the flag line · {len(below)} · shown for transparency</div>')
            for network in below:
                _row(network)

st.html(f"""<div class="fn-foot">Data: {theme.esc(data.folder.name)} · run {theme.esc(data.run["run_id"])} ·
detector v{theme.esc(data.run["code_version"])} · this app reads detector output only, never the labels</div>""")
