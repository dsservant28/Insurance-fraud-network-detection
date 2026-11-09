"""How it works: the idea in two minutes, with real numbers from the loaded run.

Layout: a header, the five-stage pipeline (five equal tiles), one real group followed from raw data to its
score (four equal tiles), two equal panels (innocent explanations and the rarity curve), and four
equal tiles on what keeps the system honest.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from fraudnet.app import theme
from fraudnet.app.charts import rarity_curve
from fraudnet.app.data import data_dir, load_evaluation, load_overview, load_reports
from fraudnet.app.graph import LINK_LABEL
from fraudnet.app.plain import reason
from fraudnet.detect.config import load_config


@st.cache_data(show_spinner=False)
def _overview(path: str):
    return load_overview(Path(path))


folder = data_dir()
data = _overview(str(folder))
summary = load_reports(folder)["summary"] or {"checks": [], "exceptions": {}}
evaluation = (load_evaluation()["evaluation"] or {}).get("unseen", {})
settings, _ = load_config()
counts = data.run["counts"]


def tiles(items: list[tuple[str, str, str]], height: int) -> None:
    for column, (kicker, title, body) in zip(st.columns(len(items), gap="small"), items):
        column.html(f"""<div style="height: {height}px; padding: 16px; border-radius: 12px; border: 1px solid {theme.LINE};
  background: {theme.RAISED}; box-sizing: border-box">
  <div class="fn-kicker">{kicker}</div>
  <div style="font-size: 16px; font-weight: 600; margin-top: 8px">{title}</div>
  <div style="font-size: 13px; color: {theme.MUTED}; margin-top: 6px; line-height: 1.5">{body}</div></div>""")


def section(title: str, kicker: str) -> None:
    st.html(f'<div class="fn-panel-head" style="margin-top: 18px"><h2>{title}</h2><span class="fn-kicker">{kicker}</span></div>')


# ---- header
st.html("""<div class="fn-kicker">How it works</div>
<div class="fn-title">From raw records to explained suspicion</div>
<p class="fn-lede">Insurance records go in; a ranked, explained list of suspicious groups comes out. The detector
<b>never looks at the answers</b>: only the evaluation does, afterwards.</p>""")

# ---- 1. the pipeline
checks = summary["checks"]
passed = sum(1 for check in checks if check["status"] == "PASS")
exceptions = sum(summary.get("exceptions", {}).values())
try:
    with sqlite3.connect(folder / "fraudnet.db") as db:
        cases = db.execute("SELECT COUNT(*) FROM investigation").fetchone()[0]
except sqlite3.Error:
    cases = 0
recall = f"{evaluation['recall']:.3f} recall on {len(evaluation.get('seeds', []))} unseen seeds" if evaluation else "see docs/EVALUATION.md"
section("Five stages", "each one feeds the next")
tiles([
    ("1 · Generate", f"{data.claimants:,} claimants · {data.claims:,} claims",
     "Seeded synthetic data with deliberate fraud rings, innocent look-alikes and five required edge cases."),
    ("2 · Validate", f"{passed} of {len(checks)} checks pass",
     f"Keys, joins, dates and arithmetic are checked. {exceptions} records that break a rule are reported as exceptions."),
    ("3 · Detect", f"{data.links:,} links · {len(data.flagged)} flagged",
     "Links are rebuilt from raw values, innocent reasons are ruled out, and each group is scored and explained."),
    ("4 · Investigate", f"{cases} cases",
     "Analysts and reviewers work cases under the four-eyes rule, in a history that can't be rewritten."),
    ("5 · Evaluate", "Scored against the answers", f"Only this stage reads the labels: {recall}, plus a stress test."),
], height=190)

# ---- 2. one real group, step by step
top = data.flagged[0] if data.flagged else (data.networks[0] if data.networks else None)
if top is not None:
    strongest = max(top.evidence, key=lambda item: item["strength"])
    edge_type = strongest["edge_type"]
    cap = settings["links"]["caps"].get(edge_type, 0)
    rare = data.run["rarity"].get(edge_type, {"share": 0, "rarity": 1})
    discounted = top.detail.get("discounted_links", [])
    doubts, doubt = ["1"], 1.0
    for step in top.detail.get("waterfall", []):
        if step["added"] > 0:
            doubt -= step["added"]
            doubts.append(f"{doubt:.3f}")
    label = LINK_LABEL.get(edge_type, edge_type).lower()
    section(f"Following {top.network_id}, the top-ranked group", "four steps")
    tiles([
        ("Step 1 · Match raw values", "Who shares what?", reason(top)),
        ("Step 2 · Rule out innocent reasons", "None applies" if not discounted else f"{len(discounted)} links explained away",
         "A family at one address, a busy building, a storm or a busy provider would each discount the link. "
         + ("None of these fits this group." if not discounted else "Those links count for less.")),
        ("Step 3 · Weigh by rarity", f"{cap} × {rare['rarity']:.3f} = {cap * rare['rarity']:.3f}",
         f"Only {rare['share']:.1%} of claimants have an unexplained {label}, so the link keeps "
         f"{'nearly ' if rare['rarity'] < 1 else ''}its full weight."),
        ("Step 4 · Combine the evidence", f"Score {top.score:.4f}",
         f"Each kind of evidence removes part of the remaining doubt: {' → '.join(doubts)}. Score = 1 − doubt left. "
         f"Flagged at {data.run['flag_threshold']} or more."),
    ], height=210)

# ---- 3. two equal panels
explain = settings["explanations"]
cleared = counts.get("explained_links", {})
left, right = st.columns(2, gap="large")
with left, st.container(border=True, height=440):
    rules = [("Household", "Same surname at the same address", explain["household_factor"], cleared.get("HOUSEHOLD", 0)),
             ("Building", f"{explain['building_min_residents']} or more residents at one address", explain["building_factor"], cleared.get("BUILDING", 0)),
             ("Busy provider", "More customers than 95% of providers", explain["busy_provider_factor"], cleared.get("BUSY_PROVIDER", 0)),
             ("Common event", f"Similar stories in one city within {explain['common_event_days']} days", explain["common_event_factor"], cleared.get("COMMON_EVENT", 0))]
    rows = "".join(f"""<div style="display: grid; grid-template-columns: minmax(0, 1fr) 70px 90px; gap: 12px; align-items: center;
  padding: 12px 0; border-top: 1px solid #1E2632">
  <div><div style="font-size: 14.5px; font-weight: 600">{name}</div><div style="font-size: 12.5px; color: {theme.MUTED}">{test}</div></div>
  <div class="fn-mono" style="font-size: 14px; text-align: right; color: {theme.CYAN}">× {factor}</div>
  <div class="fn-mono" style="font-size: 13px; text-align: right">{count:,} {'link' if count == 1 else 'links'}</div></div>""" for name, test, factor, count in rules)
    st.html(f'<div class="fn-panel-head"><h2>Innocent explanations</h2><span class="fn-kicker">factor · cleared in this run</span></div>'
            f'<div style="font-size: 13px; color: {theme.MUTED}; margin-bottom: 4px">Sharing an address or provider is often innocent. '
            f'These rules shrink such links before they can count.</div>{rows}')
with right, st.container(border=True, height=440):
    st.html('<div class="fn-panel-head"><h2>Rarity</h2><span class="fn-kicker">weights come from the data</span></div>'
            f'<div style="font-size: 13px; color: {theme.MUTED}">A kind of link few people have keeps its full weight; a common one '
            'is discounted, never below half. Each dot is a real link type in this run.</div>')
    st.altair_chart(rarity_curve(data.run["rarity"], settings["rarity"]["reference_log10"], settings["rarity"]["floor"]),
                    theme=None, width="stretch")

# ---- 4. what keeps it honest
section("What keeps it honest", "checked automatically")
tiles([
    ("Labels never read", "Answers stay separate", "An automatic check blocks the detector and this app from naming the label files or columns."),
    ("Reproducible", "Same seed, same bytes", "Regenerating with the same seed gives byte-identical files, checked file by file."),
    ("Sealed history", "Nothing can be rewritten", "Database triggers block edits and deletes; a hash chain shows any tampering."),
    ("Predictions first", "Tested on the unknown", "Stress-test predictions were pushed to git before any stress run, then scored as hit or miss."),
], height=170)
