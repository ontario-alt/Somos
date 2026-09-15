"""
Quarterly dashboard -- trend/roll-up views built from monthly warehouse
history (AR trend, WIP aging trend, revenue by matter type, realization
trend, client concentration, prior-year variance).

Every panel here is snapshot_date-partitioned, so with the single
snapshot currently in the warehouse each trend renders as one point per
series -- honest, not a fabricated line -- and fills in as
build_warehouse.py accumulates more months. Two panels (revenue by
matter type, realization trend) are hard-blocked regardless of history
depth: they need data this warehouse doesn't have yet (a matter-type/
practice-area taxonomy, and a billed-vs-worked source distinct from WIP).
"""
from __future__ import annotations

import streamlit as st

import pandas as pd

from dashboard.charts.placeholder import missing_source
from dashboard.charts.stacked_area import stacked_area_by_series
from dashboard.charts.trend_line import trend_line
from dashboard.charts.variance_table import variance_table
from dashboard.data import query, table_exists


def _month_label(d) -> str:
    return pd.Timestamp(d).strftime("%b %Y")


def render():
    st.title("Quarterly Report")

    n_snapshots = (
        query("SELECT COUNT(DISTINCT snapshot_date) AS n FROM ar_aging").iloc[0]["n"]
        if table_exists("ar_aging")
        else 0
    )
    st.caption(
        f"{n_snapshots} snapshot(s) in the warehouse. Trend panels below render one point per "
        "snapshot -- run `python etl/build_warehouse.py` monthly to build up real trend lines."
    )

    _section_ar_trend()
    st.divider()
    _section_monthly_billings()
    st.divider()
    _section_wip_aging_trend()
    st.divider()
    _section_revenue_by_matter_type()
    st.divider()
    _section_realization_trend()
    st.divider()
    _section_client_concentration()
    st.divider()
    _section_variance_by_entity()


def _section_ar_trend():
    st.subheader("AR Trend by Entity")
    if not table_exists("ar_aging"):
        missing_source("the AR aging export")
        return
    df = query(
        """
        SELECT snapshot_date, entity, SUM(line_amount) AS ar_amount
        FROM ar_aging
        WHERE entity IS NOT NULL
        GROUP BY snapshot_date, entity
        ORDER BY snapshot_date, entity
        """
    )
    if df.empty:
        st.info("No AR rows with a resolved entity.")
        return
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    fig = trend_line(df, x_col="snapshot_date", y_col="ar_amount", series_col="entity")
    st.plotly_chart(fig, use_container_width=True)


def _section_monthly_billings():
    st.subheader("Monthly Billings by Entity")
    if not table_exists("ar_summary_monthly"):
        missing_source("the AR Summary export (monthly billed activity by client)")
        return
    df = query(
        """
        SELECT month_date, entity, SUM(amount) AS billed
        FROM ar_summary_monthly
        WHERE month_date <= date_trunc('month', CURRENT_DATE)
        GROUP BY month_date, entity
        ORDER BY month_date, entity
        """
    )
    if df.empty:
        st.info("No AR Summary data available.")
        return
    df["month"] = df["month_date"].map(_month_label)
    month_order = df.drop_duplicates("month").sort_values("month_date")["month"].tolist()
    fig = trend_line(df, x_col="month", y_col="billed", series_col="entity", show_values=True, x_order=month_order)
    st.plotly_chart(fig, use_container_width=True)
    n_months = df["month"].nunique()
    st.caption(
        f"{n_months} month(s) of billed activity from the AR Summary export -- distinct from "
        "AR balance (a point-in-time snapshot, the chart above) and from cash receipts (money "
        "actually collected, on the Weekly page). Months later than the current one read as $0 "
        "in the export and are excluded here rather than shown as a drop to zero."
    )


def _section_wip_aging_trend():
    st.subheader("WIP Aging Trend -- Avg. Days Outstanding")
    if not table_exists("wip_transactions"):
        missing_source("the WIP export")
        return
    df = query(
        """
        SELECT
            snapshot_date,
            SUM(billing_amount * DATE_DIFF('day', transaction_date, snapshot_date)) / NULLIF(SUM(billing_amount), 0) AS avg_days_outstanding
        FROM wip_transactions
        WHERE billing_status = 'B' AND billing_amount > 0
        GROUP BY snapshot_date
        ORDER BY snapshot_date
        """
    )
    if df.empty or df["avg_days_outstanding"].isna().all():
        st.info("Not enough billable WIP transactions to compute an aging proxy.")
        return
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    fig = trend_line(df, x_col="snapshot_date", y_col="avg_days_outstanding", y_is_currency=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Proxy metric: billing-value-weighted average of (snapshot date - transaction date) "
        "across billable WIP entries -- not a true open-WIP aging figure (that needs each "
        "matter's WIP balance open date, not in the current export). Treat as directional."
    )


