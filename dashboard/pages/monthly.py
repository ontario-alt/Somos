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
from dashboard.charts.theme import entity_color_map, fmt_currency, fmt_pct, short_client_label
from dashboard.charts.treemap import wip_treemap
from dashboard.charts.trend_line import trend_line
from dashboard.data import query, table_exists

_ENTITY_ABBREV = {full: abbrev for abbrev, full in config.MATTER_CODE_ENTITY_PREFIXES.items()}
_ENTITY_COLORS = entity_color_map(config.MATTER_CODE_ENTITY_PREFIXES)


def _month_label(d) -> str:
    """2026-09-01 -> "Sep 2026" -- reads as a period, not a raw date, on
    every monthly-cadence chart/table on this page."""
    ts = pd.Timestamp(d)
    return ts.strftime("%b %Y")


def render():
    st.title("Monthly Report")

    if not table_exists("ar_aging_detail") and not table_exists("wip_by_matter"):
        st.warning("No AR or WIP data in the warehouse yet. Run `python etl/build_warehouse.py`.")
        return

    _section_kpis()
    st.divider()

    col1, col2 = st.columns([2, 3])
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
    # ar_aging_detail (the "All AR Report" / Somos AR Aging workbook
    # source), not ar_aging (a static invoice-level CSV that was never
    # refreshed): verified the two disagreed by ~$692K on the same date,
    # almost entirely ($647K) in the Over-120 bucket, and most of that gap
    # ($653K) matches client names now confirmed as GBNF -- old
    # collectibles the firm already tracks separately. ar_aging_detail is
    # the one that's actually current and already excludes them.
    has_ar = table_exists("ar_aging_detail")
    latest_ar = (
        query(
            """
            SELECT COALESCE(SUM(balance), 0) AS total, COALESCE(SUM(days_91_120 + over_120), 0) AS over_90
            FROM ar_aging_detail WHERE as_of_date = (SELECT MAX(as_of_date) FROM ar_aging_detail)
            """
        ).iloc[0]
        if has_ar
        else None
    )
    ar_total = latest_ar["total"] if has_ar else None
    over_90 = latest_ar["over_90"] if has_ar else None
    wip_total = query("SELECT COALESCE(SUM(wip_amount), 0) AS v FROM wip_by_matter").iloc[0]["v"] if table_exists("wip_by_matter") else None
    matter_count = query("SELECT COUNT(*) AS v FROM wip_by_matter").iloc[0]["v"] if table_exists("wip_by_matter") else None

    kpi_row(
        [
            {"label": "Total AR", "value": fmt_currency(ar_total) if ar_total is not None else "--"},
            {"label": "Total WIP", "value": fmt_currency(wip_total) if wip_total is not None else "--"},
            {"label": "AR 90+ days", "value": fmt_currency(over_90) if over_90 is not None else "--"},
            {"label": "Active matters (WIP)", "value": f"{matter_count:,.0f}" if matter_count is not None else "--"},
        ]
    )
    if has_ar and table_exists("gbnf_ar_aging"):
        gbnf_total = query("SELECT COALESCE(SUM(balance), 0) AS v FROM gbnf_ar_aging").iloc[0]["v"]
        st.caption(
            f"Total AR excludes {fmt_currency(gbnf_total)} in GBNF (Gone But Not Forgotten) "
            "collectibles, tracked separately -- see the Weekly page. GBNF is never counted "
            "toward the regular aging book's Over 120 / oldest totals."
        )


def _section_ar_by_entity():
    st.subheader("AR by Entity")
    # ar_aging_detail, not ar_aging -- see the "why is Total AR so high"
    # note on the KPI row above; this is the same actively-refreshed
    # source, and it excludes GBNF.
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
    df["month"] = df["as_of_date"].map(_month_label)
    # AR balance is a point-in-time stock, not a flow -- summing every
    # weekly snapshot that falls in the same month would inflate the
    # total several-fold. Keep only each month's latest snapshot.
    df = df.loc[df.groupby(["month", "entity"])["as_of_date"].idxmax()].reset_index(drop=True)
    month_order = list(dict.fromkeys(df.sort_values("as_of_date")["month"]))
    df["_rank"] = df["month"].map({m: i for i, m in enumerate(month_order)})
    df = df.sort_values(["_rank", "entity"]).drop(columns="_rank")

    fig = stacked_column_by_series(
        df, x_col="month", y_col="ar_amount", series_col="entity", title=None, show_values=True,
        color_map=_ENTITY_COLORS,
    )
    st.plotly_chart(fig, use_container_width=True)

    pivot = df.pivot_table(index="month", columns="entity", values="ar_amount", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(month_order)
    pivot["Total"] = pivot.sum(axis=1)
    st.dataframe(
        pivot.reset_index().rename(columns={"month": "Month"}),
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in pivot.columns},
    )
    st.caption(
        f"Each bar is that month's latest AR snapshot (not a sum of the month's snapshots -- "
        f"balance is a point-in-time figure, so summing several weekly snapshots in one month "
        f"would overstate it). {month_order[-1]} reflects the {pd.Timestamp(df['as_of_date'].max()).date()} snapshot; "
        "see the Weekly page for week-by-week movement within a month."
    )


