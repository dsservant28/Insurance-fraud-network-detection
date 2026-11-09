"""Entry point: streamlit run streamlit_app.py

Streamlit Community Cloud runs this file from the repository root without installing the
package, so `src/` is put on the path here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from fraudnet.app import theme  # noqa: E402

st.set_page_config(page_title="FraudNet · Investigator console", page_icon=":material/radar:", layout="wide")
theme.apply()
st.logo(str(Path(__file__).resolve().parent / "src" / "fraudnet" / "app" / "assets" / "logo.svg"), size="large")

from fraudnet.app import bootstrap  # noqa: E402


@st.cache_resource(show_spinner=False)
def _first_start() -> bool:
    """Build data/output once per server when it is missing (a fresh hosted deployment)."""
    if not bootstrap.needed():
        return False
    with st.spinner("Building the dataset: first start only, about a minute…"):
        return bootstrap.build()


_first_start()

PAGES = Path(__file__).resolve().parent / "src" / "fraudnet" / "app" / "pages"
st.navigation([
    st.Page(PAGES / "risk_field.py", title="Risk field", icon=":material/radar:", default=True),
    st.Page(PAGES / "network_dossier.py", title="Network dossier", icon=":material/hub:"),
    st.Page(PAGES / "cases.py", title="Cases", icon=":material/gavel:"),
    st.Page(PAGES / "data_checks.py", title="Data checks", icon=":material/fact_check:"),
    st.Page(PAGES / "evaluation_lab.py", title="Evaluation lab", icon=":material/science:"),
    st.Page(PAGES / "how_it_works.py", title="How it works", icon=":material/lightbulb:"),
], position="top").run()
