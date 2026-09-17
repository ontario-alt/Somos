"""
Streamlit entrypoint. Run with:

    streamlit run dashboard/app.py

Local run only for v1 -- no hosted deployment.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

import config
from dashboard.data import warehouse_last_built
from dashboard.report_pages import expenses, measuring_period, monthly, quarterly, weekly

st.set_page_config(page_title="Somos Group Executive Dashboard", layout="wide", page_icon="\U0001f4ca")

with st.sidebar:
    st.title("Somos Group")
    st.caption("Executive Dashboard")

    last_built = warehouse_last_built()
    if last_built:
        st.caption(f"Warehouse last built: {last_built}")
    else:
        st.warning("Warehouse not built yet.")

    if st.button("\U0001f504 Refresh data", use_container_width=True, help="Re-run the ETL against whatever's newest in data/raw/"):
        with st.spinner("Rebuilding warehouse from data/raw/..."):
            from etl.build_warehouse import build

            build()
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Warehouse rebuilt.")
        st.rerun()

    st.caption(f"Raw data folder: `{config.RAW_DATA_DIR}`")

    st.divider()
    page_name = st.radio(
        "Report",
        ["Monthly", "Weekly", "Quarterly", "Measuring Period", "Executive Expenses"],
        label_visibility="collapsed",
    )

pages = {
    "Monthly": monthly.render,
    "Weekly": weekly.render,
    "Quarterly": quarterly.render,
    "Measuring Period": measuring_period.render,
    "Executive Expenses": expenses.render,
}

try:
    pages[page_name]()
except FileNotFoundError as e:
    st.error(str(e))
