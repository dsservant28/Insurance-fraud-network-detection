"""Data checks: is the data sound, what does it cover, and which records break the rules.

Layout: a header with the verdict, two equal panels (checks and coverage), then the data exceptions:
three equal type tiles and one table. Exceptions are reported, never hidden or silently fixed.
"""
from __future__ import annotations

import json

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.data import data_dir, exception_cases, load_reports
from fraudnet.investigate.workflow import EXCEPTION_ACTIONS

folder = data_dir()
reports = load_reports(folder)
summary = reports["summary"]
if summary is None:
    st.info("No validation report yet. Run `python -m fraudnet.run` first.")
    st.stop()

GOOD, BAD = "#7FE0B5", "#FF6A3D"
checks = summary["checks"]
passed = sum(1 for check in checks if check["status"] == "PASS")
repro = reports["reproducibility"]

# ---- header
left, right = st.columns([1.35, 1], gap="large", vertical_alignment="bottom")
with left:
    st.html(f"""<div class="fn-kicker">Data checks</div>
<div class="fn-title">{passed} of {len(checks)} checks pass</div>
<p class="fn-lede">Every dataset is checked before anything is detected. Records that break a business rule are
<b>reported as exceptions</b> and routed to a case, never silently fixed.</p>""")
with right:
    if repro:
        ok = repro["status"] == "PASS"
        repro_text = (f"{repro['files_identical']} of {repro['files_compared']} files identical when regenerated "
                      f"with seed {repro['seed']}")
    else:
        ok, repro_text = None, "Not run yet: python -m fraudnet.validate --reproducibility"
    colour = GOOD if ok else (BAD if ok is False else theme.FAINT)
    rows = summary["row_counts"]
    st.html(f"""
<div class="fn-card" style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; text-align: center">
  <div><div class="fn-mono" style="font-size: 22px; font-weight: 600">{rows.get('claim', 0):,}</div><div class="fn-kicker">claims</div></div>
  <div><div class="fn-mono" style="font-size: 22px; font-weight: 600">{rows.get('claimant', 0):,}</div><div class="fn-kicker">claimants</div></div>
  <div><div class="fn-mono" style="font-size: 22px; font-weight: 600">{rows.get('relationship_edge', 0):,}</div><div class="fn-kicker">edges</div></div>
</div>
<div style="margin-top: 10px; font-size: 13px; color: {colour}">● Reproducibility: {theme.esc(repro_text)}</div>""")

# ---- two equal panels: the checks, and what the data covers
PANEL = 566  # tall enough for all 12 checks; coverage scrolls inside the same height
one, two = st.columns(2, gap="large")
with one, st.container(border=True, height=PANEL):
    items = "".join(f"""
<div style="display: grid; grid-template-columns: 22px 54px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 0;
            border-top: 1px solid #1E2632">
  <span style="width: 12px; height: 12px; border-radius: 50%; background: {GOOD if c['status'] == 'PASS' else BAD}"></span>
  <span class="fn-mono" style="font-size: 12px; color: {theme.FAINT}">{theme.esc(c['id'])}</span>
  <span style="font-size: 14px">{theme.esc(c['name'])}</span>
  <span class="fn-mono" style="font-size: 12px; color: {GOOD if c['failure_count'] == 0 else BAD}">
    {'pass' if c['failure_count'] == 0 else str(c['failure_count']) + ' problems'}</span>
</div>""" for c in checks)
    st.html(f'<div class="fn-panel-head"><h2>Validation checks</h2><span class="fn-kicker">keys · joins · dates · arithmetic</span></div>{items}')

with two, st.container(border=True, height=PANEL):
    groups: dict[str, list[tuple[str, int]]] = {}
    for key, count in summary.get("coverage", {}).items():
        group, _, label = key.partition(": ")
        groups.setdefault(group, []).append((label, int(count)))
    order = ["normal", "open work", "boundary", "failure", "exception"]
    tint = {"normal": GOOD, "open work": theme.CYAN, "boundary": "#EED9A4", "failure": theme.AMBER, "exception": BAD}
    blocks = ""
    for group in [g for g in order if g in groups] + [g for g in groups if g not in order]:
        top = max(count for _, count in groups[group])
        bars = "".join(f"""
<div style="display: grid; grid-template-columns: minmax(0, 1fr) 120px 52px; gap: 10px; align-items: center; padding: 3px 0">
  <span style="font-size: 13px; color: #C9D1DC">{theme.esc(label.capitalize())}</span>
  <div style="height: 6px; border-radius: 3px; background: #1A212C"><div style="height: 6px; border-radius: 3px; width: {max(4, count / top * 100):.0f}%;
       background: {tint.get(group, theme.TEXT)}"></div></div>
  <span class="fn-mono" style="font-size: 12px; text-align: right">{count:,}</span>
</div>""" for label, count in sorted(groups[group], key=lambda item: -item[1]))
        blocks += f'<div class="fn-kicker" style="margin: 12px 0 4px; color: {tint.get(group, theme.FAINT)}">{theme.esc(group)}</div>{bars}'
    st.html(f'<div class="fn-panel-head"><h2>What the data covers</h2><span class="fn-kicker">bars compare within a group</span></div>{blocks}')

