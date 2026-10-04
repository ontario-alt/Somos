"""
Measuring Period dashboard -- the fixed fiscal-year (10/1-9/30) window
the firm measures hours and profitability on:

  * Creditable Hours vs. Prorated Target -- the hours scorecard. Each
    hours-required timekeeper's role target (attorney / planner, see
    config.BILLABLE_HOUR_TARGETS), prorated for leave and partial-year
    employment, against billable hours + pro bono (pro bono credit capped
    at config.PRO_BONO_CREDIT_CAP). Math lives in dashboard/hours_credit.py.
  * Timekeeper Profitability -- revenue vs. direct labor cost per person
    and per role, from the labor detail export + employee cost rates.
  * FY revenue by entity (GL), FY vs prior FY, originations, and
    practice-group profitability (full portfolio from labor detail when
    loaded; the NTE Tracking Report's JTD view as a supplement).

Preferred hours source is the transaction-level labor detail export
(etl/parse_labor_detail.py): it separates pro bono from other time,
gives month-by-month pace, and carries dollars. Without it the
scorecard falls back to the "All Timekeepers Hours" summary, using its
Credited Hours column as the pro bono figure -- captioned as such, since
that column may include credited time that isn't pro bono.

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
from dashboard import hours_credit
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
    today = datetime.date.today()
    if table_exists("labor_detail"):
        v = query("SELECT MAX(transaction_date) AS v FROM labor_detail").iloc[0]["v"]
        if v is not None and not pd.isna(v):
            return pd.Timestamp(v).date()
    if table_exists("timekeeper_hours"):
        v = query("SELECT MAX(period_end) AS v FROM timekeeper_hours").iloc[0]["v"]
        if v is not None and not pd.isna(v):
            return min(today, pd.Timestamp(v).date())
    return today


def _load_people() -> pd.DataFrame | None:
    """Hours-required timekeepers (role set) from reference/employee_targets.csv."""
    if not table_exists("employee_targets"):
        return None
    cols = set(query("SELECT * FROM employee_targets LIMIT 0").columns)
    if "name_key" not in cols:
        st.warning(
            "The warehouse's employee_targets table is from an older version -- click "
            "**Refresh data** (or run `python etl/build_warehouse.py`) to rebuild it."
        )
        return None
    # No genuine per-row snapshot -- pinned to the latest snapshot_date so
    # a leftover older snapshot can't fan out a join.
    df = query(
        """
        SELECT full_name, name_key, employee_number, target_type AS role, start_date, end_date
        FROM employee_targets
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM employee_targets)
        """
    )
    df["role"] = df["role"].map(config.resolve_role)
    return df


def _load_leave() -> pd.DataFrame:
    if not table_exists("employee_leave"):
        return pd.DataFrame(columns=["name_key", "employee_number", "leave_start", "leave_end", "percent_away"])
    return query("SELECT name_key, employee_number, leave_start, leave_end, percent_away, leave_type, full_name FROM employee_leave")


def _load_hours(fy_start, as_of) -> tuple[pd.DataFrame, str]:
    """Per-person billable / pro bono hours to date, plus which source they came from."""
    if table_exists("labor_detail"):
        df = query(
            """
            SELECT name_key,
                   ANY_VALUE(employee_name) AS employee_name,
                   SUM(CASE WHEN is_billable THEN hours ELSE 0 END) AS billable_hours,
                   SUM(CASE WHEN is_pro_bono THEN hours ELSE 0 END) AS pro_bono_hours,
                   SUM(hours) AS total_hours,
                   STRING_AGG(DISTINCT entity, ', ' ORDER BY entity) AS entities
            FROM labor_detail
            WHERE transaction_date BETWEEN ? AND ?
            GROUP BY name_key
            """,
            [fy_start, as_of],
        )
        return df, "labor_detail"
    if table_exists("timekeeper_hours"):
        raw = query(
            """
            SELECT entity, employee_name, billable_hours, credited_hours, total_hours
            FROM timekeeper_hours WHERE period_start = ?
            """,
            [fy_start],
        )
        if raw.empty:
            return raw, "timekeeper_hours"
        raw["name_key"] = raw["employee_name"].map(name_key)
        df = raw.groupby("name_key", as_index=False).agg(
            employee_name=("employee_name", "first"),
            billable_hours=("billable_hours", "sum"),
            pro_bono_hours=("credited_hours", "sum"),
            total_hours=("total_hours", "sum"),
            entities=("entity", lambda s: ", ".join(sorted(set(s.dropna())))),
        )
        return df, "timekeeper_hours"
    return pd.DataFrame(), "none"


# ---------------------------------------------------------------------------
# Creditable hours scorecard
# ---------------------------------------------------------------------------
def _section_timekeeper_hours(fy_start: datetime.date, fy_end: datetime.date, as_of: datetime.date):
    st.subheader("Creditable Hours vs. Prorated Target")
    people = _load_people()
    if people is None:
        missing_source(
            "reference/employee_targets.csv",
            remedy="Generated automatically the first time build_warehouse.py runs with employee cost data loaded.",
        )
        return
    hours, source = _load_hours(fy_start, as_of)
    if source == "none":
        missing_source("the labor detail export (preferred) or the All Timekeepers Hours export")
        return

    tracked = people[people["role"].notna()]
    if tracked.empty:
        st.info(
            "No hours-required timekeepers yet. Fill in `target_type` (\"Attorney\" or \"Planner\") "
            "in `reference/employee_targets.csv` for everyone with a target, then refresh -- see the "
            "README's \"Measuring period hours\" section."
        )
        return

    leave = _load_leave()
    sc = hours_credit.build_scorecard(tracked, hours, leave, fy_start, fy_end, as_of)
    period_wd = len(hours_credit.workdays(fy_start, fy_end))
    elapsed_wd = len(hours_credit.workdays(fy_start, min(as_of, fy_end)))

    targets_txt = " · ".join(f"{k} {v:,} hrs" for k, v in config.BILLABLE_HOUR_TARGETS.items())
    st.caption(
        f"Annual targets: {targets_txt}. Creditable = billable + pro bono, pro bono credit capped at "
        f"{config.PRO_BONO_CREDIT_CAP} hrs{' (prorated)' if config.PRO_BONO_CAP_PRORATED else ''} per "
        f"person. Targets prorated on workdays for approved leave (reference/leave.csv) and mid-period "
        f"start/end dates. {elapsed_wd} of {period_wd} workdays elapsed "
        f"({elapsed_wd / period_wd * 100:.0f}%). \"Expected to date\" scales each person's prorated "
        f"target by their own available workdays elapsed, so time on leave doesn't count against pace."
    )
    if source == "timekeeper_hours":
        st.warning(
            "Using the All Timekeepers Hours summary (no labor detail export loaded): its *Credited "
            "Hours* column is treated as pro bono, which overstates pro bono if that column includes "
            "other credited time. Load the labor detail export for an exact pro bono split and "
            "monthly pace.",
            icon="⚠️",
        )

    # Filters
    f1, f2 = st.columns(2)
    roles = f1.multiselect("Role", list(config.BILLABLE_HOUR_TARGETS), default=list(config.BILLABLE_HOUR_TARGETS))
    statuses = f2.multiselect("Status", hours_credit.STATUS_ORDER, default=hours_credit.STATUS_ORDER)
    view = sc[sc["Role"].isin(roles) & sc["Status"].isin(statuses)]

    counts = sc["Status"].value_counts()
    firm_cred, firm_exp = sc["Creditable"].sum(), sc["Expected to Date"].sum()
    kpi_row(
        [
            {"label": "Timekeepers tracked", "value": f"{len(sc)}",
             "help": "People with a role in reference/employee_targets.csv."},
            {"label": "Met / On track", "value": f"{counts.get('Met', 0) + counts.get('On Track', 0)}",
             "help": f"Pace ≥ {config.PACE_STATUS_THRESHOLDS[0] * 100:.0f}% of expected-to-date, or target already met."},
            {"label": "Watch", "value": f"{counts.get('Watch', 0)}",
             "help": f"Pace {config.PACE_STATUS_THRESHOLDS[1] * 100:.0f}-{config.PACE_STATUS_THRESHOLDS[0] * 100:.0f}% of expected."},
            {"label": "Behind", "value": f"{counts.get('Behind', 0)}",
             "help": f"Pace below {config.PACE_STATUS_THRESHOLDS[1] * 100:.0f}% of expected."},
            {"label": "Team pace", "value": f"{firm_cred / firm_exp * 100:.0f}%" if firm_exp else "--",
             "help": f"{firm_cred:,.0f} creditable hrs vs. {firm_exp:,.0f} expected to date, all tracked timekeepers."},
            {"label": "Pro bono credited", "value": f"{sc['Pro Bono (credited)'].sum():,.0f} hrs",
             "delta": f"{sc['Pro Bono (over cap)'].sum():,.0f} hrs over cap" if sc["Pro Bono (over cap)"].sum() else None,
             "help": "Pro bono logged above the per-person cap is reported but not credited."},
        ]
    )

    if view.empty:
        st.info("No timekeepers match the selected filters.")
        return

    expected_pct = view["Expected to Date"] / view["Prorated Target"].where(view["Prorated Target"] > 0) * 100
    st.plotly_chart(target_progress(view, expected_pct), use_container_width=True)

    display_cols = [
        "Timekeeper", "Entities", "Prorated Target", "Leave Days", "Billable", "Pro Bono (logged)",
        "Pro Bono (credited)", "Creditable", "Expected to Date", "Variance to Expected", "% of Target",
        "Pace %", "Projected", "Remaining", "Needed / Week", "Status",
    ]
    hrs_fmt = st.column_config.NumberColumn(format="%.1f")
    col_cfg = {c: hrs_fmt for c in display_cols if c not in ("Timekeeper", "Entities", "Status", "% of Target", "Pace %")}
    col_cfg.update(
        {
            "% of Target": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            "Pace %": st.column_config.NumberColumn(format="%.0f%%", help="Creditable ÷ expected to date"),
            "Projected": st.column_config.NumberColumn(format="%.0f", help="Straight-line: creditable ÷ share of available time elapsed"),
            "Needed / Week": st.column_config.NumberColumn(format="%.1f", help="Creditable hours per remaining available week to hit target"),
            "Leave Days": st.column_config.NumberColumn(format="%.1f", help="Workdays of approved leave in the period (weighted by percent away)"),
        }
    )
    status_rank = {s: i for i, s in enumerate(hours_credit.STATUS_ORDER)}
    for role in roles:
        sub = view[view["Role"] == role]
        if sub.empty:
            continue
        sub = sub.assign(_r=sub["Status"].map(status_rank)).sort_values(["_r", "Pace %"])
        st.markdown(f"**{role}s** — target {config.BILLABLE_HOUR_TARGETS[role]:,} hrs/yr before proration")
        st.dataframe(sub[display_cols], use_container_width=True, hide_index=True, column_config=col_cfg)

    st.download_button(
        "Download scorecard (CSV)",
        sc.drop(columns=["name_key", "has_hours"]).to_csv(index=False).encode(),
        file_name=f"measuring_period_hours_{as_of:%Y%m%d}.csv",
        mime="text/csv",
    )

    if source == "labor_detail":
        _person_drilldown(tracked, view, leave, fy_start, fy_end, as_of)

    _hours_data_quality(sc, hours, people, leave)


def _person_drilldown(people, view, leave, fy_start, fy_end, as_of):
    with st.expander("Timekeeper detail — month-by-month pace", expanded=False):
        name = st.selectbox("Timekeeper", view.sort_values("Timekeeper")["Timekeeper"].tolist())
        row = view[view["Timekeeper"] == name].iloc[0]
        person = people[people["name_key"] == row["name_key"]].iloc[0]
        monthly = query(
            """
            SELECT DATE_TRUNC('month', transaction_date) AS month,
                   SUM(CASE WHEN is_billable THEN hours ELSE 0 END) AS billable_hours,
                   SUM(CASE WHEN is_pro_bono THEN hours ELSE 0 END) AS pro_bono_hours,
                   SUM(CASE WHEN NOT is_billable AND NOT is_pro_bono THEN hours ELSE 0 END) AS other_hours
            FROM labor_detail
            WHERE name_key = ? AND transaction_date BETWEEN ? AND ?
            GROUP BY 1 ORDER BY 1
            """,
            [row["name_key"], fy_start, as_of],
        )
        if monthly.empty:
            st.info("No time entries for this timekeeper in the period.")
            return
        monthly["month"] = pd.to_datetime(monthly["month"])
        pace = hours_credit.cumulative_pace(monthly, person, row, leave, fy_start, fy_end)
        pace = pace[pace["month"] <= pd.Timestamp(as_of)]
        st.plotly_chart(cumulative_vs_target(pace, name), use_container_width=True)
        st.dataframe(
            monthly.assign(month=monthly["month"].dt.strftime("%b %Y")).rename(
                columns={"month": "Month", "billable_hours": "Billable", "pro_bono_hours": "Pro Bono",
                         "other_hours": "Other (non-creditable)"}
            ),
            use_container_width=True, hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ["Billable", "Pro Bono", "Other (non-creditable)"]},
        )
        p_leave = leave[leave["name_key"] == row["name_key"]] if not leave.empty else leave
        if not p_leave.empty:
            st.caption(
                "Approved leave: "
                + "; ".join(
                    f"{r.leave_type or 'Leave'} {pd.Timestamp(r.leave_start):%m/%d/%Y}–"
                    f"{pd.Timestamp(r.leave_end):%m/%d/%Y}" if pd.notna(r.leave_end) else
                    f"{r.leave_type or 'Leave'} from {pd.Timestamp(r.leave_start):%m/%d/%Y} (open)"
                    + (f" at {r.percent_away:.0f}%" if r.percent_away < 100 else "")
                    for r in p_leave.itertuples()
                )
            )


def _hours_data_quality(sc, hours, people, leave):
    issues = []
    no_hours = sc.loc[~sc["has_hours"], "Timekeeper"].tolist()
    if no_hours:
        issues.append(
            f"**{len(no_hours)} tracked timekeeper(s) have no hours in the export** (name mismatch, or "
            f"genuinely no time logged): {', '.join(no_hours)}"
        )
    if not hours.empty:
        known = set(people["name_key"].dropna())
        stray = hours[~hours["name_key"].isin(known)]
        if not stray.empty:
            issues.append(
                f"**{len(stray)} timekeeper(s) in the hours data aren't in reference/employee_targets.csv** "
                f"(add them, with a blank target_type if exempt): {', '.join(sorted(stray['employee_name'].astype(str)))}"
            )
        exempt = set(people.loc[people["role"].isna(), "name_key"])
        heavy = hours[hours["name_key"].isin(exempt) & (hours["billable_hours"] > 500)]
        if not heavy.empty:
            issues.append(
                f"{len(heavy)} timekeeper(s) marked exempt have 500+ billable hours -- confirm they "
                f"shouldn't have a target: {', '.join(sorted(heavy['employee_name'].astype(str)))}"
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
               SUM(hours) AS total_hours,
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
