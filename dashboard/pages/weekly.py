"""
Weekly dashboard -- cash position, AR/AP aging, exceptions. Reuses the
chart components built for the monthly page. Week-over-week trend/diff
views are still placeholders: they need multiple weekly snapshots
accumulated in the warehouse over time (only one snapshot is loaded
today).
"""
from __future__ import annotations

import datetime

import streamlit as st

import config
from dashboard.charts.aging_bar import aging_stacked_bar
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.placeholder import missing_source
from dashboard.charts.theme import fmt_currency
from dashboard.data import query, table_exists


def render():
    st.title("Weekly Report")
    st.caption("Cash position, AR/AP aging, and exceptions -- refreshed from the newest AR/AP/receipts exports.")

    _section_cash_position()
    st.divider()
    _section_ar_aging()
    st.divider()
    _section_ap_aging()
    st.divider()
    _section_exceptions()


def _section_cash_position():
    st.subheader("Cash Position")
    if not table_exists("cash_receipts") and not table_exists("cash_disbursements"):
        missing_source("the cash receipts / disbursements exports")
        return
    week_start = datetime.date.today() - datetime.timedelta(days=7)

    collected = (
        query("SELECT COALESCE(SUM(-amount), 0) AS v FROM cash_receipts WHERE receipt_date >= ?", [week_start]).iloc[0]["v"]
        if table_exists("cash_receipts")
        else None
    )
    disbursed = (
        query("SELECT COALESCE(SUM(amount), 0) AS v FROM cash_disbursements WHERE check_date >= ?", [week_start]).iloc[0]["v"]
        if table_exists("cash_disbursements")
        else None
    )
    net = (collected or 0) - (disbursed or 0) if collected is not None and disbursed is not None else None

    kpi_row(
        [
            {"label": "Cash collected (trailing 7 days)", "value": fmt_currency(collected) if collected is not None else "--"},
            {"label": "Cash disbursed (trailing 7 days)", "value": fmt_currency(disbursed) if disbursed is not None else "--"},
            {"label": "Net cash flow", "value": fmt_currency(net) if net is not None else "--"},
        ]
    )
    st.caption(
        f"Trailing 7 days from {week_start} (AP export's payment lines double as the "
        "disbursements source -- see etl/parse_ap.py). Week-over-week trend line needs "
        "multiple weekly snapshots accumulated in the warehouse over time -- only one "
        "snapshot of each source is loaded currently."
    )


def _section_ar_aging():
    st.subheader("AR Aging")
    if not table_exists("ar_aging"):
        missing_source("the AR aging export")
        return
    df = query(
        f"""
        SELECT 'Total' AS grp, {', '.join(f'SUM({b}) AS {b}' for b in config.AGING_BUCKETS)}
        FROM ar_aging
        """
    )
    fig = aging_stacked_bar(df, group_col="grp")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Newly flagged: crossing 90/120-day thresholds**")
    flagged = query(
        """
        SELECT matter_name, invoice_number, invoice_date, days_91_120, over_120
        FROM ar_aging
        WHERE days_91_120 > 0 OR over_120 > 0
        ORDER BY over_120 DESC, days_91_120 DESC
        """
    )
    if flagged.empty:
        st.info("Nothing currently in the 90+ day buckets.")
    else:
        st.dataframe(flagged, use_container_width=True, hide_index=True)
    st.caption(
        "'Newly crossing' (vs. already flagged last week) needs a prior-week snapshot to "
        "diff against -- shown here is everything currently in the 90+ buckets."
    )


def _section_ap_aging():
    st.subheader("AP Aging")
    if not table_exists("ap_aging"):
        missing_source("the AP export")
        return
    df = query(
        f"""
        SELECT 'Total' AS grp, {', '.join(f'SUM({b}) AS {b}' for b in config.AGING_BUCKETS)}
        FROM ap_aging
        """
    )
    fig = aging_stacked_bar(df, group_col="grp")
    st.plotly_chart(fig, use_container_width=True)

    detail = query(
        """
        SELECT vendor_name, invoice_number, invoice_date, entity, balance
        FROM ap_aging
        ORDER BY balance DESC
        """
    )
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config={"balance": st.column_config.NumberColumn("Balance", format="$%.2f")},
    )
    st.caption(
        "Open balance = net of each invoice's voucher and payment lines in the AP export "
        "(no separate 'paid' flag in the source -- see etl/parse_ap.py). Aging bucket is "
        "computed from invoice date to today, not carried from the source."
    )


def _section_exceptions():
    st.subheader("Exceptions")
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
        st.info("No open comments/action items in the current export.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        "A real resolved/open workflow needs somewhere to persist status across weeks -- "
        "this currently just surfaces AR comment text from the export as-is."
    )
