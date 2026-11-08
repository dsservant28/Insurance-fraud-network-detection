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

    return alt.layer(*layers).properties(height=430, background="transparent").configure_view(stroke=None).configure_axis(
        labelColor=theme.FAINT, titleColor=theme.MUTED, gridColor="#1E2632", domainColor="#3A4658", tickColor="#3A4658",
        labelFont="JetBrains Mono", titleFont="Inter", titleFontWeight=500, titleFontSize=12,
    ).configure_legend(labelFont="Inter", labelFontSize=12)
