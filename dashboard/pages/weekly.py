"""
Weekly dashboard -- cash position, AR/AP aging, exceptions. Reuses the
chart components built for the monthly page. AP aging and week-over-week
trend/diffing are placeholders: AP aging has no sample export yet, and
trend/diff views need multiple weekly snapshots accumulated in the
warehouse over time (only one snapshot is loaded today).
"""
from __future__ import annotations

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
    if not table_exists("cash_receipts"):
        missing_source("Cash Position", "cash receipts")
        return
    collected = query("SELECT COALESCE(SUM(-amount), 0) AS v FROM cash_receipts").iloc[0]["v"]
    kpi_row(
        [
            {"label": "Cash collected (this period)", "value": fmt_currency(collected)},
            {"label": "Cash disbursed (this period)", "value": "--", "help": "Needs a cash disbursements export -- not available yet."},
            {"label": "Net cash flow", "value": "--", "help": "Needs disbursements to net against collections."},
        ]
    )
    st.caption(
        "Week-over-week trend line needs multiple weekly snapshots accumulated in the "
        "warehouse over time -- only one receipts snapshot is loaded currently."
    )


def _section_ar_aging():
    st.subheader("AR Aging")
    if not table_exists("ar_aging"):
        missing_source("AR Aging", "AR aging")
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
    missing_source("AP Aging", "AP aging")


def _section_exceptions():
    st.subheader("Exceptions")
    if not table_exists("ar_aging"):
        missing_source("Exceptions", "AR aging")
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