# ---- the exceptions
exceptions = reports["exceptions"]
cases = exception_cases(folder)
TYPES = {"ORPHAN_POLICY_REF": ("Claim names a missing policy", "EC-1"),
         "PAYMENT_OVER_APPROVED": ("Paid more than approved", "EC-2"),
         "DUPLICATE_INVOICE": ("One invoice on several claimants' claims", "EC-3")}


def _found(row: dict) -> str:
    kind, observed = row["exception_type"], row["observed_value"]
    if kind == "ORPHAN_POLICY_REF":
        return f"names policy {observed}, which does not exist"
    if kind == "PAYMENT_OVER_APPROVED":
        try:
            return f"paid ${int(observed) / 100:,.2f}, above the approved amount"
        except ValueError:
            return f"paid {observed}, above the approved amount"
    claimants = len(json.loads(row.get("detail_json") or "{}").get("claimant_ids", []))
    return f"invoice {observed} billed on {claimants} claimants' claims"


with st.container(border=True):
    st.html('<div class="fn-panel-head"><h2>Data exceptions</h2><span class="fn-kicker">reported, routed, never silently fixed</span></div>')
    tiles = st.columns(len(TYPES), gap="medium")
    for tile, (kind, (title, rule)) in zip(tiles, TYPES.items()):
        count = sum(1 for row in exceptions if row["exception_type"] == kind)
        with_case = sum(1 for row in exceptions if row["exception_type"] == kind and row["exception_id"] in cases)
        tile.html(f"""
<div style="padding: 14px 16px; border-radius: 12px; border: 1px solid {theme.LINE}; background: {theme.RAISED}">
  <div style="display: flex; justify-content: space-between; align-items: baseline">
    <span class="fn-kicker">{rule}</span><span class="fn-mono" style="font-size: 26px; font-weight: 600">{count}</span></div>
  <div style="font-size: 14.5px; font-weight: 600; margin-top: 4px">{title}</div>
  <div style="font-size: 12.5px; color: {theme.MUTED}; margin-top: 4px">Recommended: {EXCEPTION_ACTIONS[kind].replace('_', ' ').lower()} ·
    {with_case} with a case</div>
</div>""")
    header = ("<tr>" + "".join(f'<th style="text-align: left; padding: 10px 12px; font-family: {theme.MONO}; font-size: 11px; '
                               f'letter-spacing: .1em; text-transform: uppercase; color: {theme.FAINT}; font-weight: 500">{name}</th>'
                               for name in ("Exception", "Type", "Record", "What was found", "Case")) + "</tr>")
    body = ""
    for row in exceptions:
        case = cases.get(row["exception_id"])
        case_cell = (f'{theme.esc(case["investigation_id"])} · {theme.esc(case["status"].replace("_", " ").lower())}' if case
                     else f'<span style="color: {theme.FAINT}">none yet</span>')
        body += (f'<tr style="border-top: 1px solid #1E2632">'
                 f'<td class="fn-mono" style="padding: 9px 12px; font-size: 12.5px">{theme.esc(row["exception_id"])}</td>'
                 f'<td style="padding: 9px 12px; font-size: 13px">{theme.esc(TYPES.get(row["exception_type"], (row["exception_type"],))[0])}</td>'
                 f'<td class="fn-mono" style="padding: 9px 12px; font-size: 12.5px">{theme.esc(row["entity_id"])}</td>'
                 f'<td style="padding: 9px 12px; font-size: 13px; color: #C9D1DC">{theme.esc(_found(row))}</td>'
                 f'<td class="fn-mono" style="padding: 9px 12px; font-size: 12px">{case_cell}</td></tr>')
    st.html(f'<div style="max-height: 420px; overflow: auto; margin-top: 14px; border: 1px solid {theme.LINE}; border-radius: 10px">'
            f'<table style="width: 100%; border-collapse: collapse">{header}{body}</table></div>'
            f'<div style="font-size: 12.5px; color: {theme.MUTED}; margin-top: 10px">Open a case on any exception from the '
            '<b>Cases</b> page (Open a case → Data exception).</div>')
