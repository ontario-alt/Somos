"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window
the firm measures hours and profitability on:

  * Hours vs. Measuring Period Requirements -- the firm's Promotion and
    Bonus Policy, per person: Hours Expectation (client + FOA + pro bono +
    creditable non-billable capped at 75; 1900 / 1600), Total Activity
    (2200 / 1800), Bonus Threshold (no pro bono; 1850 / 1550) and the
    2-year promotion lookback, all prorated for leave and partial-year
    employment. Math lives in dashboard/hours_credit.py; a downloadable
    leadership snapshot in dashboard/leadership_report.py.
  * Timekeeper Profitability -- revenue vs. direct labor cost per person
    and per role, from the labor detail export + employee cost rates.
  * FY revenue by entity (GL), FY vs prior FY, originations, and
    practice-group profitability (full portfolio from labor detail when
    loaded; the NTE Tracking Report's JTD view as a supplement).

Hours sources, best first, for whichever measuring period is selected:
the transaction-level labor detail export (classifies every entry by
policy category, monthly pace, dollars); the firm's Monthly Hours Report
by Timekeeper workbook (backfills closed periods); the "All Timekeepers
Hours" summary. The latter two lump pro bono into "credited", which the
page flags.

The origination credit matrix (etl/parse_originations.py) gives real
originating-attorney credit fractions per matter, but dollarizing them
needs a revenue figure joined by matter -- checked both bridges
available: matching against AR by exact matter name (~16%) and against
matter_earnings via the matter list (~6%) -- neither is reliable enough
to trust, so this page still shows credit-fraction totals, not a
fabricated dollar chart.

FY-vs-prior-FY still needs a second fiscal year of history.
"""
from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

import config
from dashboard import hours_credit, leadership_report
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.placeholder import missing_source
from dashboard.charts.ranked_bar import ranked_bar
from dashboard.charts.target_progress import cumulative_vs_target, target_progress
from dashboard.charts.theme import fmt_currency
from dashboard.charts.trend_line import trend_line
from dashboard.data import query, table_exists
from etl.common import name_key


def render():
    st.title("Measuring Period (FY 10/1-9/30)")

    as_of = st.date_input(
        "Hours through",
        value=_default_as_of(),
        format="MM/DD/YYYY",
        help=(
            "The date hours are counted through. Defaults to the latest work date in the labor "
            "detail export (or today, capped at the hours export's period end). The measuring "
            "period shown is the fiscal year containing this date -- pick 9/30 of a prior year "
            "to review a closed period."
        ),
    )
    fy_start, fy_end = config.fiscal_year_bounds(as_of)
    st.caption(f"Measuring period: {fy_start:%b %d, %Y} - {fy_end:%b %d, %Y}, hours through {as_of:%b %d, %Y}")

    _section_timekeeper_hours(fy_start, fy_end, as_of)
    st.divider()
    _section_timekeeper_profitability(fy_start, fy_end, as_of)
    st.divider()
    _section_fy_revenue(fy_start, fy_end)
    st.divider()
    _section_fy_vs_prior_fy()
    st.divider()
    _section_originations()
    st.divider()
    _section_practice_group_profitability(fy_start, as_of)


# ---------------------------------------------------------------------------
# Shared loaders
# ---------------------------------------------------------------------------
def _default_as_of() -> datetime.date:
    """Latest date any hours source covers (so a just-closed period opens
    by default), capped at today."""
    today = datetime.date.today()
    candidates = []
    if table_exists("labor_detail"):
        candidates.append(query("SELECT MAX(transaction_date) AS v FROM labor_detail").iloc[0]["v"])
    if table_exists("monthly_hours"):
        v = query("SELECT MAX(month) AS v FROM monthly_hours").iloc[0]["v"]
        candidates.append(None if v is None or pd.isna(v) else pd.Timestamp(v) + pd.offsets.MonthEnd(0))
    if table_exists("timekeeper_hours"):
        candidates.append(query("SELECT MAX(period_end) AS v FROM timekeeper_hours").iloc[0]["v"])
    dates = [pd.Timestamp(v).date() for v in candidates if v is not None and not pd.isna(v)]
    return min(max(dates), today) if dates else today


_PEOPLE_COLS = [
    "full_name", "name_key", "employee_number", "role", "start_date", "end_date",
    "billable_target", "credit_cap", "total_target", "bonus_threshold",
]


def _load_people(fy_start=None, source: str | None = None) -> pd.DataFrame | None:
    """Timekeepers and their targets: reference/employee_targets.csv (role,
    start/end dates, individual-terms overrides), plus -- when the period's
    hours come from the firm's monthly hours workbook -- the requirements
    recorded in that workbook for that period. Explicit overrides in
    employee_targets.csv win, then the workbook's figures, then role defaults."""
    people = None
    if table_exists("employee_targets"):
        cols = set(query("SELECT * FROM employee_targets LIMIT 0").columns)
        if "name_key" not in cols or "bonus_threshold" not in cols:
            st.warning(
                "The warehouse's employee_targets table is from an older version -- click "
                "**Refresh data** (or run `python etl/build_warehouse.py`) to rebuild it."
            )
            return None
        # No genuine per-row snapshot -- pinned to the latest snapshot_date so
        # a leftover older snapshot can't fan out a join.
        people = query(
            """
            SELECT full_name, name_key, employee_number, target_type AS role, start_date, end_date,
                   billable_target, credit_cap, total_target, bonus_threshold
            FROM employee_targets
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM employee_targets)
            """
        )
        people["role"] = people["role"].map(config.resolve_role)

    if source == "monthly_hours":
        fy_end = config.fiscal_year_bounds(pd.Timestamp(fy_start).date())[1]
        wb = query(
            """
            SELECT name_key, ANY_VALUE(employee_name) AS full_name,
                   MAX(billable_requirement) AS wb_billable, MAX(credit_cap) AS wb_cap,
                   MAX(total_requirement) AS wb_total
            FROM monthly_hours WHERE month BETWEEN ? AND ?
            GROUP BY name_key
            """,
            [fy_start, fy_end],
        )
        if people is None:
            people = pd.DataFrame(columns=_PEOPLE_COLS)
        people = people.merge(wb, on="name_key", how="outer", suffixes=("", "_wb"))
        people["full_name"] = people["full_name"].fillna(people.pop("full_name_wb"))
        for col, wb_col in (("billable_target", "wb_billable"), ("credit_cap", "wb_cap"), ("total_target", "wb_total")):
            people[col] = pd.to_numeric(people[col], errors="coerce").fillna(people.pop(wb_col))
        # Role from the requirement when the targets file doesn't say:
        # 1,900 -> Attorney, 1,600 -> Planner, anything else = individual terms.
        by_target = {v: k for k, v in config.BILLABLE_HOUR_TARGETS.items()}
        people["role"] = people["role"].fillna(people["billable_target"].map(by_target))
    return people


def _load_leave() -> pd.DataFrame:
    if not table_exists("employee_leave"):
        return pd.DataFrame(columns=["name_key", "employee_number", "leave_start", "leave_end", "percent_away", "leave_type", "full_name"])
    return query("SELECT name_key, employee_number, leave_start, leave_end, percent_away, leave_type, full_name FROM employee_leave")


def _has_rows(table: str, date_col: str, lo, hi) -> bool:
    return table_exists(table) and query(
        f"SELECT COUNT(*) AS n FROM {table} WHERE {date_col} BETWEEN ? AND ?", [lo, hi]
    ).iloc[0]["n"] > 0


def _hours_source(fy_start, as_of) -> str:
    """Best source covering this measuring period: labor detail, then the
    firm's monthly hours workbook, then the All Timekeepers Hours summary."""
    if _has_rows("labor_detail", "transaction_date", fy_start, as_of):
        return "labor_detail"
    if _has_rows("monthly_hours", "month", fy_start, as_of):
        return "monthly_hours"
    if table_exists("timekeeper_hours") and query(
        "SELECT COUNT(*) AS n FROM timekeeper_hours WHERE period_start = ?", [fy_start]
    ).iloc[0]["n"] > 0:
        return "timekeeper_hours"
    return "none"


# Hours by policy category (see config.py). The labor detail export is
# classified per entry; the firm's workbook and the All Timekeepers
# Hours summary only have billable / credited / not-credited buckets, so
# their "credited" bucket is treated as creditable non-billable (capped)
# -- see the caveat shown on the page for those sources.
_LABOR_CATEGORY_SQL = """
    SUM(CASE WHEN hours_category = 'client' THEN hours ELSE 0 END) AS client_hours,
    SUM(CASE WHEN hours_category = 'foa' THEN hours ELSE 0 END) AS foa_hours,
    SUM(CASE WHEN hours_category = 'pro_bono' THEN hours ELSE 0 END) AS pro_bono_hours,
    SUM(CASE WHEN hours_category = 'creditable' THEN hours ELSE 0 END) AS creditable_hours,
    SUM(CASE WHEN hours_category = 'other' THEN hours ELSE 0 END) AS other_hours,
    SUM(CASE WHEN hours_category = 'time_off' THEN hours ELSE 0 END) AS time_off_hours
"""
_WORKBOOK_CATEGORY_SQL = """
    SUM(billable_to_clients) AS client_hours, 0.0 AS foa_hours, 0.0 AS pro_bono_hours,
    SUM(nb_credited) AS creditable_hours, SUM(nb_not_credited) AS other_hours, 0.0 AS time_off_hours
"""


def _load_hours(fy_start, as_of, source: str) -> pd.DataFrame:
    """Per-person hours to date by policy category (hours_credit.HOURS_COLS), plus entities."""
    if source == "labor_detail":
        return query(
            f"""
            SELECT name_key, ANY_VALUE(employee_name) AS employee_name, {_LABOR_CATEGORY_SQL},
                   STRING_AGG(DISTINCT entity, ', ' ORDER BY entity) AS entities
            FROM labor_detail
            WHERE transaction_date BETWEEN ? AND ?
            GROUP BY name_key
            """,
            [fy_start, as_of],
        )
    if source == "monthly_hours":
        return query(
            f"""
            SELECT name_key, ANY_VALUE(employee_name) AS employee_name, {_WORKBOOK_CATEGORY_SQL},
                   '' AS entities
            FROM monthly_hours WHERE month BETWEEN ? AND ?
            GROUP BY name_key
            """,
            [fy_start, as_of],
        )
    if source == "timekeeper_hours":
        raw = query(
            """
            SELECT entity, employee_name, billable_hours, credited_hours, not_credited_hours
            FROM timekeeper_hours WHERE period_start = ?
            """,
            [fy_start],
        )
        raw["name_key"] = raw["employee_name"].map(name_key)
        df = raw.groupby("name_key", as_index=False).agg(
            employee_name=("employee_name", "first"),
            client_hours=("billable_hours", "sum"),
            creditable_hours=("credited_hours", "sum"),
            other_hours=("not_credited_hours", "sum"),
            entities=("entity", lambda s: ", ".join(sorted(set(s.dropna())))),
        )
        df["foa_hours"] = df["pro_bono_hours"] = df["time_off_hours"] = 0.0
        return df
    return pd.DataFrame()


def _load_monthly(source: str, key: str, fy_start, as_of) -> pd.DataFrame:
    if source == "labor_detail":
        df = query(
            f"""
            SELECT DATE_TRUNC('month', transaction_date) AS month, {_LABOR_CATEGORY_SQL}
            FROM labor_detail
            WHERE name_key = ? AND transaction_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY 1
            """,
            [key, fy_start, as_of],
        )
    elif source == "monthly_hours":
        df = query(
            f"""
            SELECT month, {_WORKBOOK_CATEGORY_SQL}
            FROM monthly_hours WHERE name_key = ? AND month BETWEEN ? AND ?
            GROUP BY month ORDER BY month
            """,
            [key, fy_start, as_of],
        )
    else:
        return pd.DataFrame()
    df["month"] = pd.to_datetime(df["month"])
    return df


def _scorecard_for(fy_start, fy_end, as_of) -> tuple[pd.DataFrame | None, str, pd.DataFrame, pd.DataFrame | None]:
    """(scorecard, source, hours, people) for one measuring period, or (None, source, ...) if unavailable."""
    source = _hours_source(fy_start, as_of)
    if source == "none":
        return None, source, pd.DataFrame(), None
    people = _load_people(fy_start, source)
    if people is None or people.empty:
        return None, source, pd.DataFrame(), people
    hours = _load_hours(fy_start, as_of, source)
    tracked = people[people.apply(lambda p: hours_credit.person_targets(p)["expectation"] is not None, axis=1)]
    sc = hours_credit.build_scorecard(tracked, hours, _load_leave(), fy_start, fy_end, as_of)
    return sc, source, hours, people


# ---------------------------------------------------------------------------
# Creditable hours scorecard
# ---------------------------------------------------------------------------
_SOURCE_LABELS = {
    "labor_detail": "Vantagepoint labor detail export",
    "monthly_hours": "the firm's Monthly Hours Report by Timekeeper workbook",
    "timekeeper_hours": "the All Timekeepers Hours summary",
}


def _section_timekeeper_hours(fy_start: datetime.date, fy_end: datetime.date, as_of: datetime.date):
    st.subheader("Hours vs. Measuring Period Requirements")
    sc, source, hours, people = _scorecard_for(fy_start, fy_end, as_of)
    if source == "none":
        missing_source(
            f"hours for the {fy_start:%m/%d/%Y}–{fy_end:%m/%d/%Y} measuring period: the labor detail "
            "export (preferred), the Monthly Hours Report by Timekeeper workbook, or the All "
            "Timekeepers Hours export"
        )
        return
    if people is None:
        missing_source(
            "reference/employee_targets.csv",
            remedy="Generated automatically the first time build_warehouse.py runs with employee cost data loaded.",
        )
        return
    if sc is None or sc.empty:
        st.info(
            "No hours-required timekeepers yet. Fill in `target_type` (\"Attorney\" or \"Planner\") "
            "in `reference/employee_targets.csv` for everyone with a target, then refresh -- see the "
            "README's \"Measuring period hours\" section."
        )
        return
    leave = _load_leave()
    tracked = people[people["name_key"].isin(sc["name_key"])]
    sc = _add_promotion_lookback(sc, fy_start)
    # Anyone with a requirement but no hours at all in this period's source
    # (not yet hired, already gone, or a name mismatch) is listed under
    # Data checks rather than scored as a row of zeros.
    sc_all, sc = sc, sc[sc["has_hours"]]
    if sc.empty:
        st.info("None of the timekeepers with a requirement have hours in this period's source -- see Data checks.")
        _hours_data_quality(sc_all, hours, people, leave, source, fy_start, as_of)
        return

    period_wd = len(hours_credit.workdays(fy_start, fy_end))
    elapsed_wd = len(hours_credit.workdays(fy_start, min(as_of, fy_end)))
    reqs = " · ".join(
        f"{'Associates' if k == 'Attorney' else 'Planners/Project Specialists'} "
        f"{v:,} / {config.TOTAL_HOUR_TARGETS.get(k, 0):,} / {config.BONUS_HOUR_THRESHOLDS.get(k, 0):,}"
        for k, v in config.BILLABLE_HOUR_TARGETS.items()
    )
    st.caption(
        f"Source: {_SOURCE_LABELS[source]}. Per the Promotion and Bonus Policy — Hours Expectation / "
        f"Total Activity / Bonus Threshold: {reqs}, plus individual terms where set. **Credited hours** = "
        f"client + Firm's Own Account + pro bono + creditable non-billable (capped at "
        f"{config.CREDITABLE_NB_CAP} hrs). **Total activity** = all chargeable + non-chargeable hours"
        f", excluding PTO/sick/holiday (which never count). **Bonus hours** = "
        f"client + FOA + capped creditable (no pro bono). Requirements and the creditable cap are prorated "
        f"on workdays for approved leave and mid-period start/end dates. {elapsed_wd} of {period_wd} "
        f"workdays elapsed ({elapsed_wd / period_wd * 100:.0f}%). Status is the worse of Hours "
        f"Expectation and Total Activity."
    )
    if source in ("monthly_hours", "timekeeper_hours"):
        st.warning(
            f"{_SOURCE_LABELS[source].capitalize()} has only billable / credited / not-credited "
            "buckets, so its credited non-billable hours are all treated as *creditable* (capped at "
            f"{config.CREDITABLE_NB_CAP}). Under the policy, approved pro bono counts in full — anyone "
            "whose credited hours include pro bono is understated here. Firm's Own Account time is "
            "assumed to be inside the billable figure. The labor detail export classifies each entry "
            "exactly.",
            icon="⚠️",
        )

    # Filters
    role_opts = [r for r in [*config.BILLABLE_HOUR_TARGETS, "Custom"] if r in set(sc["Role"])]
    f1, f2 = st.columns(2)
    roles = f1.multiselect("Role", role_opts, default=role_opts,
                           help="Custom = individual terms (an Hours Expectation that isn't a role default).")
    statuses = f2.multiselect("Status", hours_credit.STATUS_ORDER, default=hours_credit.STATUS_ORDER)
    view = sc[sc["Role"].isin(roles) & sc["Status"].isin(statuses)]

    counts = sc["Status"].value_counts()
    bonus = sc["Bonus Status"].value_counts()
    closed = as_of >= fy_end
    kpi_row(
        [
            {"label": "Timekeepers tracked", "value": f"{len(sc)}",
             "help": "People with an Hours Expectation (role default or individual terms)."},
            {"label": "Met" if closed else "Met / On track",
             "value": f"{counts.get('Met', 0) + (0 if closed else counts.get('On Track', 0))}",
             "help": "Both Hours Expectation and Total Activity met (or on pace)."},
            {"label": "Not met" if closed else "Watch / Behind",
             "value": f"{counts.get('Not Met', 0) + counts.get('Watch', 0) + counts.get('Behind', 0)}",
             "help": f"Short on either requirement. Watch = {config.PACE_STATUS_THRESHOLDS[1] * 100:.0f}-"
                     f"{config.PACE_STATUS_THRESHOLDS[0] * 100:.0f}% of expected to date; Behind = below."},
            {"label": "Bonus eligible" if closed else "Bonus eligible / on pace",
             "value": f"{bonus.get('Eligible', 0)}" + ("" if closed else f" / {bonus.get('On pace', 0)}"),
             "help": "Bonus hours (client + FOA + capped creditable) at or above the prorated Bonus Threshold."},
            {"label": "Pro bono hours", "value": f"{sc['Pro Bono'].sum():,.0f}",
             "help": "Approved pro bono -- counts in full toward the Hours Expectation."},
            {"label": "Creditable NB over cap", "value": f"{sc['Creditable NB (over cap)'].sum():,.0f} hrs",
             "help": "Creditable non-billable hours logged above each person's (prorated) cap -- reported, not counted."},
        ]
    )

    if view.empty:
        st.info("No timekeepers match the selected filters.")
        return

    expected_pct = view["Expected to Date"] / view["Expectation"].where(view["Expectation"] > 0) * 100
    st.plotly_chart(target_progress(view, expected_pct), use_container_width=True)

    tab_exp, tab_total, tab_bonus, tab_promo = st.tabs(
        ["Hours Expectation", "Total Activity", "Bonus Eligibility", "Promotion (2-yr lookback)"]
    )
    h1 = st.column_config.NumberColumn(format="%.1f")
    pct = lambda help_: st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100, help=help_)
    status_rank = {s: i for i, s in enumerate(hours_credit.STATUS_ORDER)}

    def _tables(tab, cols, cfg, sort_col):
        with tab:
            for role in roles:
                sub = view[view["Role"] == role]
                if sub.empty:
                    continue
                sub = sub.assign(_r=sub[sort_col].map(lambda v: status_rank.get(v, 99))).sort_values(["_r", "Timekeeper"])
                label = {"Attorney": "Associates (attorneys)", "Planner": "Planners & Project Specialists"}.get(role, "Individual terms")
                st.markdown(f"**{label}**")
                st.dataframe(sub[cols], use_container_width=True, hide_index=True,
                             column_config={c: cfg.get(c, h1) for c in cols if c not in ("Timekeeper",) and not c.endswith("Status")})

    _tables(
        tab_exp,
        ["Timekeeper", "Expectation", "Leave Days", "Client", "FOA", "Pro Bono", "Creditable NB (logged)",
         "Creditable NB (counted)", "Credited Hours", "Expected to Date", "% of Expectation", "Pace %",
         "Projected", "Needed / Week", "Expectation Status"],
        {
            "Expectation": st.column_config.NumberColumn(format="%.1f", help="Prorated Hours Expectation"),
            "Creditable NB (counted)": st.column_config.NumberColumn(format="%.1f", help="Up to the prorated 75-hour cap"),
            "Credited Hours": st.column_config.NumberColumn(format="%.1f", help="Client + FOA + pro bono + creditable counted"),
            "% of Expectation": pct("Credited hours ÷ prorated Hours Expectation"),
            "Pace %": st.column_config.NumberColumn(format="%.0f%%", help="Credited hours ÷ expected to date"),
            "Projected": st.column_config.NumberColumn(format="%.0f", help="Straight-line year-end projection"),
            "Leave Days": st.column_config.NumberColumn(format="%.1f", help="Workdays of approved leave (weighted by percent away)"),
        },
        "Expectation Status",
    )
    _tables(
        tab_total,
        ["Timekeeper", "Total Expectation", "Client", "FOA", "Pro Bono", "Creditable NB (logged)", "Other NB",
         "Time Off", "Total Hours", "Total %", "Total Status"],
        {"Total %": pct("Total activity ÷ prorated Total Activity requirement"),
         "Total Expectation": st.column_config.NumberColumn(format="%.1f", help="Prorated Total Activity requirement")},
        "Total Status",
    )
    _tables(
        tab_bonus,
        ["Timekeeper", "Bonus Threshold", "Client", "FOA", "Creditable NB (counted)", "Bonus Hours", "Bonus %",
         "Pro Bono", "Bonus Credited Hours", "Bonus Status"],
        {"Bonus %": pct("Bonus hours ÷ prorated Bonus Threshold"),
         "Bonus Threshold": st.column_config.NumberColumn(format="%.1f", help="Prorated: 1850 Associates / 1550 Planners"),
         "Bonus Credited Hours": st.column_config.NumberColumn(format="%.1f", help="Once eligible, pro bono is added back (policy §3.5)")},
        "Bonus Status",
    )
    with tab_bonus:
        st.caption(
            "Eligibility only -- bonuses remain discretionary and subject to firm performance and "
            "policy compliance (including timely time entry), paid at the end of Q1."
        )
    _tables(
        tab_promo,
        ["Timekeeper", "% of Expectation", "Prior Period %", "2-yr Avg %", "Promotion Lookback"],
        {"% of Expectation": st.column_config.NumberColumn(format="%.0f%%", help="This period, to date"),
         "Prior Period %": st.column_config.NumberColumn(format="%.0f%%"),
         "2-yr Avg %": st.column_config.NumberColumn(format="%.0f%%")},
        "Expectation Status",
    )
    with tab_promo:
        st.caption(
            f"Policy §1c: promotion in a year the hours requirement wasn't met (exceptional "
            f"circumstances) needs an average of at least {config.PROMOTION_LOOKBACK_PCT}% of the Hours "
            f"Expectation over two years. Prior period comes from whichever hours source covers it "
            f"(the firm's monthly workbook backfills closed years)."
        )

    notes = []
    if source in ("monthly_hours", "timekeeper_hours"):
        notes.append(
            "This period's source has no separate pro bono figure: all credited non-billable hours are "
            f"treated as creditable (capped at {config.CREDITABLE_NB_CAP}), which understates anyone whose "
            "credited hours include approved pro bono."
        )
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download leadership report (HTML)",
        leadership_report.build_html(sc, fy_start, fy_end, as_of, _SOURCE_LABELS[source], notes).encode(),
        file_name=f"Measuring_Period_Hours_{fy_end:%Y}_through_{as_of:%Y%m%d}.html",
        mime="text/html",
        help="One self-contained file (charts included) to email or post to SharePoint/Teams; "
             "opens in any browser and prints to PDF.",
        use_container_width=True,
    )
    d2.download_button(
        "Download scorecard (CSV)",
        sc.drop(columns=["name_key", "has_hours"]).to_csv(index=False).encode(),
        file_name=f"measuring_period_hours_{as_of:%Y%m%d}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if source in ("labor_detail", "monthly_hours"):
        _person_drilldown(tracked, view, leave, fy_start, fy_end, as_of, source)

    _hours_data_quality(sc_all, hours, people, leave, source, fy_start, as_of)
    if source == "labor_detail":
        _classification_review(fy_start, as_of)


_CATEGORY_LABELS = {
    "foa": "Firm's Own Account (counts)", "pro_bono": "Pro bono (counts in full)",
    "creditable": "Creditable non-billable (capped)", "other": "Other non-billable (Total Activity only)",
    "time_off": "PTO / sick / holiday (never counts)",
}


def _classification_review(fy_start, as_of):
    """Every non-client project and how it was categorized, so the keyword
    rules (config.TIME_CATEGORY_KEYWORDS) can be checked against the new
    billing system's project names and corrected with
    config.TIME_CATEGORY_OVERRIDES."""
    df = query(
        """
        SELECT hours_category, matter_code, matter_name, labor_code,
               COUNT(DISTINCT name_key) AS timekeepers, SUM(hours) AS hours
        FROM labor_detail
        WHERE transaction_date BETWEEN ? AND ? AND hours_category <> 'client'
        GROUP BY ALL ORDER BY hours_category, hours DESC
        """,
        [fy_start, as_of],
    )
    if df.empty:
        return
    n_other = int((df["hours_category"] == "other").sum())
    with st.expander(f"How non-billable time was classified ({len(df)} projects)", expanded=False):
        st.caption(
            "Categories come from project name / labor code keywords (the policy's old file numbers no "
            "longer apply). If a project is in the wrong bucket, add its project number to "
            "`TIME_CATEGORY_OVERRIDES` in config.py and refresh."
            + (f" {n_other} project(s) are in *Other* (including non-billable or written-off time on "
               f"client matters) -- check these first." if n_other else "")
        )
        st.dataframe(
            df.assign(hours_category=df["hours_category"].map(_CATEGORY_LABELS).fillna(df["hours_category"])).rename(
                columns={"hours_category": "Category", "matter_code": "Project #", "matter_name": "Project Name",
                         "labor_code": "Labor Code", "timekeepers": "Timekeepers", "hours": "Hours"}),
            use_container_width=True, hide_index=True,
            column_config={"Hours": st.column_config.NumberColumn(format="%,.1f")},
        )


def _add_promotion_lookback(sc: pd.DataFrame, fy_start) -> pd.DataFrame:
    """Prior measuring period's % of Hours Expectation (full period) and the
    two-year average, for policy §1c's promotion lookback."""
    prior_start = datetime.date(fy_start.year - 1, fy_start.month, fy_start.day)
    prior_end = fy_start - datetime.timedelta(days=1)
    prior, *_ = _scorecard_for(prior_start, prior_end, prior_end)
    sc = sc.copy()
    if prior is not None:
        prior = prior[prior["has_hours"]]
    if prior is None or prior.empty:
        sc["Prior Period %"] = float("nan")
    else:
        sc = sc.merge(prior[["name_key", "% of Expectation"]].rename(columns={"% of Expectation": "Prior Period %"}),
                      on="name_key", how="left")
    sc["2-yr Avg %"] = sc[["% of Expectation", "Prior Period %"]].mean(axis=1, skipna=False)
    sc["Promotion Lookback"] = sc["2-yr Avg %"].map(
        lambda v: "" if pd.isna(v) else ("Meets 90% test" if v >= config.PROMOTION_LOOKBACK_PCT else "Below 90%")
    )
    return sc


def _person_drilldown(people, view, leave, fy_start, fy_end, as_of, source):
    with st.expander("Timekeeper detail — month-by-month pace", expanded=False):
        name = st.selectbox("Timekeeper", view.sort_values("Timekeeper")["Timekeeper"].tolist())
        row = view[view["Timekeeper"] == name].iloc[0]
        person = people[people["name_key"] == row["name_key"]].iloc[0]
        monthly = _load_monthly(source, row["name_key"], fy_start, as_of)
        if monthly.empty:
            st.info("No hours for this timekeeper in the period.")
            return
        pace = hours_credit.cumulative_pace(monthly, person, row, leave, fy_start, fy_end)
        pace = pace[pace["month"] <= pd.Timestamp(as_of)]
        st.plotly_chart(cumulative_vs_target(pace, name), use_container_width=True)
        labels = {"client_hours": "Client", "foa_hours": "FOA", "pro_bono_hours": "Pro Bono",
                  "creditable_hours": "Creditable NB", "other_hours": "Other NB", "time_off_hours": "Time Off"}
        shown = [c for c in labels if monthly[c].abs().sum() > 0]
        st.dataframe(
            monthly.assign(month=monthly["month"].dt.strftime("%b %Y"))[["month", *shown]].rename(
                columns={"month": "Month", **labels}),
            use_container_width=True, hide_index=True,
            column_config={labels[c]: st.column_config.NumberColumn(format="%.1f") for c in shown},
        )
        if source == "monthly_hours":
            note = query(
                "SELECT ANY_VALUE(note) AS note FROM monthly_hours WHERE name_key = ? AND month BETWEEN ? AND ?",
                [row["name_key"], fy_start, as_of],
            ).iloc[0]["note"]
            if note:
                st.caption(f"From the workbook: {note}")
        p_leave = leave[leave["name_key"] == row["name_key"]] if not leave.empty else leave
        if not p_leave.empty:
            st.caption(
                "Approved leave: "
                + "; ".join(
                    (f"{r.leave_type or 'Leave'} {pd.Timestamp(r.leave_start):%m/%d/%Y}–{pd.Timestamp(r.leave_end):%m/%d/%Y}"
                     if pd.notna(r.leave_end) else f"{r.leave_type or 'Leave'} from {pd.Timestamp(r.leave_start):%m/%d/%Y} (open)")
                    + (f" at {r.percent_away:.0f}%" if r.percent_away < 100 else "")
                    for r in p_leave.itertuples()
                )
            )


def _hours_data_quality(sc, hours, people, leave, source, fy_start, as_of):
    issues = []
    no_hours = sc.loc[~sc["has_hours"], "Timekeeper"].tolist()
    if no_hours:
        issues.append(
            f"{len(no_hours)} timekeeper(s) with a requirement have no hours in this period's source and "
            f"aren't scored (not employed yet / already gone, or a name mismatch): {', '.join(no_hours)}"
        )
    if not hours.empty:
        tracked_keys = set(sc["name_key"])
        known = set(people["name_key"].dropna())
        stray = hours[~hours["name_key"].isin(known)]
        if not stray.empty:
            issues.append(
                f"**{len(stray)} timekeeper(s) in the hours data aren't in reference/employee_targets.csv** "
                f"(add them, with a blank target_type if exempt): {', '.join(sorted(stray['employee_name'].astype(str)))}"
            )
        untracked = hours[hours["name_key"].isin(known - tracked_keys)]
        if not untracked.empty:
            issues.append(
                f"{len(untracked)} timekeeper(s) logged time but have no requirement for this period, so "
                f"they're not scored (exempt, or a mid-year hire whose target wasn't set -- the policy "
                f"prorates a first period, so add their role and start_date): "
                + ", ".join(f"{r.employee_name} ({r.client_hours:,.0f} client hrs)"
                            for r in untracked.sort_values("employee_name").itertuples())
            )
    over = sc[sc["Creditable NB (over cap)"] > 0]
    if not over.empty:
        issues.append(
            f"{len(over)} timekeeper(s) logged more creditable non-billable hours than their cap; only the "
            f"cap counts"
            + (" (the workbook's own \"Billable\" column adds all credited hours, uncapped, so its totals "
               "read higher than this page)" if source == "monthly_hours" else "")
            + ": " + ", ".join(f"{t} {lg:,.0f} logged / {cp:,.0f} cap" for t, lg, cp in
                               over[["Timekeeper", "Creditable NB (logged)", "Creditable Cap"]].itertuples(index=False))
        )
    if source == "monthly_hours":
        partial = query(
            "SELECT ANY_VALUE(employee_name) AS n FROM monthly_hours "
            "WHERE partial_month AND month BETWEEN ? AND ? GROUP BY name_key", [fy_start, as_of]
        )
        no_end = [n for n in partial["n"] if people.loc[people["full_name"] == n, "end_date"].isna().all()]
        if no_end:
            issues.append(
                f"Partial final month in the workbook with no end_date in employee_targets.csv (their "
                f"requirements aren't prorated for leaving): {', '.join(no_end)}"
            )
    if not leave.empty:
        unmatched_leave = leave[~leave["name_key"].isin(set(people["name_key"]))]
        if not unmatched_leave.empty:
            issues.append(
                f"{len(unmatched_leave)} leave row(s) in reference/leave.csv don't match anyone in "
                f"employee_targets.csv: {', '.join(unmatched_leave['full_name'].astype(str))}"
            )
    if issues:
        with st.expander(f"Data checks ({len(issues)})", expanded=False):
            for i in issues:
                st.markdown(f"- {i}")


# ---------------------------------------------------------------------------
# Timekeeper profitability
# ---------------------------------------------------------------------------
def _timekeeper_economics(fy_start, as_of) -> tuple[pd.DataFrame, str, str] | None:
    """Per-person hours, revenue and direct labor cost for the period.
    Returns (df, revenue_basis_label, cost_basis_label) or None."""
    if not table_exists("labor_detail"):
        return None
    lab = query(
        """
        SELECT name_key,
               ANY_VALUE(employee_name) AS employee_name,
               SUM(CASE WHEN NOT is_time_off THEN hours ELSE 0 END) AS total_hours,
               SUM(CASE WHEN is_billable THEN hours ELSE 0 END) AS billable_hours,
               SUM(CASE WHEN is_pro_bono THEN hours ELSE 0 END) AS pro_bono_hours,
               SUM(standard_value) AS standard_value,
               SUM(billed_amount) AS billed_amount,
               COUNT(billed_amount) AS n_billed,
               SUM(cost_amount) AS cost_amount,
               COUNT(cost_amount) AS n_cost
        FROM labor_detail
        WHERE transaction_date BETWEEN ? AND ?
        GROUP BY name_key
        """,
        [fy_start, as_of],
    )
    if lab.empty:
        return None

    use_billed = lab["n_billed"].sum() > 0
    lab["revenue"] = (lab["billed_amount"] if use_billed else lab["standard_value"]).fillna(0.0)
    revenue_basis = "billed amount" if use_billed else "standard value (hours × bill rate, before write-downs)"

    # Cost: labor detail's own cost extension when the export carries it;
    # otherwise Employee Cost Rate Details (hourly x hours, salary x months).
    lab["cost"] = lab["cost_amount"].where(lab["n_cost"] > 0)
    cost_basis = "labor detail cost extension"
    people = _load_people()
    if people is not None:
        lab = lab.merge(people[["name_key", "full_name", "role", "start_date", "end_date"]], on="name_key", how="left")
        lab["employee_name"] = lab["full_name"].fillna(lab["employee_name"])
    else:
        lab["role"], lab["start_date"], lab["end_date"] = None, None, None
    if lab["cost"].isna().any() and table_exists("employee_cost_rates"):
        rates = query(
            "SELECT full_name, job_cost_type, job_cost_rate FROM employee_cost_rates "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM employee_cost_rates)"
        )
        rates["name_key"] = rates["full_name"].map(name_key)
        lab = lab.merge(rates[["name_key", "job_cost_type", "job_cost_rate"]].drop_duplicates("name_key"), on="name_key", how="left")

        def _rate_cost(r):
            if pd.notna(r["cost"]):
                return r["cost"]
            if r.get("job_cost_type") == "Hourly":
                return r["total_hours"] * r["job_cost_rate"]
            if r.get("job_cost_type") == "Salary":
                s = max(pd.Timestamp(fy_start), pd.Timestamp(r["start_date"])) if pd.notna(r["start_date"]) else fy_start
                e = min(pd.Timestamp(as_of), pd.Timestamp(r["end_date"])) if pd.notna(r["end_date"]) else as_of
                return hours_credit.salary_cost(r["job_cost_rate"], s, e)
            return None

        lab["cost"] = lab.apply(_rate_cost, axis=1)
        cost_basis = (
            "Employee Cost Rate Details (hourly staff: hours × cost rate; salaried staff: monthly "
            "rate × months elapsed in the period, regardless of hours)"
            if lab["n_cost"].sum() == 0
            else "labor detail cost extension, else Employee Cost Rate Details"
        )

    lab["cost"] = pd.to_numeric(lab["cost"], errors="coerce")
    lab["contribution"] = lab["revenue"] - lab["cost"]
    lab["margin_pct"] = lab["contribution"] / lab["revenue"].where(lab["revenue"] != 0) * 100
    lab["revenue_per_hr"] = lab["revenue"] / lab["billable_hours"].where(lab["billable_hours"] > 0)
    lab["cost_per_hr"] = lab["cost"] / lab["total_hours"].where(lab["total_hours"] > 0)
    lab["pro_bono_cost"] = lab["pro_bono_hours"] * lab["cost_per_hr"]
    lab["role"] = lab["role"].fillna("No target")
    if use_billed:
        lab["realization_pct"] = lab["billed_amount"] / lab["standard_value"].where(lab["standard_value"] > 0) * 100
    return lab, revenue_basis, cost_basis


