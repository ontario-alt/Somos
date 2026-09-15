"""Consistent 'not available yet' block for panels blocked on a missing
Vantagepoint source (AP aging, earnings/labor, GL trial balance)."""
from __future__ import annotations

import streamlit as st


def missing_source(title: str, needs: str):
    """Assumes the caller has already rendered its own st.subheader(title)."""
    st.info(
        f"Not available yet -- needs the **{needs}** export, which hasn't been "
        "provided. Drop a sample in `data/raw/`, implement the parser "
        "(`etl/parse_*.py`), and re-run `python etl/build_warehouse.py`.",
        icon="⚠️",
    )
