"""
Quarterly dashboard -- trend/roll-up views built from monthly warehouse
history (AR trend, WIP aging trend, revenue by matter type, realization
trend, client concentration, prior-year variance).

Not built yet: every panel here needs multiple monthly snapshots
accumulated in `snapshot_date` over time, and the warehouse currently
holds exactly one. Building this page against a single snapshot would
mean either faking a trend or shipping charts that are trivially a
single point -- not real reporting. Once a few months of
`build_warehouse.py` runs have accumulated, this page gets built the
same way monthly.py was: query snapshot_date-partitioned aggregates,
reuse dashboard/charts/stacked_column.py and a new trend-line component.
"""
from __future__ import annotations

import streamlit as st

from dashboard.data import query, table_exists


def render():
    st.title("Quarterly Report")
    st.info(
        "Not built yet -- every panel on this page (AR trend, WIP aging trend, "
        "realization trend, client concentration, prior-year variance) needs "
        "multiple months of warehouse history to show a trend. Run "
        "`python etl/build_warehouse.py` monthly for a few months and this page "
        "is next.",
        icon="\U0001f4c8",
    )
    if table_exists("ar_aging"):
        n = query("SELECT COUNT(DISTINCT snapshot_date) AS n FROM ar_aging").iloc[0]["n"]
        st.caption(f"Snapshots currently in the warehouse: {n}")
