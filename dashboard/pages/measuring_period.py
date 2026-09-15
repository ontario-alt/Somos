"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window:
FY revenue by entity, FY vs prior FY, originations pacing vs. target,
practice-group profitability.

FY revenue now uses real GL trial balance revenue by entity.
Practice-group profitability now uses real matter-level profit (the NTE
Tracking Report, etl/parse_matter_earnings.py) joined to the matter
list's practice-group taxonomy -- but that report only covers matters
with a not-to-exceed cap set (42 of ~315 matters), so this is real data
for a subset of the portfolio, not the whole thing; captioned as such.

The origination credit matrix (etl/parse_originations.py) gives real
originating-attorney credit fractions per matter, but dollarizing them
needs a revenue figure joined by matter -- checked both bridges
available: matching against AR by exact matter name (~16%) and against
matter_earnings via the matter list (~6%, since matter_earnings itself
only covers 42 matters) -- neither is reliable enough to trust, so this
page still shows credit-fraction totals, not a fabricated dollar chart.

FY-vs-prior-FY still needs a second fiscal year of history.
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

    _section_timekeeper_hours(fy_start, fy_end)
    st.divider()
    _section_fy_revenue(fy_start, fy_end)
    st.divider()
    _section_fy_vs_prior_fy()
    st.divider()
    _section_originations()
    st.divider()
    _section_practice_group_profitability()