def _section_timekeeper_profitability(fy_start, fy_end, as_of):
    st.subheader("Timekeeper Profitability")
    econ = _timekeeper_economics(fy_start, as_of)
    if econ is None:
        missing_source(
            "the labor detail export with Billing Extension (and ideally Billed Amount / Cost "
            "Extension) columns, plus the Employee Cost Rate Details export",
            remedy="The All Timekeepers Hours summary has hours only, no dollars, so it can't drive this view.",
        )
        return
    df, revenue_basis, cost_basis = econ

    tot_rev, tot_cost = df["revenue"].sum(), df["cost"].sum(skipna=True)
    contrib = tot_rev - tot_cost
    kpi_row(
        [
            {"label": "Revenue", "value": fmt_currency(tot_rev, short=True), "help": f"Basis: {revenue_basis}."},
            {"label": "Direct labor cost", "value": fmt_currency(tot_cost, short=True), "help": f"Basis: {cost_basis}."},
            {"label": "Labor contribution", "value": fmt_currency(contrib, short=True)},
            {"label": "Contribution margin", "value": f"{contrib / tot_rev * 100:.0f}%" if tot_rev else "--"},
            {"label": "Pro bono investment", "value": fmt_currency(df["pro_bono_cost"].sum(skipna=True), short=True),
             "help": "Pro bono hours × each person's average cost per hour."},
        ]
    )

    by_role = df.groupby("role", as_index=False).agg(
        timekeepers=("name_key", "count"), billable_hours=("billable_hours", "sum"),
        revenue=("revenue", "sum"), cost=("cost", "sum"),
    )
    by_role["contribution"] = by_role["revenue"] - by_role["cost"]
    by_role["margin_pct"] = by_role["contribution"] / by_role["revenue"].where(by_role["revenue"] != 0) * 100
    by_role["revenue_per_hr"] = by_role["revenue"] / by_role["billable_hours"].where(by_role["billable_hours"] > 0)
    money = st.column_config.NumberColumn(format="$%,.0f")
    st.markdown("**By role**")
    st.dataframe(
        by_role.rename(columns={
            "role": "Role", "timekeepers": "Timekeepers", "billable_hours": "Billable Hours",
            "revenue": "Revenue", "cost": "Labor Cost", "contribution": "Contribution",
            "margin_pct": "Margin %", "revenue_per_hr": "Revenue / Billable Hr",
        }),
        use_container_width=True, hide_index=True,
        column_config={
            "Revenue": money, "Labor Cost": money, "Contribution": money, "Revenue / Billable Hr": money,
            "Billable Hours": st.column_config.NumberColumn(format="%,.1f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    st.plotly_chart(
        ranked_bar(df.rename(columns={"employee_name": "Timekeeper"}), label_col="Timekeeper",
                   value_col="contribution", series_col="role", top_n=20,
                   title="Top 20 timekeepers by labor contribution"),
        use_container_width=True,
    )

    cols = {
        "employee_name": "Timekeeper", "role": "Role", "total_hours": "Total Hours",
        "billable_hours": "Billable Hours", "pro_bono_hours": "Pro Bono Hours", "revenue": "Revenue",
        "cost": "Labor Cost", "contribution": "Contribution", "margin_pct": "Margin %",
        "revenue_per_hr": "Revenue / Billable Hr", "cost_per_hr": "Cost / Hr",
    }
    if "realization_pct" in df:
        cols["realization_pct"] = "Realization %"
    st.markdown("**By timekeeper**")
    st.dataframe(
        df.sort_values("contribution", ascending=False)[list(cols)].rename(columns=cols),
        use_container_width=True, hide_index=True,
        column_config={
            **{c: money for c in ["Revenue", "Labor Cost", "Contribution", "Revenue / Billable Hr", "Cost / Hr"]},
            **{c: st.column_config.NumberColumn(format="%,.1f") for c in ["Total Hours", "Billable Hours", "Pro Bono Hours"]},
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
            "Realization %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    n_no_cost = int(df["cost"].isna().sum())
    st.caption(
        f"Revenue = {revenue_basis}. Cost = {cost_basis}. This is *direct labor* contribution -- rent, "
        "admin salaries and other overhead aren't allocated, so it's a ranking and trend tool, not "
        "net profit. Salaried timekeepers carry their full salary cost whether or not their hours "
        "are billable, which is the point: low-utilization salaried time shows up as low margin."
        + (f" {n_no_cost} timekeeper(s) didn't match a cost rate and show no cost." if n_no_cost else "")
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
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM originations)
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

    flagged = (
        query(
            "SELECT status, COUNT(*) AS matters FROM originations_flagged "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM originations_flagged) "
            "GROUP BY status ORDER BY matters DESC"
        )
        if table_exists("originations_flagged")
        else pd.DataFrame()
    )
    if not flagged.empty:
        st.markdown("**Matters needing attention**")
        st.dataframe(flagged, use_container_width=True, hide_index=True)


def _section_practice_group_profitability(fy_start, as_of):
    st.subheader("Practice Group Profitability")
    if table_exists("labor_detail") and table_exists("matter_list"):
        _practice_groups_from_labor(fy_start, as_of)
        st.markdown("**NTE-capped matters (job-to-date)**")
    _practice_groups_from_nte()


def _practice_groups_from_labor(fy_start, as_of):
    """Full-portfolio view: every matter with time in the period. Revenue
    per matter from labor detail; labor cost allocated by hours at each
    timekeeper's average cost per hour for the period (same cost basis
    as Timekeeper Profitability above, so the two reconcile)."""
    econ = _timekeeper_economics(fy_start, as_of)
    if econ is None:
        return
    people_econ, revenue_basis, _ = econ
    use_billed = revenue_basis.startswith("billed")
    by_matter = query(
        f"""
        SELECT matter_code, name_key, SUM(hours) AS hours,
               SUM({'billed_amount' if use_billed else 'standard_value'}) AS revenue
        FROM labor_detail
        WHERE transaction_date BETWEEN ? AND ?
        GROUP BY matter_code, name_key
        """,
        [fy_start, as_of],
    )
    by_matter = by_matter.merge(people_econ[["name_key", "cost_per_hr"]], on="name_key", how="left")
    by_matter["cost"] = by_matter["hours"] * by_matter["cost_per_hr"]
    orgs = query(
        "SELECT matter_code, organization_name FROM matter_list "
        "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM matter_list)"
    ).drop_duplicates("matter_code")
    by_matter = by_matter.merge(orgs, on="matter_code", how="left")
    by_matter["practice_group"] = by_matter["organization_name"].fillna("Unmapped")
    pg = by_matter.groupby("practice_group", as_index=False).agg(
        matters=("matter_code", "nunique"), hours=("hours", "sum"),
        revenue=("revenue", "sum"), cost=("cost", "sum"),
    )
    pg["contribution"] = pg["revenue"].fillna(0) - pg["cost"].fillna(0)
    pg["margin_pct"] = pg["contribution"] / pg["revenue"].where(pg["revenue"] != 0) * 100
    pg = pg.sort_values("contribution", ascending=False)
    money = st.column_config.NumberColumn(format="$%,.0f")
    st.markdown(f"**All matters with time {fy_start:%m/%d/%Y}–{as_of:%m/%d/%Y}**")
    st.dataframe(
        pg.rename(columns={
            "practice_group": "Practice Group", "matters": "Matters", "hours": "Hours", "revenue": "Revenue",
            "cost": "Labor Cost", "contribution": "Contribution", "margin_pct": "Margin %",
        }),
        use_container_width=True, hide_index=True,
        column_config={
            "Revenue": money, "Labor Cost": money, "Contribution": money,
            "Hours": st.column_config.NumberColumn(format="%,.1f"),
            "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    mapped = by_matter.loc[by_matter["organization_name"].notna(), "hours"].sum() / max(by_matter["hours"].sum(), 1e-9)
    st.caption(
        f"Revenue = {revenue_basis}; labor cost allocated to matters by hours at each timekeeper's "
        f"average cost per hour (salaried cost spread over all their hours, including non-billable). "
        f"Practice group from the matter list's Organization Name; {mapped * 100:.0f}% of hours "
        f"matched a matter code. Direct labor only -- no overhead allocation."
    )


def _practice_groups_from_nte():
    if not (table_exists("matter_earnings") and table_exists("matter_list")):
        missing_source("the NTE Tracking Report + matter list export (for the practice-group taxonomy)")
        return
    # Neither matter_earnings nor matter_list has a genuine per-row
    # snapshot date -- both filtered to their own latest snapshot_date so
    # a reload on a later day (leaving a duplicate snapshot behind on
    # either side) can't fan out the join and double revenue/profit.
    df = query(
        """
        SELECT
            COALESCE(m.organization_name, 'Unmapped') AS practice_group,
            COUNT(*) AS matters,
            SUM(e.jtd_revenue) AS revenue,
            SUM(e.jtd_profit) AS profit
        FROM matter_earnings e
        LEFT JOIN matter_list m ON e.matter_code = m.matter_code
            AND m.snapshot_date = (SELECT MAX(snapshot_date) FROM matter_list)
        WHERE e.snapshot_date = (SELECT MAX(snapshot_date) FROM matter_earnings)
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
        FROM matter_earnings e
        LEFT JOIN matter_list m ON e.matter_code = m.matter_code
            AND m.snapshot_date = (SELECT MAX(snapshot_date) FROM matter_list)
        WHERE e.snapshot_date = (SELECT MAX(snapshot_date) FROM matter_earnings)
        """
    ).iloc[0]
    st.caption(
        f"Real JTD revenue/profit, but only for the {int(match['total'])} matters billed against "
        f"a not-to-exceed cap -- flat-fee and T&E matters (most of the ~315-matter portfolio) are "
        f"never NTE-capped, so they structurally don't appear in this report; it's not a coverage "
        f"gap to fill with more of the same export. Directional for these practice groups, not a "
        f"complete picture firm-wide. {match['matched']}/{match['total']} matched to a practice "
        f"group by matter code; unmatched group as \"Unmapped\"."
    )
