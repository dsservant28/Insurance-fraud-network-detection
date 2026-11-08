"""The score map: every network at (strongest evidence, all other evidence combined).

A network's score is 1 - (1 - x)(1 - y), so the contour lines are exact: everything above the
flag line is flagged. Built with Altair, which ships with Streamlit.
"""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd

from fraudnet.app import theme
from fraudnet.app.data import Network

LEVELS = (0.6, 0.7, 0.8, 0.9)


def _contour(level: float, x_min: float, y_max: float) -> pd.DataFrame:
    xs = np.linspace(x_min, level, 160)
    ys = 1 - (1 - level) / (1 - xs)
    keep = (ys >= 0) & (ys <= y_max)
    return pd.DataFrame({"x": xs[keep], "y": ys[keep], "level": level})


def points(networks: list[Network], reasons: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{
        "network_id": n.network_id, "x": round(n.strongest, 4), "y": n.other, "score": n.score,
        "priority": n.priority if n.flagged else "Not flagged", "members": len(n.members), "reason": reasons[n.network_id],
    } for n in networks])


def score_map(networks: list[Network], reasons: dict[str, str], threshold: float, selected: str | None) -> alt.LayerChart:
    data = points(networks, reasons)
    x_min = min(0.2, float(data["x"].min()) - 0.05) if len(data) else 0.2
    y_max = min(1.0, max(0.7, float(data["y"].max()) + 0.08)) if len(data) else 0.7
    x_axis = alt.X("x:Q", title="Strongest evidence", scale=alt.Scale(domain=[x_min, 1.0]), axis=alt.Axis(format=".1f"))
    y_axis = alt.Y("y:Q", title="Other evidence, combined", scale=alt.Scale(domain=[0, y_max]), axis=alt.Axis(format=".1f"))

    xs = np.linspace(x_min, 1.0, 200)
    low = np.where(xs < threshold, np.clip(1 - (1 - threshold) / (1 - np.minimum(xs, threshold)), 0, y_max), 0.0)
    zone = alt.Chart(pd.DataFrame({"x": xs, "low": low, "top": y_max})).mark_area(color=theme.AMBER, opacity=0.08).encode(
        x=x_axis, y="low:Q", y2="top:Q")

    faint = pd.concat([_contour(level, x_min, y_max) for level in LEVELS if level != threshold], ignore_index=True)
    others = alt.Chart(faint).mark_line(color="#6B5A3C", strokeDash=[2, 5], strokeWidth=1.2).encode(
        x=x_axis, y=y_axis, detail="level:N")
    flag_line = alt.Chart(_contour(threshold, x_min, y_max)).mark_line(color=theme.AMBER, strokeWidth=2.5).encode(x=x_axis, y=y_axis)
    label_x = x_min + 0.01
    label_y = min(y_max, 1 - (1 - threshold) / (1 - label_x))
    flag_label = alt.Chart(pd.DataFrame({"x": [label_x], "y": [label_y], "text": [f"flag line · score {threshold:g}"]})).mark_text(
        color=theme.AMBER, align="left", dx=4, dy=-12, font="JetBrains Mono", fontSize=11).encode(x=x_axis, y=y_axis, text="text:N")

    pick = alt.selection_point(name="pick", fields=["network_id"], on="click", empty=False)
    colours = list(theme.PRIORITY.items()) + [("Not flagged", theme.NOT_FLAGGED)]
    dots = alt.Chart(data).mark_circle(size=150, opacity=0.95, stroke=theme.INK, strokeWidth=1.5).encode(
        x=x_axis, y=y_axis,
        color=alt.Color("priority:N", title=None, scale=alt.Scale(domain=[name for name, _ in colours], range=[c for _, c in colours]),
                        legend=alt.Legend(orient="bottom", direction="horizontal", labelColor=theme.MUTED, symbolStrokeWidth=0)),
        tooltip=[alt.Tooltip("network_id:N", title="Network"), alt.Tooltip("score:Q", title="Score", format=".4f"),
                 alt.Tooltip("priority:N", title="Priority"), alt.Tooltip("reason:N", title="Why")],
    ).add_params(pick)

    layers = [zone, others, flag_line, flag_label, dots]
    if selected and selected in set(data["network_id"]):
        ring = alt.Chart(data[data["network_id"] == selected]).mark_point(
            size=650, shape="circle", filled=False, color=theme.CYAN, strokeWidth=2.5).encode(x=x_axis, y=y_axis)
        layers.append(ring)

    return _style(alt.layer(*layers).properties(height=430, background="transparent"))