def _section_top_matters():
    st.subheader("Top Matters")
    metric = st.radio("Rank by", ["WIP", "AR"], horizontal=True, key="top_matters_metric")
    if metric == "WIP":
        if not table_exists("wip_by_matter"):
            missing_source("the WIP export")
            return
        # Grouped by (company, client_name, matter_name), not matter_name
        # alone: several unrelated clients can share a generic matter name
        # like "General Real Estate" -- grouping by name only would sum
        # their unrelated WIP into one phantom bar.
        df = query(
            """
            SELECT company, client_name, matter_name, SUM(wip_amount) AS value
            FROM wip_by_matter GROUP BY company, client_name, matter_name
            """
        )
        df["entity"] = df["company"]
    else:
        if not table_exists("ar_aging"):
            missing_source("the AR aging export")
            return
        # Same risk here -- group by the real matter_code, not matter_name,
        # since matter_name alone collides across matter_codes (verified:
        # "General Real Estate" alone spans 11 distinct matter codes).
        df = query(
            """
            SELECT matter_code, matter_name, entity, SUM(line_amount) AS value
            FROM ar_aging WHERE entity IS NOT NULL GROUP BY matter_code, matter_name, entity
            """
        )
        df["client_name"] = None
    if df.empty:
        st.info("No matter data available.")
        return

    df["label"] = df.apply(
        lambda r: f"{r['matter_name']} — {short_client_label(None, r['client_name'])}"
        if r["client_name"]
        else str(r["matter_name"]),
        axis=1,
    )
    # matter_name (or matter_name + client) can still repeat if the same
    # matter appears more than once in the source -- disambiguate so
    # Plotly doesn't silently merge two different bars onto one row.
    dupe = df["label"].duplicated(keep=False)
    if dupe.any():
        df.loc[dupe, "label"] = df.loc[dupe, "label"] + df.loc[dupe].groupby("label").cumcount().add(1).astype(str).radd(" #")

    fig = ranked_bar(
        df, label_col="label", value_col="value", series_col="entity", color_map=_ENTITY_COLORS, top_n=10
    )
    st.plotly_chart(fig, use_container_width=True)


