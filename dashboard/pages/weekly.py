"""
Weekly dashboard -- cash position, AR/AP aging, exceptions. Reuses the
chart components built for the monthly page.

The AR section is built to match the bookkeeping team's own weekly AR
report (Summary / Priority Board / Client Rollup, from a sample workbook
built off Vantagepoint's "All AR Report"): KPI row, aging by entity,
a configurable Red/Yellow/Green collections-priority tier
(config.AR_RED_THRESHOLD), top-10 client concentration, and a full
matter-level detail table. It reads ar_aging_detail (etl/parse_ar_detail.py,
parsed from the client-level "All AR Report" PDF), not the invoice-level
ar_aging table the rest of the app uses -- that one has no client field.

Week-over-week movement (the sample report's 4th tab) needs multiple
weekly ar_aging_detail snapshots accumulated over time -- only one is
loaded today, so it's not built yet; see the caption at the bottom of
the AR section for what unlocks it.
"""
from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

import config
from dashboard.charts.aging_bar import aging_stacked_bar
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.placeholder import missing_source
from dashboard.charts.theme import fmt_currency, fmt_pct
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


_PRIORITY_ORDER = {"Red": 0, "Yellow": 1, "Green": 2}


def _ar_detail_dates() -> list:
    """Every distinct "Aged as of" snapshot loaded, newest first. Plain
    date objects, not pandas Timestamps -- those print a "00:00:00"
    suffix wherever a date lands directly in a label."""
    df = query("SELECT DISTINCT as_of_date FROM ar_aging_detail ORDER BY as_of_date DESC")
    return [d.date() if hasattr(d, "date") else d for d in df["as_of_date"]]


def _ar_detail_df(as_of_date=None) -> pd.DataFrame:
    """Matter-level AR detail for one snapshot. Filters to a single
    as_of_date -- without this, loading multiple weekly snapshots (the
    whole point of accumulating history) would double-count every KPI
    and table on this page by summing across weeks instead of picking one."""
    threshold = config.AR_RED_THRESHOLD
    where = "WHERE as_of_date = ?" if as_of_date else "WHERE as_of_date = (SELECT MAX(as_of_date) FROM ar_aging_detail)"
    return query(
        f"""
        SELECT
            entity, client_name, matter_name, as_of_date,
            current_0_30, days_31_60, days_61_90, days_91_120, over_120, balance,
            (days_91_120 + over_120) AS over_90,
            (days_61_90 + days_91_120 + over_120) AS aged_60_plus,
            CASE
                WHEN over_120 > 0 THEN 'Over 120'
                WHEN days_91_120 > 0 THEN '91-120'
                WHEN days_61_90 > 0 THEN '61-90'
                WHEN days_31_60 > 0 THEN '31-60'
                ELSE 'Current'
            END AS oldest_bucket,
            CASE
                WHEN (days_91_120 + over_120) >= {threshold} THEN 'Red'
                WHEN (days_61_90 + days_91_120 + over_120) > 0 THEN 'Yellow'
                ELSE 'Green'
            END AS priority
        FROM ar_aging_detail
        {where}
        """,
        [as_of_date] if as_of_date else None,
    )