def _style(chart):
    return chart.configure_view(stroke=None).configure_axis(
        labelColor=theme.FAINT, titleColor=theme.MUTED, gridColor="#1E2632", domainColor="#3A4658", tickColor="#3A4658",
        labelFont="JetBrains Mono", titleFont="Inter", titleFontWeight=500, titleFontSize=12,
    ).configure_legend(labelFont="Inter", labelFontSize=12, labelColor=theme.MUTED)


TIMELINE_EVENTS = {"POLICY_START": ("Policy started", "triangle-up", "#8F9BAE"), "INCIDENT": ("Incident", "circle", "#E9EDF3"),
                   "INVOICE": ("Invoice", "diamond", "#F4A62A"), "PAYMENT": ("Payment", "square", "#5BC6E8")}


def timeline_events(network: Network) -> pd.DataFrame:
    rows = [dict(item) for item in network.detail.get("timeline", []) if item["event"] in TIMELINE_EVENTS]
    frame = pd.DataFrame(rows, columns=["date", "event", "claimant_id", "claim_id", "ref"])
    if frame.empty:
        return frame.assign(name=[], kind=[])
    frame = frame.drop_duplicates(["date", "event", "claimant_id", "ref"])
    frame["name"] = frame["claimant_id"].map(lambda cid: f"{network.names.get(cid, cid)} · {cid}")
    frame["kind"] = frame["event"].map(lambda event: TIMELINE_EVENTS[event][0])
    incidents = frame[frame["event"] == "INCIDENT"]
    if not incidents.empty:  # policy starts long before the first incident would squash the view
        start = pd.Timestamp(incidents["date"].min()) - pd.Timedelta(days=45)
        frame = frame[pd.to_datetime(frame["date"]) >= start]
    return frame.reset_index(drop=True)


def same_day_incidents(network: Network, frame: pd.DataFrame) -> pd.DataFrame:
    """Days on which at least half the group (and at least 3 people) reported an incident."""
    incidents = frame[frame["event"] == "INCIDENT"]
    need = max(3, -(-len(network.members) // 2))
    per_day = incidents.groupby("date")["claimant_id"].nunique()
    days = per_day[per_day >= need]
    return pd.DataFrame({"date": days.index, "people": days.values,
                         "text": [f"{n} of {len(network.members)} report an incident" for n in days.values]})


def timeline(network: Network) -> alt.LayerChart | None:
    frame = timeline_events(network)
    if frame.empty:
        return None
    order = [f"{network.names.get(m, m)} · {m}" for m in network.members]
    kinds = [label for label, _, _ in TIMELINE_EVENTS.values()]
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, tickCount={"interval": "month", "step": 1}))
    y = alt.Y("name:N", title=None, sort=order, axis=alt.Axis(labelFont="Inter", labelFontSize=12, labelLimit=260))
    marks = alt.Chart(frame).mark_point(filled=True, size=90, opacity=0.95).encode(
        x=x, y=y,
        shape=alt.Shape("kind:N", title=None, scale=alt.Scale(domain=kinds, range=[s for _, s, _ in TIMELINE_EVENTS.values()]),
                        legend=None),  # the page draws its own key above the chart
        color=alt.Color("kind:N", title=None, scale=alt.Scale(domain=kinds, range=[c for _, _, c in TIMELINE_EVENTS.values()]),
                        legend=None),
        tooltip=[alt.Tooltip("date:T", title="Date", format="%d %b %Y"), alt.Tooltip("kind:N", title="Event"),
                 alt.Tooltip("claim_id:N", title="Claim"), alt.Tooltip("ref:N", title="Reference"), alt.Tooltip("name:N", title="Who")])
    layers = [marks]
    bursts = same_day_incidents(network, frame)
    if not bursts.empty:
        rule = alt.Chart(bursts).mark_rule(color=theme.PRIORITY["CRITICAL"], strokeWidth=2, opacity=0.7).encode(
            x="date:T", tooltip=[alt.Tooltip("date:T", format="%d %b %Y", title="Date"), alt.Tooltip("text:N", title="Same day")])
        label = alt.Chart(bursts).mark_text(color="#FF9A66", align="left", dx=6, dy=-6, font="JetBrains Mono", fontSize=11).encode(
            x="date:T", y=alt.value(0), text="text:N")
        layers = [rule, label, marks]
    height = max(160, 44 * len(order))
    return _style(alt.layer(*layers).properties(height=height, background="transparent"))
