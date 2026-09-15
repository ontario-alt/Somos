"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window:
FY revenue by entity, FY vs prior FY, originations pacing vs. target,
practice-group profitability.

FY revenue now uses real GL trial balance revenue by entity. The
origination credit matrix (etl/parse_originations.py) gives real
originating-attorney credit fractions per matter, but dollarizing them
needs a revenue figure joined by matter -- and the origination matrix's
matter names don't reliably match AR/WIP matter names (checked: ~16%
match rate against AR by exact-normalized name), so this page shows
credit-fraction totals (matter counts, not dollars) rather than a
fabricated target-vs-actual dollar chart. FY-vs-prior-FY needs a second
fiscal year of history, and practice-group profitability needs a
practice-group taxonomy (still not present in any source).
"""
from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

import config
from dashboard.charts.placeholder import missing_source
from dashboard.charts.ranked_bar import ranked_bar
from dashboard.charts.trend_line import trend_line
from dashboard.data import query, table_exists


def render():
    st.title("Measuring Period (FY 10/1-9/30)")

    fy_start, fy_end = config.fiscal_year_bounds(datetime.date.today())
    st.caption(f"Current fiscal year: {fy_start:%b %d, %Y} - {fy_end:%b %d, %Y}")

    _section_fy_revenue(fy_start, fy_end)
    st.divider()
    _section_fy_vs_prior_fy()
    st.divider()
    _section_originations()
    st.divider()
    _section_practice_group_profitability()


def _section_fy_revenue(fy_start: datetime.date, fy_end: datetime.date):
    st.subheader("Fiscal-Year Revenue by Entity")
    if not table_exists("gl_trial_balance"):
        missing_source("the GL trial balance export")
        return
    df = query(
        """
        SELECT snapshot_date, entity, -SUM(closing_balance) AS value
        FROM gl_trial_balance
        WHERE account_type = 'Revenue'
        GROUP BY snapshot_date, entity
        ORDER BY snapshot_date, entity
        """
    )
    if df.empty:
        st.info("No GL revenue data available.")
        return
    fig = trend_line(
        df,
        x_col="snapshot_date",
        y_col="value",
        series_col="entity",
        shaded_band=(fy_start, fy_end),
        shaded_band_label="Current FY",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Recognized revenue from the GL trial balance, by entity. One point per snapshot "
        "today -- fills into a real within-FY trend as build_warehouse.py accumulates monthly "
        "trial balance snapshots. Shaded band marks the current fiscal year window."
    )


def _section_fy_vs_prior_fy():
    st.subheader("FY vs. Prior FY (Same Period to Date)")
    n_years = (
        query("SELECT COUNT(DISTINCT EXTRACT(YEAR FROM snapshot_date)) AS n FROM wip_by_matter").iloc[0]["n"]
        if table_exists("wip_by_matter")
        else 0
    )
    if n_years < 2:
        missing_source(
            "a second fiscal year of warehouse history (only the current FY is loaded)",
            remedy=(
                "Chart component is ready (`dashboard/charts/grouped_bar.py::grouped_bar_by_series`) "
                "-- wire it up once a prior-FY snapshot is in the warehouse."
            ),
        )
        return
    st.info("Multiple fiscal years detected but this panel's query isn't wired up yet.")


def _section_originations():
    st.subheader("Originations Tracking")
    if not table_exists("originations"):
        missing_source("the origination credit matrix export")
        return
    df = query(
        """
        SELECT attorney, SUM(credit_fraction) AS matter_credits
        FROM originations
        GROUP BY attorney
        ORDER BY matter_credits DESC
        """
    )
    fig = ranked_bar(df, label_col="attorney", value_col="matter_credits", top_n=15, value_is_currency=False)
    st.plotly_chart(fig, use_container_width=True)

    if not config.ORIGINATION_TARGETS:
        st.caption(
            "Shown in matter-credits (sum of each attorney's credit fraction across matters), "
            "not dollars -- dollarizing needs a revenue figure joined by matter, and the "
            "origination matrix's matter names only match AR's ~16% of the time by exact "
            "normalized name (checked directly), so a $ join here would silently misreport "
            "most matters. Fix at the source: have the origination export carry the same "
            "matter code AR/WIP use (e.g. \"LLC25-002\"), not just a free-text matter name. "
            "`config.ORIGINATION_TARGETS` is also still empty. Once both are in place, "
            "`dashboard/charts/grouped_bar.py::bar_with_target` renders actual-vs-target."
        )
    else:
        st.caption(
            "Targets are configured but originations still can't be dollarized -- see above. "
            "Matter-credits shown instead."
        )

    flagged = query("SELECT status, COUNT(*) AS matters FROM originations_flagged GROUP BY status ORDER BY matters DESC") if table_exists("originations_flagged") else pd.DataFrame()
    if not flagged.empty:
        st.markdown("**Matters needing attention**")
        st.dataframe(flagged, use_container_width=True, hide_index=True)


def _section_practice_group_profitability():
    st.subheader("Practice Group Profitability (FY-to-Date)")
    missing_source("a practice-group taxonomy plus the GL trial balance / earnings exports for real cost and margin")
