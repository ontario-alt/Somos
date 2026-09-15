"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window:
FY revenue by entity, FY vs prior FY, originations pacing vs. target,
practice-group profitability.

Not built yet -- blocked on the same missing pieces as the monthly
P&L panel (GL trial balance for real revenue/margin) plus two things no
sample export has shown yet: an originating-attorney field per matter,
and multiple fiscal years of warehouse history for the prior-FY
comparison. config.ORIGINATION_TARGETS is already wired up in config.py
for when targets are set.
"""
from __future__ import annotations

import streamlit as st

import config


def render():
    st.title("Measuring Period (FY 10/1-9/30)")
    st.info(
        "Not built yet -- blocked on: (1) GL trial balance / earnings for real "
        "revenue figures, (2) an originating-attorney field, not present in any "
        "sample export so far, and (3) more than one fiscal year of warehouse "
        "history for the FY-vs-prior-FY comparison.",
        icon="\U0001f4c5",
    )
    if not config.ORIGINATION_TARGETS:
        st.caption("`config.ORIGINATION_TARGETS` is also still empty -- fill it in when ready.")
