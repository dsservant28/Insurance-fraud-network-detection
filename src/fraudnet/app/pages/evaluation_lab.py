"""Evaluation lab: how well the detector works, and where it stops working.

Reads only the committed aggregate summaries (docs/EVALUATION.json and docs/stress/*.json). Layout: a
header with four equal figures, two equal panels (comparisons and the stress grid), five edge-case tiles.
"""
from __future__ import annotations

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.data import load_evaluation

data = load_evaluation()
evaluation, v01, v02 = data["evaluation"], data["stress_v01"], data["stress_v02"]
if evaluation is None:
    st.info("No evaluation summary yet. Run `python -m fraudnet.evaluate --data data/output --doc docs/EVALUATION.md`.")
    st.stop()

dev, unseen = evaluation["development"], evaluation.get("unseen") or {}
GOOD, BAD = "#7FE0B5", "#FF6A3D"


def _hits(summary) -> str:
    return f"{sum(p['hit'] for p in summary['predictions'])}/{len(summary['predictions'])}" if summary else "–"


# ---- header
left, right = st.columns([1.2, 1], gap="large", vertical_alignment="bottom")
with left:
    st.html(f"""<div class="fn-kicker">Evaluation lab</div>
<div class="fn-title">How well it works</div>
<p class="fn-lede">Scored against the hidden labels, which only the evaluation reads. Then given data it was never designed
for, with every prediction <b>pushed to git before the run</b>.</p>""")
with right:
    figures = [(f"{dev['precision']:.3f}", "precision", "development seed"),
               (f"{unseen.get('recall', 0):.3f}" if unseen else "–", "ring recall", f"{len(unseen.get('seeds', []))} unseen seeds"),
               (_hits(v01), "predictions hit", "stress · v0.1"), (_hits(v02), "predictions hit", "stress · v0.2")]
    cells = "".join(f'<div><div class="fn-mono" style="font-size: 22px; font-weight: 600">{theme.esc(value)}</div>'
                    f'<div class="fn-kicker">{theme.esc(what)}</div><div style="font-size: 11.5px; color: {theme.FAINT}">'
                    f'{theme.esc(where)}</div></div>' for value, what, where in figures)
    st.html(f'<div class="fn-card" style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; '
            f'text-align: center">{cells}</div>')

PANEL = 560
one, two = st.columns(2, gap="large")

# ---- left: against simpler approaches
with one, st.container(border=True, height=PANEL):
    source = unseen if unseen.get("comparisons") else dev
    rows = [("This detector", source.get("precision", dev["precision"]), source.get("recall", dev["recall"]), True)]
    names = {"no_benign_explanations": "Without explaining away families, buildings and storms",
             "no_repetition": "Without the repetition rule",
             "provider_as_plain_link": "Treating a shared provider as a link",
             "any_shared_value": "Flag anyone who shares any value",
             "recorded_edges_only": "Trust the recorded relationship register"}
    for block in ("principles_off", "comparisons"):
        for key, values in source.get(block, {}).items():
            rows.append((names.get(key, key), values["precision"], values["recall"], False))
    items = "".join(f"""
<div style="padding: 10px 0; border-top: 1px solid #1E2632">
  <div style="font-size: 13.5px; font-weight: {600 if mine else 500}; color: {theme.TEXT if mine else '#C9D1DC'}">{theme.esc(name)}</div>
  <div style="display: grid; grid-template-columns: 70px minmax(0, 1fr) 48px; gap: 8px; align-items: center; margin-top: 6px">
    <span class="fn-kicker" style="font-size: 10px">precision</span>
    <div style="height: 7px; border-radius: 4px; background: #1A212C"><div style="height: 7px; border-radius: 4px; width: {p * 100:.1f}%; background: {theme.CYAN}"></div></div>
    <span class="fn-mono" style="font-size: 12px; text-align: right">{p:.3f}</span>
    <span class="fn-kicker" style="font-size: 10px">recall</span>
    <div style="height: 7px; border-radius: 4px; background: #1A212C"><div style="height: 7px; border-radius: 4px; width: {r * 100:.1f}%; background: {theme.AMBER}"></div></div>
    <span class="fn-mono" style="font-size: 12px; text-align: right">{r:.3f}</span>
  </div>
</div>""" for name, p, r, mine in rows)
    where = f"mean of seeds {', '.join(map(str, unseen['seeds']))}" if source is unseen else "development seed"
    st.html(f'<div class="fn-panel-head"><h2>Against simpler approaches</h2><span class="fn-kicker">{theme.esc(where)}</span></div>'
            f'<div style="font-size: 13px; color: {theme.MUTED}; margin-bottom: 6px">Take one idea away and a number falls.</div>{items}')