def _section_ar_aging():
    st.subheader("AR Aging")
    if not table_exists("ar_aging_detail"):
        missing_source(
            "the 'All AR Report' export (client-level, needed for the priority tiers and "
            "client rollup below -- see etl/parse_ar_detail.py)"
        )
        return
    dates = _ar_detail_dates()
    df = _ar_detail_df(dates[0] if dates else None)
    if df.empty:
        st.info("No AR detail rows available.")
        return
    as_of = df["as_of_date"].dropna().iloc[0] if df["as_of_date"].notna().any() else None
    as_of_display = as_of.date() if hasattr(as_of, "date") else as_of
    n_dates = len(dates)
    st.caption(
        f"Aged as of {as_of_display}"
        + (f" ({n_dates} snapshots loaded -- see Week over Week below)" if n_dates > 1 else "")
    )

    total = df["balance"].sum()
    current = df["current_0_30"].sum()
    over_90 = df["over_90"].sum()
    red = df[df["priority"] == "Red"]
    kpi_row(
        [
            {"label": "Total AR Outstanding", "value": fmt_currency(total, short=True), "help": fmt_currency(total)},
            {"label": "Current (0-30 days)", "value": fmt_currency(current, short=True), "help": fmt_currency(current)},
            {"label": "Over 90 Days", "value": fmt_currency(over_90, short=True), "help": fmt_currency(over_90)},
            {"label": "% Over 90 Days", "value": fmt_pct(over_90 / total * 100 if total else 0)},
            {"label": "Red Balance", "value": fmt_currency(red["balance"].sum(), short=True), "help": fmt_currency(red["balance"].sum())},
            {"label": "Matters in Red", "value": f"{len(red)}"},
        ]
    )

    bucket_totals = df[["current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120"]].sum().to_frame().T
    bucket_totals.insert(0, "grp", "Total")
    st.plotly_chart(aging_stacked_bar(bucket_totals, group_col="grp"), use_container_width=True)

    st.markdown("**Aging by Entity**")
    by_entity = (
        df.groupby("entity")
        .agg(
            current_0_30=("current_0_30", "sum"),
            days_31_60=("days_31_60", "sum"),
            days_61_90=("days_61_90", "sum"),
            days_91_120=("days_91_120", "sum"),
            over_120=("over_120", "sum"),
            balance=("balance", "sum"),
            over_90=("over_90", "sum"),
            matters=("matter_name", "count"),
        )
        .reset_index()
    )
    by_entity["pct_of_total"] = by_entity["balance"] / total * 100 if total else 0
    by_entity["pct_over_90"] = (by_entity["over_90"] / by_entity["balance"].replace(0, pd.NA)) * 100
    total_row = pd.DataFrame(
        [
            {
                "entity": "TOTAL -- ALL ENTITIES",
                **{c: by_entity[c].sum() for c in ["current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120", "balance", "over_90", "matters"]},
                "pct_of_total": 100.0,
                "pct_over_90": over_90 / total * 100 if total else 0,
            }
        ]
    )
    by_entity = pd.concat([by_entity, total_row], ignore_index=True)
    st.dataframe(
        by_entity.rename(
            columns={
                "entity": "Entity", "current_0_30": "Current", "days_31_60": "31-60", "days_61_90": "61-90",
                "days_91_120": "91-120", "over_120": "Over 120", "balance": "Balance", "over_90": "Over 90 Days",
                "matters": "Matters", "pct_of_total": "% of Total", "pct_over_90": "% Over 90",
            }
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            c: st.column_config.NumberColumn(format="$%,.0f")
            for c in ["Current", "31-60", "61-90", "91-120", "Over 120", "Balance", "Over 90 Days"]
        }
        | {"% of Total": st.column_config.NumberColumn(format="%.1f%%"), "% Over 90": st.column_config.NumberColumn(format="%.1f%%")},
    )

    st.markdown(f"**Priority** &nbsp;&mdash;&nbsp; Red threshold: over-90 balance ≥ {fmt_currency(config.AR_RED_THRESHOLD)}")
    by_priority = (
        df.groupby("priority")
        .agg(matters=("matter_name", "count"), balance=("balance", "sum"), over_90=("over_90", "sum"))
        .reindex(["Red", "Yellow", "Green"])
        .reset_index()
    )
    by_priority["pct_of_total"] = by_priority["balance"] / total * 100 if total else 0
    st.dataframe(
        by_priority.rename(
            columns={"priority": "Priority", "matters": "Matters", "balance": "Balance", "over_90": "Over 90 Days", "pct_of_total": "% of Total AR"}
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Balance": st.column_config.NumberColumn(format="$%,.0f"),
            "Over 90 Days": st.column_config.NumberColumn(format="$%,.0f"),
            "% of Total AR": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "Red = an over-90 balance at or above the threshold (principal outreach this week; "
        "escalate to demand letter or stop-work review). Yellow = aged past 60 days, below "
        "the threshold (follow up before it crosses 90). Green = nothing aged past 60 days. "
        "Change the threshold in `config.AR_RED_THRESHOLD` and every table on this page "
        "recalculates."
    )

    st.markdown("**Concentration -- Ten Largest Client Balances**")
    entity_abbrev = {v: k for k, v in config.MATTER_CODE_ENTITY_PREFIXES.items()}
    priority_rank = df["priority"].map(_PRIORITY_ORDER)
    df_ranked = df.assign(_rank=priority_rank)
    by_client = (
        df_ranked.groupby("client_name")
        .agg(
            matters=("matter_name", "count"),
            balance=("balance", "sum"),
            over_90=("over_90", "sum"),
            _rank=("_rank", "min"),
            entity=("entity", lambda s: " / ".join(sorted({entity_abbrev.get(e, e) for e in s}))),
        )
        .reset_index()
        .sort_values("balance", ascending=False)
    )
    by_client["priority"] = by_client["_rank"].map({v: k for k, v in _PRIORITY_ORDER.items()})
    by_client["pct_of_total"] = by_client["balance"] / total * 100 if total else 0
    top10 = by_client.head(10).drop(columns="_rank")
    st.dataframe(
        top10.rename(
            columns={
                "client_name": "Client", "entity": "Entity", "matters": "Matters", "balance": "AR Balance",
                "over_90": "Over 90 Days", "pct_of_total": "% of Total AR", "priority": "Priority",
            }
        )[["Client", "Entity", "Matters", "AR Balance", "Over 90 Days", "% of Total AR", "Priority"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "AR Balance": st.column_config.NumberColumn(format="$%,.0f"),
            "Over 90 Days": st.column_config.NumberColumn(format="$%,.0f"),
            "% of Total AR": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        f"{by_client.shape[0]} client relationships across {len(df)} matters. Client priority "
        "reflects the highest tier held by any of that client's matters; Entity concatenates "
        "every entity that client has matters under (e.g. \"LLC / LLP\")."
    )

    with st.expander(f"Matter-level detail ({len(df)} matters, sorted by priority then balance)"):
        detail = df.assign(_rank=df["priority"].map(_PRIORITY_ORDER)).sort_values(["_rank", "balance"], ascending=[True, False])
        low_confidence = query(
            "SELECT COUNT(*) AS n FROM ar_aging_detail WHERE as_of_date = ? AND client_name_confidence != 'ok'",
            [as_of],
        ).iloc[0]["n"]
        if low_confidence:
            st.caption(
                f"⚠️ {low_confidence} row(s) show the same value for client and matter -- "
                "the source PDF's line-wrap dropped the client segment for these. A CSV/Excel "
                "export of the same report (if Vantagepoint supports it) would avoid this."
            )
        st.dataframe(
            detail[
                ["entity", "client_name", "matter_name", "current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120", "balance", "over_90", "aged_60_plus", "oldest_bucket", "priority"]
            ].rename(
                columns={
                    "entity": "Entity", "client_name": "Client", "matter_name": "Matter", "current_0_30": "Current",
                    "days_31_60": "31-60", "days_61_90": "61-90", "days_91_120": "91-120", "over_120": "Over 120",
                    "balance": "Balance", "over_90": "Over 90 Days", "aged_60_plus": "Aged 60+", "oldest_bucket": "Oldest Bucket", "priority": "Priority",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                c: st.column_config.NumberColumn(format="$%,.0f")
                for c in ["Current", "31-60", "61-90", "91-120", "Over 120", "Balance", "Over 90 Days", "Aged 60+"]
            },
        )

    st.markdown("**Week over Week**")
    if len(dates) < 2:
        st.info(
            f"Only {len(dates)} snapshot loaded -- needs a second week's \"All AR Report\" to "
            "compare against. Run `python etl/build_warehouse.py` against each week's export as "
            "it comes in (or drop several past weeks in at once) and this fills in."
        )
    else:
        _section_week_over_week(dates[0], dates[1])


def _section_week_over_week(current_date, prior_date):
    current = _ar_detail_df(current_date)
    prior = _ar_detail_df(prior_date)

    cur_total, prior_total = current["balance"].sum(), prior["balance"].sum()
    cur_over90, prior_over90 = current["over_90"].sum(), prior["over_90"].sum()
    cur_red, prior_red = (current["priority"] == "Red").sum(), (prior["priority"] == "Red").sum()

    kpi_row(
        [
            {"label": f"Total AR -- {prior_date}", "value": fmt_currency(prior_total, short=True), "help": fmt_currency(prior_total)},
            {"label": f"Total AR -- {current_date}", "value": fmt_currency(cur_total, short=True), "help": fmt_currency(cur_total)},
            {
                "label": "Change",
                "value": fmt_currency(cur_total - prior_total, short=True),
                "delta": fmt_pct((cur_total - prior_total) / prior_total * 100) if prior_total else None,
            },
            {"label": "Over 90 -- Change", "value": fmt_currency(cur_over90 - prior_over90, short=True)},
            {"label": "Red Matters", "value": f"{prior_red} → {cur_red}"},
        ]
    )

    st.markdown("**Bucket Movement**")
    buckets = ["current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120"]
    bucket_labels = {"current_0_30": "Current", "days_31_60": "31-60", "days_61_90": "61-90", "days_91_120": "91-120", "over_120": "Over 120"}
    move = pd.DataFrame(
        [
            {
                "Bucket": bucket_labels[b],
                str(prior_date): prior[b].sum(),
                str(current_date): current[b].sum(),
            }
            for b in buckets
        ]
    )
    move["Change"] = move[str(current_date)] - move[str(prior_date)]
    st.dataframe(
        move,
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in [str(prior_date), str(current_date), "Change"]},
    )

    st.markdown("**Priority Movement**")
    def _priority_snapshot(d: pd.DataFrame) -> pd.DataFrame:
        return d.groupby("priority").agg(matters=("matter_name", "count"), balance=("balance", "sum")).reindex(["Red", "Yellow", "Green"]).fillna(0)

    p_prior, p_cur = _priority_snapshot(prior), _priority_snapshot(current)
    pm = pd.DataFrame(
        {
            f"Matters {prior_date}": p_prior["matters"],
            f"Matters {current_date}": p_cur["matters"],
            f"Balance {prior_date}": p_prior["balance"],
            f"Balance {current_date}": p_cur["balance"],
        }
    ).reset_index().rename(columns={"priority": "Priority"})
    st.dataframe(
        pm,
        use_container_width=True,
        hide_index=True,
        column_config={
            c: st.column_config.NumberColumn(format="$%,.0f") for c in pm.columns if c.startswith("Balance")
        },
    )
    st.caption(
        f"Comparing {current_date} against the prior snapshot ({prior_date}). Matter-level "
        "movement (new/cleared matters, which specific matters changed priority) isn't broken "
        "out yet -- ask if you want that added; the bucket and priority totals above are "
        "already real."
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
        column_config={"balance": st.column_config.NumberColumn("Balance", format="$%,.2f")},
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
