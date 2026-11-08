"""The console's look: colours, type and the shared CSS. One place, so every page matches."""
from __future__ import annotations

import html

import streamlit as st

INK, PANEL, RAISED, LINE = "#0A0D12", "#11161E", "#0E131A", "#232C3A"
TEXT, MUTED, FAINT = "#E9EDF3", "#A6B0C0", "#8F9BAE"
AMBER, CYAN = "#F4A62A", "#5BC6E8"
# Told apart by lightness as well as hue: red-orange, amber, pale sand, grey.
PRIORITY = {"CRITICAL": "#FF6A3D", "HIGH": "#F4A62A", "MEDIUM": "#EED9A4", "LOW": "#8E877B"}
NOT_FLAGGED = "#5BC6E8"
FONT, MONO, DISPLAY = "Inter, system-ui, sans-serif", "'JetBrains Mono', ui-monospace, monospace", "'Space Grotesk', Inter, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background: {INK}; color: {TEXT}; font-family: {FONT}; }}
[data-testid="stHeader"] {{ background: transparent; }}
/* Keep the toolbar: the page navigation lives inside it. Hide only the deploy button and the main menu. */
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"], footer, #MainMenu {{ display: none; }}
[data-testid="stHeader"] {{ background: #0C1016; border-bottom: 1px solid #1C2430; }}
[data-testid="stTopNav"] a, [data-testid="stTopNav"] button {{ font-family: {FONT}; font-weight: 500; }}
[data-testid="stMainBlockContainer"] {{ max-width: 1376px; padding-top: 5.2rem; padding-bottom: 4rem; }}
h1, h2, h3 {{ font-family: {DISPLAY}; letter-spacing: -0.01em; }}
.fn-kicker {{ font-family: {MONO}; font-size: 11px; font-weight: 500; letter-spacing: .14em; text-transform: uppercase; color: {FAINT}; }}
.fn-mono {{ font-family: {MONO}; font-variant-numeric: tabular-nums; }}
.fn-title {{ font-family: {DISPLAY}; font-size: 44px; line-height: 1.05; font-weight: 600; margin: 6px 0 10px; color: {TEXT}; }}
.fn-lede {{ color: {MUTED}; font-size: 17px; margin: 0; max-width: 860px; }}
.fn-lede b {{ color: {TEXT}; font-weight: 600; }}
.fn-strip {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.fn-chip {{ font-family: {MONO}; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 8px; color: #14100A; }}
.fn-chip-outline {{ font-family: {MONO}; font-size: 12px; padding: 4px 10px; border-radius: 8px; border: 1px solid {LINE}; color: {MUTED}; }}
.fn-panel-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 0 0 6px; }}
.fn-panel-head h2 {{ margin: 0; font-size: 20px; font-weight: 600; color: {TEXT}; }}
.fn-row {{ padding: 12px 14px; border-radius: 10px; border: 1px solid #1E2632; background: {RAISED}; }}
.fn-row-on {{ border-color: {CYAN}; box-shadow: 0 0 0 1px {CYAN} inset; }}
.fn-row-top {{ display: flex; align-items: baseline; gap: 10px; }}
.fn-rank {{ font-family: {MONO}; font-size: 12px; color: {FAINT}; width: 22px; }}
.fn-id {{ font-family: {MONO}; font-weight: 600; font-size: 14px; color: {TEXT}; }}
.fn-score {{ font-family: {MONO}; font-weight: 600; margin-left: auto; }}
.fn-reason {{ margin: 6px 0 8px 32px; font-size: 14px; line-height: 1.45; color: #C9D1DC; }}
.fn-bar {{ display: flex; height: 6px; margin-left: 32px; border-radius: 3px; overflow: hidden; background: #1A212C; }}
.fn-divider {{ margin: 18px 0 8px; }}
.fn-card {{ padding: 16px 18px; border-radius: 12px; border: 1px solid {LINE}; background: {PANEL}; }}
.fn-card h3 {{ margin: 0; font-size: 22px; font-family: {MONO}; }}
.fn-sum {{ font-family: {MONO}; font-size: 13px; color: {MUTED}; margin-top: 10px; }}
.fn-names {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
.fn-name {{ font-size: 12.5px; padding: 3px 8px; border-radius: 6px; border: 1px solid #2C3646; color: {TEXT}; }}
.fn-foot {{ font-family: {MONO}; font-size: 12px; color: {FAINT}; margin-top: 28px; border-top: 1px solid #1C2430; padding-top: 14px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {LINE} !important; background: {PANEL}; border-radius: 14px !important; }}
.stButton > button {{ min-height: 40px; border-radius: 10px; border: 1px solid #2C3646; background: transparent; color: {TEXT}; font-weight: 600; }}
.stButton > button:hover {{ border-color: {CYAN}; color: {TEXT}; }}
</style>
"""


def apply() -> None:
    st.html(CSS)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def chip(priority: str) -> str:
    return f'<span class="fn-chip" style="background: {PRIORITY.get(priority, NOT_FLAGGED)}">{esc(priority)}</span>'
