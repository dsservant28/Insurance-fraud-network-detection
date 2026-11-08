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

PAGES = Path(__file__).resolve().parent / "src" / "fraudnet" / "app" / "pages"
st.navigation([
    st.Page(PAGES / "risk_field.py", title="Risk field", icon=":material/radar:", default=True),
], position="top").run()