def _section_wip_treemap():
    st.subheader("WIP Composition by Matter")
    if not table_exists("wip_by_matter"):
        missing_source("the WIP export")
        return
    df = query(
        "SELECT company, client_name, matter_name, SUM(wip_amount) AS wip_amount FROM wip_by_matter GROUP BY company, client_name, matter_name"
    )
    df = df[df["wip_amount"] > 0]
    if df.empty:
        st.info("No positive WIP balances to chart.")
        return

    df["client_label"] = df.apply(
        lambda r: short_client_label(_ENTITY_ABBREV.get(r["company"], r["company"]), r["client_name"]), axis=1
    )
    df["matter_id"] = df["client_label"] + " > " + df["matter_name"].astype(str) + " #" + df.index.astype(str)

    clients = df.groupby("client_label", as_index=False)["wip_amount"].sum()
    clients["id"] = clients["client_label"]
    clients["parent"] = ""
    clients["label"] = clients["client_label"]

    matters = df.rename(columns={"matter_id": "id", "matter_name": "label", "client_label": "parent"})[
        ["id", "label", "parent", "wip_amount"]
    ]

    tree_df = pd.concat([clients[["id", "label", "parent", "wip_amount"]], matters], ignore_index=True)
    fig = wip_treemap(tree_df, label_col="label", value_col="wip_amount", parent_col="parent", id_col="id")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Grouped by client (entity: client, e.g. \"LLP: Fairplex\") -- click into a client's box "
        "to see its individual matters, each sized by its own WIP balance."
    )


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
    df["month"] = df["snapshot_date"].map(_month_label)
    month_order = df.drop_duplicates("month").sort_values("snapshot_date")["month"].tolist()
    fig = trend_line(df, x_col="month", y_col="revenue", series_col="entity", show_values=True, x_order=month_order)
    st.plotly_chart(fig, use_container_width=True)

    pivot = df.pivot_table(index="month", columns="entity", values="revenue", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(month_order)
    pivot["Total"] = pivot.sum(axis=1)
    st.dataframe(
        pivot.reset_index().rename(columns={"month": "Month"}),
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in pivot.columns},
    )
    n_months = df["month"].nunique()
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
    has_targets = has_cost and table_exists("employee_targets")

    cost_join = "LEFT JOIN employee_cost_rates c ON e.employee_name = c.wip_name" if has_cost else ""
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
    target_join = "LEFT JOIN employee_targets t ON c.employee_number = t.employee_number" if has_targets else ""
    target_select = "t.target_type," if has_targets else ""

    df = query(
        f"""
        WITH e AS (
            -- Grouped by employee only, not (employee, company): cost rates
            -- aren't genuinely entity-specific (verified against the sample --
            -- same employee, same rate in both entities' exports), so
            -- combining hours/billing across companies first means a salaried
            -- employee's monthly cost gets applied once, not once per entity
            -- they happened to log time against.
            SELECT
                employee_name,
                SUM(hours) AS hours,
                SUM(billing_amount) AS billing_amount,
                SUM(CASE WHEN billing_status = 'B' THEN hours ELSE 0 END) AS billable_hours
            FROM wip_transactions
            WHERE employee_name IS NOT NULL
            GROUP BY employee_name
        )
        SELECT
            e.employee_name,
            e.hours,
            e.billing_amount,
            e.billable_hours,
            {cost_select}
            {target_select}
        FROM e
        {cost_join}
        {target_join}
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

    if has_targets:
        span = query(
            "SELECT MIN(transaction_date) AS lo, MAX(transaction_date) AS hi FROM wip_transactions WHERE billing_status = 'B'"
        ).iloc[0]
        days_span = max((span["hi"] - span["lo"]).days + 1, 1) if span["lo"] is not None else 30
        credit = config.BILLABLE_HOUR_CREDIT if config.EMPLOYEE_TARGETS_CREDIT_REDUCES_TARGET else 0

        def _prorated_target(target_type):
            if not target_type or target_type not in config.BILLABLE_HOUR_TARGETS:
                return None
            annual = config.BILLABLE_HOUR_TARGETS[target_type] - credit
            return annual * (days_span / 365.0)

        target_hours = pd.to_numeric(df["target_type"].map(_prorated_target), errors="coerce")
        utilization_pct = (df["billable_hours"] / target_hours * 100).round(1)
        # Formatted as strings rather than left as a numeric column with
        # NumberColumn(format=...): when every row is NaN (no targets
        # assigned yet, the common case until reference/employee_targets.csv
        # is filled in), Streamlit's NumberColumn renders the literal text
        # "None" instead of a blank cell -- this sidesteps that entirely.
        df["target_hours"] = target_hours.map(lambda v: "--" if pd.isna(v) else f"{v:.1f}")
        df["utilization_pct"] = utilization_pct.map(lambda v: "--" if pd.isna(v) else f"{v:.1f}%")
        rename["target_hours"] = "Target Hours (period)"
        rename["utilization_pct"] = "Utilization %"

    df = df.rename(columns=rename)
    display_cols = ["Timekeeper", "Hours", "Billing Value"] + (["Cost", "Margin"] if has_cost else []) + ["Effective Rate ($/hr)"]
    if has_targets:
        display_cols += ["Target Hours (period)", "Utilization %"]
    st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            **{c: st.column_config.NumberColumn(format="$%,.0f") for c in money_cols},
            "Hours": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    captions = []
    if has_cost:
        n_unmatched = df["Cost"].isna().sum()
        total_billing, total_cost = df["Billing Value"].sum(), df["Cost"].sum(skipna=True)
        captions.append(
            "Cost/Margin from the Employee Cost Rate Details export: hourly staff cost "
            "hours x their rate, salaried staff cost their full monthly rate regardless of "
            "hours logged (that's how salary cost actually works, not an approximation) -- "
            "so a salaried timekeeper with little billable WIP this period still shows their "
            "full month's cost, and firm-wide cost can exceed billing value in a given month "
            f"({fmt_currency(total_cost)} cost vs. {fmt_currency(total_billing)} billing here) "
            "without that meaning the firm is unprofitable -- WIP only captures billable "
            "client work, not the rest of what salaried staff are paid for."
            + (f" {n_unmatched} timekeeper(s) didn't match a cost record (name format or not "
               "in the cost export) and show no cost/margin." if n_unmatched else "")
        )
    else:
        captions.append(
            "Cost/Margin need the Employee Cost Rate Details export -- not available yet."
        )
    if has_targets:
        n_no_target = (df["Target Hours (period)"] == "--").sum()
        captions.append(
            f"Utilization = billable hours (billing_status = 'B') / target hours, target hours "
            f"prorated to the {days_span}-day span of billable WIP currently loaded (annual "
            f"target x {days_span}/365) -- not a monthly or YTD figure yet, since the warehouse "
            f"only holds one WIP period today. Targets and who's exempt come from "
            f"reference/employee_targets.csv (edit that file directly, then re-run "
            f"build_warehouse.py). {n_no_target} timekeeper(s) shown have no target assigned in "
            f"that file (blank = intentionally exempt, e.g. executives/admin/consultants)."
        )
    else:
        captions.append(
            "Utilization needs reference/employee_targets.csv (a starter is generated "
            "automatically the first time build_warehouse.py runs with employee cost data "
            "loaded -- fill in each employee's target_type and re-run) plus a billed-vs-worked "
            "source for realization, which is still missing."
        )
    st.caption(" ".join(captions))


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