def _section_revenue_by_matter_type():
    st.subheader("AR by Practice Group")
    if not (table_exists("ar_aging") and table_exists("matter_list")):
        missing_source("the AR aging export + the matter list export (for the practice-group taxonomy)")
        return
    df = query(
        """
        SELECT a.snapshot_date, COALESCE(m.organization_name, 'Unmapped') AS practice_group, SUM(a.line_amount) AS ar_amount
        FROM ar_aging a
        LEFT JOIN matter_list m ON a.matter_code = m.matter_code
        GROUP BY a.snapshot_date, practice_group
        ORDER BY a.snapshot_date, practice_group
        """
    )
    if df.empty:
        st.info("No AR data to break down by practice group.")
        return
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    fig = stacked_area_by_series(df, x_col="snapshot_date", y_col="ar_amount", series_col="practice_group")
    st.plotly_chart(fig, use_container_width=True)
    match = query(
        """
        SELECT
            COUNT(DISTINCT a.matter_code) AS total,
            COUNT(DISTINCT CASE WHEN m.matter_code IS NOT NULL THEN a.matter_code END) AS matched
        FROM ar_aging a
        LEFT JOIN matter_list m ON a.matter_code = m.matter_code
        """
    ).iloc[0]
    st.caption(
        f"Proxy: AR outstanding by practice group (matter_list.organization_name), not "
        f"recognized revenue -- the GL trial balance has no matter-level detail to break out "
        f"by practice group directly. {match['matched']}/{match['total']} matters "
        f"({match['matched'] / match['total'] * 100:.0f}%) matched to the matter list by matter "
        f"code; unmatched matters group as \"Unmapped\". One snapshot today -- fills into a real "
        f"trend as more AR aging snapshots accumulate."
    )


def _section_realization_trend():
    st.subheader("Realization Rate Trend")
    missing_source("the project earnings & labor export (billed amount distinct from worked-at-standard-rate)")
    st.caption(
        "Chart component is ready (dashboard/charts/trend_line.py) -- realization = billed / "
        "worked value by quarter, once the earnings export distinguishes the two."
    )


def _section_client_concentration():
    st.subheader("Client Concentration -- Top 10 Share of WIP")
    if not table_exists("wip_by_matter"):
        missing_source("the WIP export")
        return
    df = query(
        """
        WITH by_client AS (
            SELECT snapshot_date, client_name, SUM(wip_amount) AS client_wip
            FROM wip_by_matter
            GROUP BY snapshot_date, client_name
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY snapshot_date ORDER BY client_wip DESC) AS rnk
            FROM by_client
        )
        SELECT
            r.snapshot_date,
            SUM(CASE WHEN r.rnk <= 10 THEN r.client_wip ELSE 0 END) * 100.0 / NULLIF(SUM(r.client_wip), 0) AS top10_share_pct
        FROM ranked r
        GROUP BY r.snapshot_date
        ORDER BY r.snapshot_date
        """
    )
    if df.empty:
        st.info("No client-level WIP data available.")
        return
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    fig = trend_line(df, x_col="snapshot_date", y_col="top10_share_pct", y_is_currency=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Top-10 clients' share of total WIP value (proxy for revenue concentration -- "
        "recognized-revenue concentration needs the GL/earnings source)."
    )


def _section_variance_by_entity():
    st.subheader("Variance by Entity -- Current Year vs. Prior Year")
    n_years = (
        query("SELECT COUNT(DISTINCT EXTRACT(YEAR FROM snapshot_date)) AS n FROM ar_aging").iloc[0]["n"]
        if table_exists("ar_aging")
        else 0
    )
    if n_years < 2:
        missing_source(
            "a second fiscal year of warehouse history (only current-year snapshots are loaded)",
            remedy=(
                "Table component is ready (`dashboard/charts/variance_table.py::variance_table`) -- "
                "wire it up once prior-year snapshots are in the warehouse."
            ),
        )
        return
    df = query(
        """
        SELECT
            entity,
            SUM(CASE WHEN EXTRACT(YEAR FROM snapshot_date) = (SELECT MAX(EXTRACT(YEAR FROM snapshot_date)) FROM ar_aging) THEN line_amount ELSE 0 END) AS current_year,
            SUM(CASE WHEN EXTRACT(YEAR FROM snapshot_date) = (SELECT MAX(EXTRACT(YEAR FROM snapshot_date)) FROM ar_aging) - 1 THEN line_amount ELSE 0 END) AS prior_year
        FROM ar_aging
        WHERE entity IS NOT NULL
        GROUP BY entity
        """
    )
    variance_table(df, label_col="entity", current_col="current_year", prior_col="prior_year", label_header="Entity")
