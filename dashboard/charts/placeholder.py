"""Consistent 'not available yet' block for panels blocked on a missing
Vantagepoint source (AP aging, earnings/labor, GL trial balance)."""
from __future__ import annotations

import streamlit as st


_DEFAULT_REMEDY = (
    "Drop a sample in `data/raw/`, implement the parser (`etl/parse_*.py`), "
    "and re-run `python etl/build_warehouse.py`."
)


def missing_source(needs: str, remedy: str = _DEFAULT_REMEDY):
    """Assumes the caller has already rendered its own st.subheader().

    `needs` should read naturally after "Not available yet -- needs ",
    e.g. "the AP aging export" or "a second fiscal year of warehouse
    history". `remedy` defaults to the standard "add a sample export"
    instructions; pass your own when the blocker isn't a missing source
    file (e.g. needs more monthly history to accumulate).
    """
    st.info(f"Not available yet -- needs {needs}. {remedy}", icon="⚠️")
