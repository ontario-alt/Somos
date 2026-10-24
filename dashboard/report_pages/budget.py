"""
Budget page -- builds next calendar year's budget (config.BUDGET_YEAR)
from Vantagepoint and the firm's P&L. The method is in
dashboard/budget_model.py:

- People plan: fee revenue (hours x rate x realization) and salaries +
  fringe, prefilled from employee cost rates, hour targets and the last
  12 months of labor detail.
- Overhead: prior-year P&L lines (P&L workbook, else the GL) + a % change.
- Budget drivers: lines you type in -- owner draws, guaranteed payments,
  bonuses, leases, capex. Owner draws sit below net income.

Edits live in the session until you click Save, which writes them to
reference/budget_<year>/ (gitignored: names and pay). The Excel export
has live formulas so the budget can keep being worked on in Excel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from dashboard import budget_model as bm
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.theme import CATEGORICAL, INK_SECONDARY, apply_layout, fmt_currency
from dashboard.data import query, table_exists

SS = "budget_"  # session_state key prefix


def _money_md(v) -> str:
    """Currency for st.markdown/caption text ("$" would start a math block)."""
    return fmt_currency(v).replace("$", "\\$")


# ---------------------------------------------------------------------------
# Data from the warehouse
# ---------------------------------------------------------------------------
def _latest(table: str, cols: str) -> pd.DataFrame | None:
    if not table_exists(table):
        return None
    return query(f"SELECT {cols} FROM {table} WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {table})")


def _actuals() -> tuple[pd.DataFrame, str]:
    if table_exists("pl_actuals"):
        df = query("SELECT * FROM pl_actuals")
        if not df.empty:
            return df, "P&L workbook"
    if table_exists("gl_trial_balance"):
        df = bm.gl_to_actuals(query("SELECT * FROM gl_trial_balance"))
        if not df.empty:
            return df, "Vantagepoint GL (monthly trial balances)"
    return pd.DataFrame(), ""


def _gl() -> pd.DataFrame | None:
    return query("SELECT * FROM gl_trial_balance") if table_exists("gl_trial_balance") else None


def _prior_hours() -> tuple[pd.DataFrame | None, str]:
    """Last 12 months of billable hours and standard value per person."""
    if table_exists("labor_detail"):
        df = query(
            """
            SELECT employee_number, ANY_VALUE(name_key) AS name_key,
                   SUM(CASE WHEN is_billable THEN hours ELSE 0 END) AS billable_hours,
                   SUM(CASE WHEN is_time_off THEN 0 ELSE hours END) AS total_hours,
                   SUM(CASE WHEN is_billable THEN standard_value ELSE 0 END) AS standard_value
            FROM labor_detail
            WHERE transaction_date > (SELECT MAX(transaction_date) FROM labor_detail) - INTERVAL 12 MONTH
            GROUP BY employee_number
            """
        )
        if not df.empty:
            return df, "labor detail"
    if table_exists("monthly_hours"):
        df = query(
            """
            SELECT name_key, SUM(billable_to_clients) AS billable_hours, SUM(total_hours) AS total_hours,
                   NULL::DOUBLE AS standard_value
            FROM monthly_hours
            WHERE month > (SELECT MAX(month) FROM monthly_hours) - INTERVAL 12 MONTH
            GROUP BY name_key
            """
        )
        if not df.empty:
            return df, "monthly hours workbook (no rates -- enter billing rates by hand)"
    return None, ""


def _default_people(a: bm.Assumptions, drivers: pd.DataFrame) -> pd.DataFrame:
    cost = _latest("employee_cost_rates", "employee_number, full_name, status, labor_type, job_cost_type, job_cost_rate")
    targets = _latest("employee_targets", "*")
    prior, _ = _prior_hours()
    return bm.default_people(cost, targets, prior, a, drivers)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def _init_state(year: int, baseline: pd.DataFrame, force_defaults: bool = False):
    if st.session_state.get(SS + "year") == year and not force_defaults:
        return
    a, people, overhead, drivers = (None, None, None, None) if force_defaults else bm.load_inputs(year)
    a = a or bm.Assumptions(year=year)
    if drivers is None:
        drivers = bm.guess_draw_drivers(_gl())
    if people is None:
        people = _default_people(a, drivers)
    st.session_state[SS + "year"] = year
    st.session_state[SS + "a"] = a
    st.session_state[SS + "people"] = people
    st.session_state[SS + "overhead_saved"] = overhead
    st.session_state[SS + "drivers"] = drivers
    st.session_state[SS + "ver"] = st.session_state.get(SS + "ver", 0) + 1  # resets editors


def _key(name: str) -> str:
    return f"{SS}{name}_{st.session_state.get(SS + 'ver', 0)}"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def render():
    year = config.BUDGET_YEAR
    st.title(f"Budget {year}")
    st.caption(
        "Hybrid budget for calendar "
        f"{year}: fee revenue and salaries come from the people plan; overhead is last year's actuals plus a % "
        "change; owner draws and other big items are budget drivers you enter. Edit any tab, the summary "
        "updates as you go. Click **Save inputs** to keep your changes."
    )

    actuals, actuals_source = _actuals()
    windows = bm.baseline_windows(actuals)

    # ---- Baseline controls ----
    c1, c2 = st.columns([2, 3])
    with c1:
        window = st.selectbox("Prior-year baseline", windows, index=0, key=SS + "window",
                              help="Which 12 months of actuals the overhead lines grow from.") if windows else None
    sheets = None
    if not actuals.empty and actuals["sheet"].nunique() > 1:
        all_sheets = sorted(actuals["sheet"].unique())
        non_consol = sorted(actuals.loc[~actuals["is_consolidated"].astype(bool), "sheet"].unique())
        with c2:
            sheets = st.multiselect(
                "Entities / P&L tabs to include", all_sheets, default=non_consol or all_sheets, key=SS + "sheets",
                help="Consolidated or summary tabs are left out by default so entities aren't counted twice.",
            )
    if actuals.empty:
        st.info(
            "No prior-year actuals yet. Save the firm's P&L workbook (e.g. `Somos P&L 2026.xlsx`) or monthly "
            "Vantagepoint trial balances in the raw data folder and click **Refresh data**. Until then, overhead "
            "is empty and you can still build the people plan and drivers."
        )
    else:
        st.caption(f"Actuals from: **{actuals_source}**.")

    baseline = bm.baseline_lines(actuals, window, sheets)
    _init_state(year, baseline)
    a: bm.Assumptions = st.session_state[SS + "a"]

    tabs = st.tabs(["Summary", "Assumptions", "People plan", "Overhead", "Budget drivers", "Save & export"])

    # ---- Assumptions ----
    with tabs[1]:
        a = _assumptions_tab(a)

    # ---- Drivers (before people, so the owner-draw rule sees current drivers) ----
    with tabs[4]:
        drivers = _drivers_tab()

    # ---- People ----
    with tabs[2]:
        people = _people_tab(a, drivers)

    # ---- Overhead ----
    with tabs[3]:
        overhead = _overhead_tab(a, baseline)

    result = bm.compute(a, people, overhead, drivers)

    with tabs[0]:
        _summary_tab(result, a)

    with tabs[5]:
        _save_export_tab(a, people, overhead, drivers, result, baseline)


def _assumptions_tab(a: bm.Assumptions) -> bm.Assumptions:
    st.subheader("Rates and pay")
    c1, c2, c3 = st.columns(3)
    k = _key("a")
    with c1:
        rate = st.number_input("Billing rate increase %", value=a.rate_increase_pct * 100, step=0.5, key=k + "rate") / 100
        rate_m = st.selectbox("New rates from", bm.MONTH_LABELS, index=a.rate_increase_month - 1, key=k + "ratem")
        real = st.number_input("Default realization %", value=a.realization_pct * 100, step=1.0, key=k + "real",
                               help="Billed / standard value. Used for new people rows; each person can differ.") / 100
    with c2:
        raise_ = st.number_input("Salary increase %", value=a.salary_increase_pct * 100, step=0.5, key=k + "raise") / 100
        raise_m = st.selectbox("Raises from", bm.MONTH_LABELS, index=a.salary_increase_month - 1, key=k + "raisem")
        fringe = st.number_input("Payroll taxes & benefits % of salary", value=a.fringe_pct * 100, step=0.5,
                                 key=k + "fringe",
                                 help="Fringe only. Not the 103.4% loaded burden, which also includes overhead "
                                      "that this budget lists line by line.") / 100
    with c3:
        growth = st.number_input("Default overhead change %", value=a.overhead_growth_pct * 100, step=0.5,
                                 key=k + "growth", help="Starting % for overhead lines. Change any line on the Overhead tab.") / 100

    st.subheader("Seasonality")
    st.caption("Share of the year's billable hours worked in each month. Default is each month's share of Mon-Fri workdays.")
    season = pd.DataFrame({"Month": bm.MONTH_LABELS, "Share %": np.round(np.array(a.seasonality) * 100, 2)})
    edited = st.data_editor(season, hide_index=True, disabled=["Month"], key=_key("season"),
                            column_config={"Share %": st.column_config.NumberColumn(format="%.2f", min_value=0.0)})
    total = edited["Share %"].sum()
    if abs(total - 100) > 0.01:
        st.warning(f"Shares total {total:.2f}%. They're rescaled to 100% in the calculation.")
    if st.button("Reset to workdays", key=_key("season_reset")):
        a.seasonality = bm.workday_weights(a.year)
        st.session_state[SS + "a"] = a
        st.session_state[SS + "ver"] += 1
        st.rerun()

    new = bm.Assumptions(
        year=a.year, rate_increase_pct=rate, rate_increase_month=bm.MONTH_LABELS.index(rate_m) + 1,
        salary_increase_pct=raise_, salary_increase_month=bm.MONTH_LABELS.index(raise_m) + 1,
        fringe_pct=fringe, realization_pct=real, overhead_growth_pct=growth,
        seasonality=list(bm.normalized_weights(edited["Share %"])),
    )
    return new


def _drivers_tab() -> pd.DataFrame:
    st.subheader("Budget drivers")
    st.caption(
        "Big items you set directly. **Owner draws** sit below net income, so the budget shows profit before "
        "and after draws. Name the owner in **Person** and their salary in the people plan is set to $0, so "
        "their pay isn't counted twice (their billable revenue still counts). Basis: *Per month* repeats the "
        "amount each month from start to end; *Per year* spreads it over those months; *One-time* lands in the "
        "start month."
    )
    base = st.session_state[SS + "drivers"]
    edited = st.data_editor(
        base, num_rows="dynamic", hide_index=True, use_container_width=True, key=_key("drivers"),
        column_config={
            "include": st.column_config.CheckboxColumn("Include", default=True),
            "driver": st.column_config.TextColumn("Driver", required=True, help="e.g. Owner draw - Alfred"),
            "section": st.column_config.SelectboxColumn("Section", options=bm.DRIVER_SECTIONS, required=True,
                                                        default="Owner draws"),
            "person": st.column_config.TextColumn("Person", help="Owner's name, as in Vantagepoint (first name is enough)"),
            "amount": st.column_config.NumberColumn("Amount ($)", format="$%,.0f", min_value=0.0),
            "basis": st.column_config.SelectboxColumn("Basis", options=bm.BASES, default="Per month"),
            "start_month": st.column_config.NumberColumn("Start month", min_value=1, max_value=12, default=1, step=1),
            "end_month": st.column_config.NumberColumn("End month", min_value=1, max_value=12, default=12, step=1),
            "note": st.column_config.TextColumn("Note"),
        },
    )
    edited = edited.dropna(subset=["driver"]).reset_index(drop=True)
    if not edited.empty:
        annual = bm.drivers_monthly(edited).sum(axis=1)
        by = pd.DataFrame({"section": edited["section"], "annual": annual}).groupby("section")["annual"].sum()
        st.caption(" · ".join(f"{s}: **{_money_md(v)}**/yr" for s, v in by.items()))
    return edited


def _people_tab(a: bm.Assumptions, drivers: pd.DataFrame) -> pd.DataFrame:
    _, hours_source = _prior_hours()
    st.subheader("People plan")
    st.caption(
        "One row per person: who's on staff, when, pay, billable hours and rate. Prefilled from Vantagepoint "
        f"(cost rates, hour targets{', and the last 12 months of ' + hours_source if hours_source else ''}). "
        "Add a row for each planned hire with a start month. Owners paid by draw show $0 salary."
    )
    base = bm.apply_draw_rule(st.session_state[SS + "people"], drivers)
    edited = st.data_editor(
        base, num_rows="dynamic", hide_index=True, use_container_width=True, key=_key("people"),
        disabled=["prior_billable_hours", "prior_rate"],
        column_config={
            "include": st.column_config.CheckboxColumn("Include", default=True),
            "name": st.column_config.TextColumn("Name", required=True),
            "employee_number": st.column_config.TextColumn("Emp #"),
            "role": st.column_config.TextColumn("Role"),
            "start_month": st.column_config.NumberColumn("Start", min_value=1, max_value=12, default=1, step=1),
            "end_month": st.column_config.NumberColumn("End", min_value=1, max_value=12, default=12, step=1),
            "annual_salary": st.column_config.NumberColumn("Annual salary", format="$%,.0f", min_value=0.0),
            "billable_hours": st.column_config.NumberColumn("Billable hrs", format="%,.0f", min_value=0.0),
            "bill_rate": st.column_config.NumberColumn("Rate $/hr", format="$%,.0f", min_value=0.0),
            "realization_pct": st.column_config.NumberColumn("Realization", format="percent", min_value=0.0,
                                                             max_value=1.5, default=a.realization_pct),
            "prior_billable_hours": st.column_config.NumberColumn("Prior hrs", format="%,.0f"),
            "prior_rate": st.column_config.NumberColumn("Prior rate", format="$%,.0f"),
            "note": st.column_config.TextColumn("Note"),
        },
    )
    edited = edited.dropna(subset=["name"]).reset_index(drop=True)
    edited["realization_pct"] = pd.to_numeric(edited["realization_pct"], errors="coerce").fillna(a.realization_pct)
    edited["include"] = edited["include"].fillna(True)
    missing = edited[edited["include"].astype(bool) & (pd.to_numeric(edited["billable_hours"], errors="coerce") > 0)
                     & (pd.to_numeric(edited["bill_rate"], errors="coerce").fillna(0) == 0)]
    if not missing.empty:
        st.warning(f"{len(missing)} people have billable hours but no rate, so they add no revenue: "
                   + ", ".join(missing["name"].astype(str).head(8)))
    return edited


def _overhead_tab(a: bm.Assumptions, baseline: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Overhead and other P&L lines")
    st.caption(
        f"Each prior-year line, grown by its change %, or a **Fixed amount** if you enter one. "
        f"'{bm.PEOPLE_PLAN}' lines (fee revenue, salaries, payroll taxes, benefits) are replaced by the people "
        f"plan so they aren't counted twice. '{bm.EXCLUDE}' drops a line."
    )
    if baseline.empty:
        st.info("No prior-year lines loaded yet. Load a P&L workbook or GL trial balances to fill this tab.")
        return pd.DataFrame(columns=bm.OVERHEAD_COLUMNS)
    ov = bm.default_overhead(baseline, a, st.session_state.get(SS + "overhead_saved"))
    edited = st.data_editor(
        ov, hide_index=True, use_container_width=True, height=min(36 * (len(ov) + 1) + 3, 800), key=_key("overhead") + str(hash(tuple(ov["line_item"]))),
        disabled=["section", "category", "account_number", "line_item", "prior_amount"],
        column_config={
            "section": "Section", "category": "Category", "account_number": "Account", "line_item": "Line item",
            "treatment": st.column_config.SelectboxColumn("Treatment", options=bm.TREATMENTS, required=True),
            "prior_amount": st.column_config.NumberColumn("Prior year", format="$%,.0f"),
            "growth_pct": st.column_config.NumberColumn("Change %", format="percent", step=0.005),
            "override_amount": st.column_config.NumberColumn("Fixed amount", format="$%,.0f",
                                                             help="Overrides Change % when filled in"),
        },
    )
    budget = bm.overhead_annual(edited)
    replaced = edited.loc[edited["treatment"] == bm.PEOPLE_PLAN, "prior_amount"].sum()
    st.caption(f"Budgeted from prior year: **{_money_md(budget.sum())}**. "
               f"Replaced by the people plan: **{_money_md(replaced)}** of prior-year lines.")
    return edited


def _summary_tab(res: bm.BudgetResult, a: bm.Assumptions):
    k = res.kpis

    def vs(cur, prior):
        if prior is None or pd.isna(prior) or prior == 0:
            return None
        return f"{cur / prior - 1:+.1%} vs prior year"

    kpi_row([
        {"label": "Revenue", "value": fmt_currency(k["revenue"], short=True), "delta": vs(k["revenue"], k["prior_revenue"])},
        {"label": "Expenses", "value": fmt_currency(k["expenses"], short=True)},
        {"label": "Net income before draws", "value": fmt_currency(k["net_income"], short=True),
         "delta": vs(k["net_income"], k["prior_net_income"])},
        {"label": "Owner draws", "value": fmt_currency(k["owner_draws"], short=True)},
        {"label": "Left after draws", "value": fmt_currency(k["after_draws"], short=True),
         "help": "Net income less owner draws. Negative means draws exceed profit."},
    ])
    st.caption(f"{k['headcount']} people in the plan · {k['billable_hours']:,.0f} billable hours · "
               f"net margin {k['net_margin']:.1%}")
    if k["after_draws"] < 0:
        st.warning(f"Owner draws exceed budgeted net income by {_money_md(-k['after_draws'])}.")

    pnl = res.pnl
    get = lambda line: pnl.loc[pnl["line"] == line, bm.MONTH_LABELS].iloc[0].to_numpy()  # noqa: E731
    fig = go.Figure()
    fig.add_bar(x=bm.MONTH_LABELS, y=get("Total revenue"), name="Revenue", marker_color=CATEGORICAL[0])
    fig.add_bar(x=bm.MONTH_LABELS, y=get("Total expenses"), name="Expenses", marker_color=CATEGORICAL[1])
    fig.add_bar(x=bm.MONTH_LABELS, y=get("Total owner draws"), name="Owner draws", marker_color=CATEGORICAL[6])
    fig.add_scatter(x=bm.MONTH_LABELS, y=np.cumsum(get("Remaining after owner draws")), name="Left after draws (cumulative)",
                    mode="lines+markers", line=dict(color=INK_SECONDARY, width=2))
    fig.update_layout(barmode="group", yaxis_tickprefix="$", yaxis_tickformat=",.0s")
    fig = apply_layout(fig, title=f"Monthly budget, {a.year}", height=400)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, xanchor="left"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Budget P&L")
    show = pnl.copy()
    show["Change"] = show["Total"] - show["Prior year"]
    show["Line"] = np.where(show["kind"].isin(["total", "result"]), show["line"], "   " + show["line"])
    show = show[["group", "Line"] + bm.MONTH_LABELS + ["Total", "Prior year", "Change"]]
    money = {c: st.column_config.NumberColumn(c, format="$%,.0f") for c in bm.MONTH_LABELS + ["Total", "Prior year", "Change"]}
    st.dataframe(show, hide_index=True, use_container_width=True, height=min(38 * (len(show) + 1), 900),
                 column_config={"group": "Section", **money})

    if not res.people.empty:
        st.subheader("By person")
        ppl = res.people.sort_values("revenue", ascending=False)
        st.dataframe(ppl, hide_index=True, use_container_width=True, column_config={
            "name": "Name", "role": "Role",
            "billable_hours": st.column_config.NumberColumn("Billable hrs", format="%,.0f"),
            "revenue": st.column_config.NumberColumn("Revenue", format="$%,.0f"),
            "salary_and_fringe": st.column_config.NumberColumn("Salary + fringe", format="$%,.0f"),
            "contribution": st.column_config.NumberColumn("Contribution", format="$%,.0f",
                                                          help="Revenue less salary and fringe (owner draws not included)"),
        })


def _save_export_tab(a, people, overhead, drivers, res: bm.BudgetResult, baseline):
    st.subheader("Save")
    st.caption(f"Saves assumptions, people plan, overhead choices and drivers to "
               f"`{bm.budget_dir(a.year)}` (kept out of git: names and pay). They load automatically next time.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save inputs", type="primary", use_container_width=True):
            path = bm.save_inputs(a, people, overhead, drivers)
            st.session_state[SS + "a"] = a
            st.session_state[SS + "people"] = people
            st.session_state[SS + "overhead_saved"] = overhead
            st.session_state[SS + "drivers"] = drivers
            st.success(f"Saved to {path}")
    with c2:
        if st.button("Start over from Vantagepoint", use_container_width=True,
                     help="Rebuild the people plan, overhead and drivers from the current data. Saved files are "
                          "only replaced when you click Save."):
            _init_state(a.year, baseline, force_defaults=True)
            st.rerun()

    st.subheader("Export")
    from dashboard.budget_excel import to_bytes

    st.download_button(
        "Download Excel budget (live formulas)", data=to_bytes(a, people, overhead, drivers),
        file_name=f"Somos_Budget_{a.year}.xlsx", use_container_width=True,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.caption("Every total in the workbook is a formula, so you can keep editing assumptions, people, overhead "
               "and drivers in Excel. Blue cells are inputs.")
    st.download_button("Download budget P&L (CSV)", data=res.pnl.to_csv(index=False).encode(),
                       file_name=f"Somos_Budget_{a.year}_PnL.csv", mime="text/csv", use_container_width=True)
