"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window:
FY revenue by entity, FY vs prior FY, originations pacing vs. target,
practice-group profitability.

FY revenue renders today as a WIP-value proxy (clearly captioned as such
-- real recognized revenue needs GL/earnings). The other three panels are
hard-blocked: FY-vs-prior-FY needs a second fiscal year of history,
originations needs an originating-attorney field no sample export has
shown, and practice-group profitability needs both a practice-group
taxonomy and real cost data.
"""
from __future__ import annotations

import datetime

import streamlit as st

import config
from dashboard.charts.placeholder import missing_source
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
    if not table_exists("wip_by_matter"):
        missing_source("the GL trial balance / project earnings & labor export")
        return
    df = query(
        """
        SELECT snapshot_date, company AS entity, SUM(wip_amount) AS value
        FROM wip_by_matter
        GROUP BY snapshot_date, company
        ORDER BY snapshot_date, company
        """
    )
    if df.empty:
        st.info("No WIP-by-entity data available.")
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
        "Proxy: WIP billing value by entity, not recognized revenue -- needs the GL trial "
        "balance / earnings export for the real figure. Shaded band marks the current fiscal "
        "year window."
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
    st.subheader("Originations Tracking vs. Target")
    if not config.ORIGINATION_TARGETS:
        missing_source(
            "an originating-attorney field per matter, plus targets in `config.ORIGINATION_TARGETS`",
            remedy=(
                "Chart component is ready (`dashboard/charts/grouped_bar.py::bar_with_target`) -- "
                "needs an originating-attorney column (not present in AR, WIP, or receipts exports; "
                "likely a Vantagepoint matter custom field) and targets filled into "
                "`config.ORIGINATION_TARGETS`."
            ),
        )
        return
    st.info("Targets are configured but originating-attorney data isn't available to plot against them yet.")


def _section_practice_group_profitability():
    st.subheader("Practice Group Profitability (FY-to-Date)")
    missing_source("a practice-group taxonomy plus the GL trial balance / earnings exports for real cost and margin")