# ---- right: the stress grid
with two, st.container(border=True, height=PANEL):
    rows = [("S1a", "Cosmetic formats"), ("S1b", "Same value, other form"), ("S1c", "Typos"), ("S2", "Camouflaged rings"),
            ("S5a", "Register gaps"), ("S5b", "Missing bank details"), ("S5c", "Placeholder stories")]
    levels = ("0.25", "0.5", "0.75", "1.0")
    stops = [(0, (22, 29, 40)), (0.5, (36, 74, 92)), (0.8, (64, 168, 204)), (1, (214, 244, 252))]

    def colour(v):
        if v is None:
            return "#1A212C"
        for k in range(1, len(stops)):
            if v <= stops[k][0]:
                (a, ca), (b, cb) = stops[k - 1], stops[k]
                t = (v - a) / (b - a)
                return "rgb(" + ",".join(str(round(x + (y - x) * t)) for x, y in zip(ca, cb)) + ")"
        return "rgb(214,244,252)"

    def recall(summary, key):
        return (summary or {}).get("table", {}).get(key, {}).get("recall", {}).get("mean")

    head = "".join(f'<div class="fn-mono" style="font-size: 11px; color: {theme.FAINT}; text-align: center">{s}</div>' for s in levels)
    grid = f'<div></div>{head}'
    for code, name in rows:
        grid += f'<div style="font-size: 13px; align-self: center"><span class="fn-mono" style="color: {theme.FAINT}; font-size: 11px">{code}</span> {name}</div>'
        for level in levels:
            a, b = recall(v01, f"{code}@{level}"), recall(v02, f"{code}@{level}")
            ink = lambda v: "#0A0D12" if v is not None and v >= 0.72 else theme.TEXT  # noqa: E731
            grid += (f'<div style="position: relative; height: 46px; border-radius: 6px; overflow: hidden">'
                     f'<div style="position: absolute; inset: 0; background: {colour(a)}; clip-path: polygon(0 0, 100% 0, 0 100%)"></div>'
                     f'<div style="position: absolute; inset: 0; background: {colour(b)}; clip-path: polygon(100% 0, 100% 100%, 0 100%)"></div>'
                     f'<span class="fn-mono" style="position: absolute; left: 6px; top: 4px; font-size: 10.5px; font-weight: 600; color: {ink(a)}">'
                     f'{"–" if a is None else f"{a:.2f}"}</span>'
                     f'<span class="fn-mono" style="position: absolute; right: 6px; bottom: 4px; font-size: 10.5px; font-weight: 600; color: {ink(b)}">'
                     f'{"–" if b is None else f"{b:.2f}"}</span></div>')
    st.html(f"""<div class="fn-panel-head"><h2>Stress test · ring recall</h2><span class="fn-kicker">◤ v0.1 · ◢ v0.2</span></div>
<div style="font-size: 13px; color: {theme.MUTED}; margin-bottom: 10px">Each scenario damages the data a little more at each strength.
v0.2 fixed placeholder stories (S5c) and other identifier forms (S1b). Typos remain a known limit.</div>
<div style="display: grid; grid-template-columns: minmax(0, 1.6fr) repeat(4, minmax(0, 1fr)); gap: 6px">{grid}</div>
<div style="font-size: 12px; color: {theme.FAINT}; margin-top: 12px">v0.1: seeds {', '.join(map(str, (v01 or {}).get('seeds', [])))} ·
v0.2: confirmation seeds {', '.join(map(str, (v02 or {}).get('seeds', [])))}, unseen by either version. Full reports: docs/STRESS.md, docs/STRESS_V02.md.</div>""")

# ---- the five required edge cases
with st.container(border=True):
    st.html('<div class="fn-panel-head"><h2>Required edge cases</h2><span class="fn-kicker">development seed</span></div>')
    plain = {"EC-1": "Claim naming a missing policy goes to an exception", "EC-2": "Overpayment goes to payment review",
             "EC-3": "Duplicate invoices are flagged as a network", "EC-4": "Ring links missing from the register are found",
             "EC-5": "A busy address alone is not treated as proof"}
    for tile, (code, check) in zip(st.columns(5, gap="small"), dev["edge_cases"].items()):
        ok = check["status"] == "PASS"
        tile.html(f"""<div style="height: 128px; padding: 14px; border-radius: 12px; border: 1px solid {theme.LINE}; background: {theme.RAISED}">
  <div style="display: flex; justify-content: space-between; align-items: baseline"><span class="fn-kicker">{theme.esc(code)}</span>
  <span class="fn-mono" style="font-size: 12px; font-weight: 600; color: {GOOD if ok else BAD}">{theme.esc(check['status'])}</span></div>
  <div style="font-size: 13.5px; margin-top: 8px">{theme.esc(plain.get(code, check['rule']))}</div></div>""")
