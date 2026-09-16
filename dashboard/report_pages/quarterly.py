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
        query("SELECT COUNT(DISTINCT as_of_date) AS n FROM ar_aging_detail").iloc[0]["n"]
        if table_exists("ar_aging_detail")
        else 0
    )
    st.caption(
        f"{n_snapshots} AR snapshot(s) in the warehouse. Trend panels below render one point per "
        "snapshot -- run `python etl/build_warehouse.py` as new exports arrive to build up real "
        "trend lines."
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
    # ar_aging_detail, not ar_aging: it's the source that's actually
    # accumulating multiple real dates (ar_aging only ever holds the
    # single newest snapshot -- see build_warehouse.py's docstring on
    # "batch daily/weekly, one date per run" sources).
    if not table_exists("ar_aging_detail"):
        missing_source("the 'All AR Report' or Somos AR Aging workbook export")
        return
    df = query(
        """
        SELECT as_of_date, entity, SUM(balance) AS ar_amount
        FROM ar_aging_detail
        WHERE entity IS NOT NULL
        GROUP BY as_of_date, entity
        ORDER BY as_of_date, entity
        """
    )
    if df.empty:
        st.info("No AR rows with a resolved entity.")
        return
    df["as_of_date"] = df["as_of_date"].astype(str)
    fig = trend_line(df, x_col="as_of_date", y_col="ar_amount", series_col="entity", show_values=True)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Total outstanding balance -- useful for spotting a growing or shrinking pile, but a "
        "flat or rising line here can just mean old, aged receivables sitting unchanged rather "
        "than new activity. See the aging composition trend below for whether the mix is "
        "actually getting older or younger."
    )

    st.markdown("**AR Aging Composition Trend**")
    bucket_cols = ["current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120"]
    bucket_labels = {
        "current_0_30": "Current (0-30)", "days_31_60": "31-60 days", "days_61_90": "61-90 days",
        "days_91_120": "91-120 days", "over_120": "Over 120 days",
    }
    comp = query(
        f"""
        SELECT as_of_date, {', '.join(f'SUM({c}) AS {c}' for c in bucket_cols)}
        FROM ar_aging_detail
        GROUP BY as_of_date
        ORDER BY as_of_date
        """
    )
    if len(comp) < 2:
        st.caption(
            "Needs at least two AR aging snapshots to show a composition trend -- only one is "
            "loaded today."
        )
    else:
        comp["total"] = comp[bucket_cols].sum(axis=1)
        long = comp.melt(id_vars=["as_of_date", "total"], value_vars=bucket_cols, var_name="bucket", value_name="amount")
        long["pct"] = (long["amount"] / long["total"].replace(0, pd.NA) * 100).round(1)
        long["bucket_label"] = long["bucket"].map(bucket_labels)
        long["as_of_date"] = long["as_of_date"].astype(str)
        # Old-to-new order so "Current" lands on top of the stack, reading
        # top-down the same way the aging buckets read left-to-right elsewhere.
        long["bucket_label"] = pd.Categorical(long["bucket_label"], categories=list(reversed(bucket_labels.values())), ordered=True)
        long = long.sort_values(["bucket_label", "as_of_date"])
        fig2 = stacked_area_by_series(long, x_col="as_of_date", y_col="pct", series_col="bucket_label", y_is_currency=False)
        fig2.update_yaxes(ticksuffix="%", range=[0, 100])
        st.plotly_chart(fig2, use_container_width=True)
        current_share_trend = comp.set_index("as_of_date")["current_0_30"] / comp.set_index("as_of_date")["total"] * 100
        delta = current_share_trend.iloc[-1] - current_share_trend.iloc[0]
        direction = "improved (more current)" if delta > 0 else "worsened (more aged)" if delta < 0 else "held steady"
        st.caption(
            f"Share of total AR in each aging bucket, by snapshot -- the actionable read on "
            f"whether collections are keeping pace, independent of whether the total balance "
            f"itself is growing. Current (0-30 days) share has {direction} "
            f"({current_share_trend.iloc[0]:.0f}% → {current_share_trend.iloc[-1]:.0f}%) "
            f"across the {len(comp)} snapshots loaded."
        )


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
    n_years = (
        query("SELECT COUNT(DISTINCT EXTRACT(YEAR FROM as_of_date)) AS n FROM ar_aging_detail").iloc[0]["n"]
        if table_exists("ar_aging_detail")
        else 0
    )
    if n_years < 2:
        # Minimized rather than a full-width placeholder block: there's
        # nothing actionable here until a prior fiscal year is loaded, so
        # it shouldn't compete for attention with the panels above that
        # already have real data. Collapsed by default -- opening it just
        # explains what's blocking it, not a chart.
        with st.expander("Variance by Entity -- Current Year vs. Prior Year (needs prior-year data)"):
            st.caption(
                "Not available yet -- only one fiscal year of AR snapshots is loaded. Drop last "
                "fiscal year's archived AR exports into `data/raw/` and re-run "
                "`python etl/build_warehouse.py` to unlock this. Table component is ready "
                "(`dashboard/charts/variance_table.py::variance_table`)."
            )
        return
    st.subheader("Variance by Entity -- Current Year vs. Prior Year")
    df = query(
        """
        SELECT
            entity,
            SUM(CASE WHEN EXTRACT(YEAR FROM as_of_date) = (SELECT MAX(EXTRACT(YEAR FROM as_of_date)) FROM ar_aging_detail) THEN balance ELSE 0 END) AS current_year,
            SUM(CASE WHEN EXTRACT(YEAR FROM as_of_date) = (SELECT MAX(EXTRACT(YEAR FROM as_of_date)) FROM ar_aging_detail) - 1 THEN balance ELSE 0 END) AS prior_year
        FROM ar_aging_detail
        WHERE entity IS NOT NULL
        GROUP BY entity
        """
    )
    variance_table(df, label_col="entity", current_col="current_year", prior_col="prior_year", label_header="Entity")