def _section_timekeeper_hours(fy_start: datetime.date, fy_end: datetime.date):
    st.subheader("Timekeeper Hours by Entity (Hours-Required Individuals)")
    if not table_exists("timekeeper_hours"):
        missing_source("the All Timekeepers Hours export")
        return
    if not table_exists("employee_targets"):
        missing_source(
            "reference/employee_targets.csv",
            remedy="Generated automatically the first time build_warehouse.py runs with employee cost data loaded.",
        )
        return

    df = query(
        """
        SELECT h.entity, h.employee_name, t.target_type,
               h.billable_hours, h.credited_hours, h.total_hours, h.period_end
        FROM timekeeper_hours h
        JOIN employee_targets t ON h.employee_name = t.full_name
        WHERE t.target_type IS NOT NULL
        ORDER BY h.entity, h.employee_name
        """
    )
    if df.empty:
        st.info(
            "No hours-required individuals matched yet. This needs `reference/employee_targets.csv` "
            "to have `target_type` (\"LLC\"/\"LLP\") filled in for at least one employee whose name "
            "also appears in the All Timekeepers Hours export -- see the README's "
            "\"Billable-hour targets\" section."
        )
        return

    # period_end in the source is the *fixed* FY end date (e.g. 9/30/2026),
    # not when the export was actually pulled -- the file carries no pull
    # date of its own. Use the same "as of" reference the rest of the app
    # uses (the newest AR snapshot) so pace is measured against today, not
    # against a FY end date that would wrongly read as "100% elapsed".
    as_of = (
        query("SELECT MAX(as_of_date) AS v FROM ar_aging_detail").iloc[0]["v"]
        if table_exists("ar_aging_detail")
        else None
    )
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    pct_elapsed = max((min(as_of, pd.Timestamp(fy_end)) - pd.Timestamp(fy_start)).days / (fy_end - fy_start).days, 0.01)

    annual_target = df["target_type"].map(config.BILLABLE_HOUR_TARGETS)
    df["target_hours"] = (annual_target - df["credited_hours"]).clip(lower=0)
    df["projected_hours"] = df["billable_hours"] / pct_elapsed
    df["pace_pct"] = (df["projected_hours"] / df["target_hours"].replace(0, pd.NA) * 100).round(1)
    # When credited hours already cover most (or all) of the annual
    # target, the residual target left to bill is tiny -- pace vs. that
    # residual swings wildly and isn't a meaningful read on its own, so
    # flag it rather than let a triple-digit percentage look like a typo.
    thin_target = annual_target.notna() & (df["target_hours"] < annual_target * 0.15)

    st.caption(
        f"Measuring period through {as_of.date()} ({pct_elapsed * 100:.0f}% of the fiscal year "
        f"elapsed). Target hours = {', '.join(f'{k} {v:,}' for k, v in config.BILLABLE_HOUR_TARGETS.items())} "
        "annual, less each timekeeper's own actual credited hours from the export (not the flat "
        f"{config.BILLABLE_HOUR_CREDIT}-hour assumption used on the Monthly page -- real per-person "
        "credit is available here). Projected = hours to date ÷ % of FY elapsed, a straight-line "
        "pace estimate, not a forecast that accounts for seasonality. Re-upload this export any time "
        "(e.g. at month-end close) to refresh with the latest actuals."
    )
    if thin_target.any():
        st.caption(
            "⚠️ Timekeeper(s) marked * have credited hours covering 85%+ of their annual "
            "target already, leaving a small residual target to bill against -- their Pace vs. "
            "Target % swings widely on small changes and isn't a reliable read on its own."
        )
    df["employee_name"] = df["employee_name"] + thin_target.map({True: " *", False: ""})

    for entity, label in config.MATTER_CODE_ENTITY_PREFIXES.items():
        sub = df[df["entity"] == label]
        if sub.empty:
            continue
        st.markdown(f"**{label}**")
        out = sub.rename(
            columns={
                "employee_name": "Timekeeper", "billable_hours": "Billable Hours (to date)",
                "credited_hours": "Credited Hours", "target_hours": "Target Hours (FY)",
                "projected_hours": "Projected Hours (FY pace)", "pace_pct": "Pace vs. Target",
            }
        )[
            ["Timekeeper", "Billable Hours (to date)", "Credited Hours", "Target Hours (FY)",
             "Projected Hours (FY pace)", "Pace vs. Target"]
        ]
        st.dataframe(
            out,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Billable Hours (to date)": st.column_config.NumberColumn(format="%.1f"),
                "Credited Hours": st.column_config.NumberColumn(format="%.1f"),
                "Target Hours (FY)": st.column_config.NumberColumn(format="%.1f"),
                "Projected Hours (FY pace)": st.column_config.NumberColumn(format="%.1f"),
                "Pace vs. Target": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    unmatched = query(
        "SELECT COUNT(DISTINCT employee_name) AS n FROM timekeeper_hours h "
        "WHERE NOT EXISTS (SELECT 1 FROM employee_targets t WHERE t.full_name = h.employee_name)"
    ).iloc[0]["n"]
    if unmatched:
        st.caption(
            f"{unmatched} timekeeper(s) in the hours export didn't match a name in "
            "reference/employee_targets.csv and aren't shown here (either exempt, blank in that "
            "file, or a name-format mismatch worth checking)."
        )


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
    st.subheader("Practice Group Profitability")
    if not (table_exists("matter_earnings") and table_exists("matter_list")):
        missing_source("the NTE Tracking Report + matter list export (for the practice-group taxonomy)")
        return
    df = query(
        """
        SELECT
            COALESCE(m.organization_name, 'Unmapped') AS practice_group,
            COUNT(*) AS matters,
            SUM(e.jtd_revenue) AS revenue,
            SUM(e.jtd_profit) AS profit
        FROM matter_earnings e
        LEFT JOIN matter_list m ON e.matter_code = m.matter_code
        GROUP BY practice_group
        ORDER BY profit DESC
        """
    )
    if df.empty:
        st.info("No matter earnings data available.")
        return
    df["margin_pct"] = (df["profit"] / df["revenue"].replace(0, pd.NA)) * 100
    st.dataframe(
        df.rename(
            columns={
                "practice_group": "Practice Group", "matters": "Matters", "revenue": "JTD Revenue",
                "profit": "JTD Profit", "margin_pct": "Margin %",
            }
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            "JTD Revenue": st.column_config.NumberColumn(format="$%,.0f"),
            "JTD Profit": st.column_config.NumberColumn(format="$%,.0f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    match = query(
        """
        SELECT COUNT(*) AS total, COUNT(m.matter_code) AS matched
        FROM matter_earnings e LEFT JOIN matter_list m ON e.matter_code = m.matter_code
        """
    ).iloc[0]
    st.caption(
        f"Real JTD revenue/profit, but only for the {int(match['total'])} matters the NTE "
        f"Tracking Report covers (matters with a not-to-exceed cap set) -- not the full "
        f"~315-matter portfolio, so this is directional for those practice groups, not a "
        f"complete picture firm-wide. {match['matched']}/{match['total']} matched to a practice "
        f"group by matter code; unmatched group as \"Unmapped\"."
    )
