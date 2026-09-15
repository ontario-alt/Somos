"""
Monthly dashboard -- the core report, rebuilding the existing WIP Report
model. Panels blocked on project earnings & labor (not yet available)
render a clearly-labeled placeholder instead of failing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.placeholder import missing_source
from dashboard.charts.ranked_bar import ranked_bar
from dashboard.charts.stacked_column import stacked_column_by_series
from dashboard.charts.theme import fmt_currency, fmt_pct
from dashboard.charts.treemap import wip_treemap
from dashboard.charts.trend_line import trend_line
from dashboard.data import query, table_exists


def render():
    st.title("Monthly Report")

    if not table_exists("ar_aging") and not table_exists("wip_by_matter"):
        st.warning("No AR or WIP data in the warehouse yet. Run `python etl/build_warehouse.py`.")
        return

    _section_kpis()
    st.divider()

    col1, col2 = st.columns([3, 2])
    with col1:
        _section_ar_by_entity()
    with col2:
        _section_top_matters()

    st.divider()
    _section_wip_treemap()

    st.divider()
    _section_billable_hours()

    st.divider()
    _section_revenue_by_month()

    st.divider()
    _section_pl_summary()

    st.divider()
    _section_timekeeper()

    st.divider()
    _section_exceptions()


def _section_kpis():
    ar_total = query("SELECT COALESCE(SUM(line_amount), 0) AS v FROM ar_aging").iloc[0]["v"] if table_exists("ar_aging") else None
    wip_total = query("SELECT COALESCE(SUM(wip_amount), 0) AS v FROM wip_by_matter").iloc[0]["v"] if table_exists("wip_by_matter") else None
    over_90 = (
        query(
            "SELECT COALESCE(SUM(days_91_120 + over_120), 0) AS v FROM ar_aging"
        ).iloc[0]["v"]
        if table_exists("ar_aging")
        else None
    )
    matter_count = query("SELECT COUNT(*) AS v FROM wip_by_matter").iloc[0]["v"] if table_exists("wip_by_matter") else None

    kpi_row(
        [
            {"label": "Total AR", "value": fmt_currency(ar_total) if ar_total is not None else "--"},
            {"label": "Total WIP", "value": fmt_currency(wip_total) if wip_total is not None else "--"},
            {"label": "AR 90+ days", "value": fmt_currency(over_90) if over_90 is not None else "--"},
            {"label": "Active matters (WIP)", "value": f"{matter_count:,.0f}" if matter_count is not None else "--"},
        ]
    )


def _section_ar_by_entity():
    st.subheader("AR by Entity")
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
    fig = stacked_column_by_series(
        df, x_col="snapshot_date", y_col="ar_amount", series_col="entity", title=None
    )
    st.plotly_chart(fig, use_container_width=True)
    ytd_total = df["ar_amount"].sum()
    st.caption(
        f"YTD total across shown snapshots: {fmt_currency(ytd_total)}. "
        "Currently one snapshot -- this chart accumulates a column per month "
        "as `build_warehouse.py` runs over time."
    )


def _section_top_matters():
    st.subheader("Top Matters")
    metric = st.radio("Rank by", ["WIP", "AR"], horizontal=True, key="top_matters_metric")
    if metric == "WIP":
        if not table_exists("wip_by_matter"):
            missing_source("the WIP export")
            return
        df = query(
            "SELECT matter_name, SUM(wip_amount) AS value FROM wip_by_matter GROUP BY matter_name"
        )
    else:
        if not table_exists("ar_aging"):
            missing_source("the AR aging export")
            return
        df = query(
            "SELECT matter_name, SUM(line_amount) AS value FROM ar_aging GROUP BY matter_name"
        )
    if df.empty:
        st.info("No matter data available.")
        return
    fig = ranked_bar(df, label_col="matter_name", value_col="value", top_n=10)
    st.plotly_chart(fig, use_container_width=True)


def _section_wip_treemap():
    st.subheader("WIP Composition by Matter")
    if not table_exists("wip_by_matter"):
        missing_source("the WIP export")
        return
    df = query(
        "SELECT client_name, matter_name, SUM(wip_amount) AS wip_amount FROM wip_by_matter GROUP BY client_name, matter_name"
    )
    df = df[df["wip_amount"] > 0]
    if df.empty:
        st.info("No positive WIP balances to chart.")
        return
    fig = wip_treemap(df, label_col="matter_name", value_col="wip_amount", parent_col=None)
    st.plotly_chart(fig, use_container_width=True)


def _section_billable_hours():
    st.subheader("Billable Hours -- Annualized Projection")
    if not table_exists("wip_transactions"):
        missing_source("the WIP export")
        return
    span = query(
        "SELECT MIN(transaction_date) AS lo, MAX(transaction_date) AS hi FROM wip_transactions WHERE billing_status = 'B'"
    )
    lo, hi = span.iloc[0]["lo"], span.iloc[0]["hi"]
    if lo is None or hi is None:
        st.info("No billable transactions available.")
        return
    days_span = max((hi - lo).days + 1, 1)
    df = query(
        """
        SELECT employee_name, SUM(hours) AS hours
        FROM wip_transactions
        WHERE billing_status = 'B' AND employee_name IS NOT NULL
        GROUP BY employee_name
        """
    )
    df["annualized_hours"] = df["hours"] * (365.0 / days_span)
    fig = ranked_bar(
        df, label_col="employee_name", value_col="annualized_hours", top_n=15, value_is_currency=False, title=None
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Projection = actual billable hours over the {days_span}-day span currently in the "
        "warehouse, annualized to 365 days. Accuracy improves as more monthly snapshots "
        "accumulate real YTD actuals rather than a single-period extrapolation."
    )


def _section_revenue_by_month():
    st.subheader("Revenue by Month by Entity")
    if not table_exists("gl_trial_balance"):
        missing_source("the GL trial balance export")
        return
    df = query(
        """
        SELECT
            snapshot_date, entity,
            -SUM(CASE WHEN account_type = 'Revenue' THEN closing_balance ELSE 0 END) AS revenue
        FROM gl_trial_balance
        GROUP BY snapshot_date, entity
        ORDER BY snapshot_date, entity
        """
    )
    if df.empty:
        st.info("No GL revenue data available.")
        return
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    fig = trend_line(df, x_col="snapshot_date", y_col="revenue", series_col="entity")
    st.plotly_chart(fig, use_container_width=True)
    n_months = df["snapshot_date"].nunique()
    st.caption(
        f"{n_months} trial-balance period(s) loaded, one point per period_end date. Drop "
        "multiple months of GL trial balances into data/raw/ (Vantagepoint runs these per "
        "entity, so one file per entity per month) and re-run `python etl/build_warehouse.py` "
        "to backfill a real month-over-month trend -- each file's own period is kept as its "
        "own snapshot rather than collapsing to one date."
    )


def _section_pl_summary():
    st.subheader("P&L Summary")
    if not table_exists("gl_trial_balance"):
        missing_source("the GL trial balance export")
        st.caption(
            "WIP gives billing value at standard rate, not actual cost, so margin can't be "
            "computed from what's currently in the warehouse."
        )
        return
    df = query(
        """
        SELECT
            entity,
            -SUM(CASE WHEN account_type = 'Revenue' THEN closing_balance ELSE 0 END) AS revenue,
            SUM(CASE WHEN account_type IN ('COGS', 'Expense') THEN closing_balance ELSE 0 END) AS cost
        FROM gl_trial_balance
        GROUP BY entity
        ORDER BY entity
        """
    )
    if df.empty:
        st.info("No GL data available.")
        return
    df["margin"] = df["revenue"] - df["cost"]
    df["margin_pct"] = (df["margin"] / df["revenue"].replace(0, pd.NA)) * 100

    kpi_row(
        [
            {"label": "Total Revenue", "value": fmt_currency(df["revenue"].sum())},
            {"label": "Total Cost", "value": fmt_currency(df["cost"].sum())},
            {
                "label": "Margin",
                "value": fmt_currency(df["margin"].sum()),
                "delta": fmt_pct(df["margin"].sum() / df["revenue"].sum() * 100) if df["revenue"].sum() else None,
            },
        ]
    )
    out = df.rename(
        columns={"entity": "Entity", "revenue": "Revenue", "cost": "Cost", "margin": "Margin", "margin_pct": "Margin %"}
    )
    st.dataframe(
        out,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Revenue": st.column_config.NumberColumn(format="$%,.0f"),
            "Cost": st.column_config.NumberColumn(format="$%,.0f"),
            "Margin": st.column_config.NumberColumn(format="$%,.0f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    period = query("SELECT MIN(period_start) AS lo, MAX(period_end) AS hi FROM gl_trial_balance").iloc[0]
    st.caption(f"GL period: {period['lo']} - {period['hi']}. Cost = COGS + Expense accounts (no separate COGS accounts seen in the sample chart of accounts).")


def _section_timekeeper():
    st.subheader("Timekeeper Activity")
    if not table_exists("wip_transactions"):
        missing_source("the WIP export")
        return

    has_cost = table_exists("employee_cost_rates")
    cost_join = (
        """
        LEFT JOIN employee_cost_rates c ON e.employee_name = c.wip_name
        """
        if has_cost
        else ""
    )
    cost_select = (
        """
            c.job_cost_type,
            CASE
                WHEN c.job_cost_type = 'Salary' THEN c.job_cost_rate
                WHEN c.job_cost_type = 'Hourly' THEN e.hours * c.job_cost_rate
                ELSE NULL
            END AS cost,
        """
        if has_cost
        else ""
    )
    df = query(
        f"""
        WITH e AS (
            -- Grouped by employee only, not (employee, company): cost rates
            -- aren't genuinely entity-specific (verified against the sample --
            -- same employee, same rate in both entities' exports), so
            -- combining hours/billing across companies first means a salaried
            -- employee's monthly cost gets applied once, not once per entity
            -- they happened to log time against.
            SELECT employee_name, SUM(hours) AS hours, SUM(billing_amount) AS billing_amount
            FROM wip_transactions
            WHERE employee_name IS NOT NULL
            GROUP BY employee_name
        )
        SELECT
            e.employee_name,
            e.hours,
            e.billing_amount,
            {cost_select}
        FROM e
        {cost_join}
        ORDER BY e.billing_amount DESC
        """
    )
    if df.empty:
        st.info("No timekeeper data available.")
        return
    df["effective_rate"] = (df["billing_amount"] / df["hours"]).round(2)

    rename = {
        "employee_name": "Timekeeper",
        "hours": "Hours",
        "billing_amount": "Billing Value",
        "effective_rate": "Effective Rate ($/hr)",
    }
    money_cols = ["Billing Value", "Effective Rate ($/hr)"]
    if has_cost:
        df["margin"] = df["billing_amount"] - df["cost"]
        rename["cost"] = "Cost"
        rename["margin"] = "Margin"
        money_cols += ["Cost", "Margin"]

    df = df.rename(columns=rename)
    display_cols = ["Timekeeper", "Hours", "Billing Value"] + (["Cost", "Margin"] if has_cost else []) + ["Effective Rate ($/hr)"]
    st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            **{c: st.column_config.NumberColumn(format="$%,.0f") for c in money_cols},
            "Hours": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if has_cost:
        n_unmatched = df["Cost"].isna().sum()
        total_billing, total_cost = df["Billing Value"].sum(), df["Cost"].sum(skipna=True)
        st.caption(
            "Cost/Margin from the Employee Cost Rate Details export: hourly staff cost "
            "hours x their rate, salaried staff cost their full monthly rate regardless of "
            "hours logged (that's how salary cost actually works, not an approximation) -- "
            "so a salaried timekeeper with little billable WIP this period still shows their "
            "full month's cost, and firm-wide cost can exceed billing value in a given month "
            f"({fmt_currency(total_cost)} cost vs. {fmt_currency(total_billing)} billing here) "
            "without that meaning the firm is unprofitable -- WIP only captures billable "
            "client work, not the rest of what salaried staff are paid for. "
            + (f"{n_unmatched} timekeeper(s) didn't match a cost record (name format or not "
               "in the cost export) and show no cost/margin. " if n_unmatched else "")
            + "Utilization and realization still need a capacity/target-hours figure and a "
            "billed-vs-worked source -- neither is available yet."
        )
    else:
        st.caption(
            "Utilization and realization require a timekeeper capacity/target-hours figure and "
            "a distinct billed-vs-worked source (the earnings export) -- neither is available yet. "
            "Cost/Margin need the Employee Cost Rate Details export -- also not available yet."
        )


def _section_exceptions():
    st.subheader("Exceptions & Action Items")
    if not table_exists("ar_aging"):
        missing_source("the AR aging export")
        return
    df = query(
        """
        SELECT matter_name, invoice_number, invoice_date, line_amount, ar_comment
        FROM ar_aging
        WHERE ar_comment IS NOT NULL AND ar_comment != ''
        ORDER BY invoice_date DESC
        """
    )
    if df.empty:
        st.info("No AR comments/flagged items in the current export.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
