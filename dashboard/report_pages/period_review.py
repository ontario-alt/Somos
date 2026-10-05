"""
Measuring Period Review -- a dashboard locked to the most recently
*closed* measuring period (e.g. Oct 1, 2025 - Sep 30, 2026 once FY2027
has begun), for year-end hours review.

  * Upload panel: the Vantagepoint time-detail export for the period is
    uploaded here, checked (columns, date coverage, hours by policy
    category) and loaded -- no folder juggling.
  * Leave & proration: every requirement is prorated for approved leave
    (reference/leave.csv). The panel shows each person's prorated
    requirement, lets leave be added / edited in place, and suggests
    likely leave from the hours data (leave-of-absence time entries,
    multi-week gaps with no hours) for someone to confirm.
  * Hours chart with the 90-100% evaluation window (config.
    EVALUATION_WINDOW) drawn as a defined band, plus a table of the
    timekeepers inside it.
  * The same three policy tests and promotion lookback as the Measuring
    Period page (dashboard/hours_credit.py), data checks, profitability,
    and a downloadable leadership report.

Reuses the Measuring Period page's loaders and sections rather than
duplicating them.
"""
from __future__ import annotations

import datetime
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import config
from dashboard import hours_credit, leadership_report
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.theme import fmt_num, fmt_pct_smart, round_for_display
from dashboard.charts.target_progress import evaluation_window_chart, window_zone
from dashboard.data import query, table_exists
from dashboard.report_pages import measuring_period as mp
from etl.common import name_key


def review_period(today: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
    """The most recently closed measuring period as of today."""
    today = today or config.today()
    current_start, _ = config.fiscal_year_bounds(today)
    return config.fiscal_year_bounds(current_start - datetime.timedelta(days=1))


def render():
    fy_start, fy_end = review_period()
    lo, hi = config.EVALUATION_WINDOW
    st.title(f"Measuring Period Review — FY{fy_end.year}")
    st.caption(f"{fy_start:%B %-d, %Y} – {fy_end:%B %-d, %Y} (closed). Every figure on this page is for this period only.")

    has_data = _has_period_hours(fy_start, fy_end)
    _upload_panel(fy_start, fy_end, expanded=not has_data)
    if not has_data:
        st.info(
            "No hours loaded for this period yet. Upload the Vantagepoint time-detail export above "
            f"({fy_start:%m/%d/%Y} – {fy_end:%m/%d/%Y})."
        )
        return

    sc, source, hours, people = mp._scorecard_for(fy_start, fy_end, fy_end)
    if people is None or sc is None or sc.empty:
        st.warning(
            "Hours are loaded, but no one with an hours requirement matched. Check "
            "`reference/employee_targets.csv` (roles) -- see the README."
        )
        return
    sc = mp._add_promotion_lookback(sc, fy_start)
    excluded, off_chart = _excluded_people(people, hours, fy_start, source)
    sc = sc[~sc["name_key"].isin(off_chart)]
    # Designation (e.g. General Counsel) for distinct shading on the chart.
    desig = people.drop_duplicates("name_key").set_index("name_key")["designation"] if "designation" in people else pd.Series(dtype=str)
    sc = sc.assign(Designation=sc["name_key"].map(desig))
    sc["Zone"] = sc["% of Expectation"].map(lambda v: window_zone(v, lo, hi))
    sc = round_for_display(sc)
    # Departed timekeepers (end_date inside the period) leave the main page
    # and are shown in the appendix at the bottom.
    ends = people.drop_duplicates("name_key").set_index("name_key")["end_date"]
    departed_keys = {k for k, e in ends.items() if pd.notna(e) and pd.Timestamp(e) < pd.Timestamp(fy_end)}
    departed = sc[sc["name_key"].isin(departed_keys)].assign(**{"Last Day": sc["name_key"].map(ends)})
    sc = sc[~sc["name_key"].isin(departed_keys)]
    sc_all, sc = sc, sc[sc["has_hours"]].copy()
    leave = mp._load_leave()
    flagged = _flag_unwindowed(sc, people, source, fy_start)

    _coverage_note(source, fy_start, fy_end)

    # Headline -- provisional (flagged) results aren't counted as met / eligible.
    firm = sc[~sc["Timekeeper"].isin(flagged)]
    zones = firm["Zone"].value_counts()
    kpi_row(
        [
            {"label": "Timekeepers reviewed", "value": f"{len(sc)}",
             "delta": f"{len(flagged)} provisional" if flagged else None, "delta_color": "off",
             "help": "Everyone with an hours requirement and hours in the period (departed timekeepers are in the "
                     "appendix). Provisional (†) results aren't counted in the other boxes."},
            {"label": "Met (100%+)", "value": f"{zones.get('Met (100%+)', 0)}"},
            {"label": f"In {lo:.0f}–{hi:.0f}% window", "value": f"{zones.get('90–100% window', 0)}",
             "help": "Credited hours at 90% to just under 100% of their prorated Hours Expectation."},
            {"label": f"Below {lo:.0f}%", "value": f"{zones.get('Below 90%', 0)}"},
            {"label": "Bonus eligible", "value": f"{int((firm['Bonus Status'] == 'Eligible').sum())}"},
            {"label": "On leave / prorated", "value": f"{int((sc['Leave Days'] > 0).sum())} / {int((sc['Expectation'] < sc['Annual Expectation'] - 0.05).sum())}",
             "help": "People with approved leave in the period / people whose requirement is prorated for leave or a mid-period start or end."},
        ]
    )

    role_opts = [r for r in [*config.BILLABLE_HOUR_TARGETS, "Custom"] if r in set(sc["Role"])]
    roles = st.multiselect("Role", role_opts, default=role_opts, format_func=_role_label)
    view = sc[sc["Role"].isin(roles)]
    if view.empty:
        st.info("No timekeepers match the selected roles.")
        return

    st.subheader("Hours vs. prorated Hours Expectation")
    st.plotly_chart(evaluation_window_chart(view, lo, hi, flagged=flagged), use_container_width=True,
                    config={"displayModeBar": False})
    st.caption(
        f"Each bar is credited hours (client + Firm's Own Account + pro bono + creditable non-billable "
        f"up to the {config.CREDITABLE_NB_CAP}-hour cap) as a % of the person's Hours Expectation "
        f"prorated for approved leave and partial-year employment. The shaded band marks the "
        f"{lo:.0f}–{hi:.0f}% evaluation window. Violet bars mark a designated role (e.g. General Counsel)."
        + (f" † {', '.join(sorted(flagged))}: requirement prorated from a mid-period start, but the summary "
           "export's full-year hours include time before that date (e.g. as a contractor), so this reads high "
           "-- the time-detail export fixes it." if flagged else "")
    )

    _window_table(view, lo, hi)
    _leave_panel(sc_all, people, leave, fy_start, fy_end)
    _excluded_summary(excluded)
    _scorecard_tabs(view, roles)

    notes = _report_notes(source, sc, leave, flagged)
    d1, d2 = st.columns(2)
    window = view[view["Zone"] == "90–100% window"].sort_values("% of Expectation", ascending=False)
    window_html = ""
    if not window.empty:
        w = window.assign(**{"Hours Short of 100%": window["Expectation"] - window["Credited Hours"]})
        window_html = f"<h2>In the {lo:.0f}–{hi:.0f}% window ({len(window)})</h2>" + leadership_report.table_html(w, [
            ("Timekeeper", "txt"), ("Expectation", "hrs"), ("Billable Needed", "hrs"), ("Leave Days", "hrs"),
            ("Credited Hours", "hrs"), ("% of Expectation", "pct"), ("Hours Short of 100%", "hrs"),
            ("Bonus Status", "txt"), ("2-yr Avg %", "pct"), ("Promotion Lookback", "txt")])
    d1.download_button(
        "Download leadership report (HTML)",
        leadership_report.build_html(
            view, fy_start, fy_end, fy_end, mp._SOURCE_LABELS.get(source, source), notes,
            chart_fig=evaluation_window_chart(view, lo, hi, flagged=flagged),
            chart_title=f"Hours vs. prorated Hours Expectation — {lo:.0f}–{hi:.0f}% evaluation window",
            extra_html=window_html, appendix_html=_appendix_html(departed),
            provisional=flagged, show_pro_bono=(source == "labor_detail"),
        ).encode(),
        file_name=f"Measuring_Period_Review_FY{fy_end.year}.html",
        mime="text/html",
        use_container_width=True,
    )
    d2.download_button(
        "Download scorecard (CSV)",
        view.drop(columns=["name_key", "has_hours"]).to_csv(index=False).encode(),
        file_name=f"measuring_period_review_FY{fy_end.year}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    _individual_breakdown(view, people, leave, source, fy_start, fy_end)
    # Excluded groups are summarized above -- not repeated as "no requirement".
    mp._hours_data_quality(sc_all, hours[~hours["name_key"].isin(off_chart)], people, leave, source, fy_start, fy_end)
    if source == "labor_detail":
        mp._classification_review(fy_start, fy_end)

    st.divider()
    mp._section_timekeeper_profitability(fy_start, fy_end, fy_end)
    _appendix(departed, fy_start, fy_end)


_APPENDIX_COLS = ["Timekeeper", "Role", "Last Day", "Annual Expectation", "Expectation", "Billable Needed",
                  "Client", "Credited Hours", "% of Expectation", "Bonus Status"]


def _departed_view(departed: pd.DataFrame) -> pd.DataFrame:
    d = departed.copy()
    d["Role"] = d["Role"].map(_role_label)
    d["Last Day"] = pd.to_datetime(d["Last Day"]).dt.strftime("%m/%d/%Y")
    for c in ("Client", "Credited Hours", "% of Expectation"):
        d[c] = d[c].where(d["has_hours"])
    d["Bonus Status"] = d["Bonus Status"].where(d["has_hours"], "No hours in export")
    return d.sort_values("Timekeeper")[_APPENDIX_COLS]


def _appendix(departed: pd.DataFrame, fy_start, fy_end):
    if departed.empty:
        return
    st.divider()
    st.subheader(f"Appendix — Departed timekeepers ({len(departed)})")
    st.caption(
        "Left during the measuring period, so kept off the main page. Requirements are prorated to their last "
        "day (workdays employed ÷ workdays in the period)."
        + (" Anyone showing 'No hours in export' needs the Vantagepoint report re-run with terminated / inactive "
           "employees included." if (~departed["has_hours"]).any() else ""))
    out = _departed_view(departed).rename(columns={"Expectation": "Prorated Expectation", "Client": "Billable"})
    # Text with a dash where there are no hours (a NumberColumn would print "None").
    for c in ("Annual Expectation", "Prorated Expectation", "Billable Needed", "Billable", "Credited Hours"):
        out[c] = out[c].map(fmt_num)
    out["% of Expectation"] = out["% of Expectation"].map(fmt_pct_smart)
    st.dataframe(out, use_container_width=True, hide_index=True)


def _appendix_html(departed: pd.DataFrame) -> str:
    if departed.empty:
        return ""
    out = _departed_view(departed).rename(columns={"Expectation": "Prorated Expectation", "Client": "Billable"})
    return (f"<h2>Appendix — Departed timekeepers ({len(out)})</h2>"
            "<p class='method'>Left during the measuring period; requirements prorated to their last day.</p>"
            + leadership_report.table_html(out, [
                ("Timekeeper", "txt"), ("Role", "txt"), ("Last Day", "txt"), ("Annual Expectation", "hrs"),
                ("Prorated Expectation", "hrs"), ("Billable Needed", "hrs"), ("Billable", "hrs"),
                ("Credited Hours", "hrs"), ("% of Expectation", "pct"), ("Bonus Status", "txt")]))


def _flag_unwindowed(sc, people, source, fy_start) -> set:
    """Names whose requirement is prorated from a mid-period start date while
    the hours source (the summary export) can't drop hours before it."""
    if source != "timekeeper_hours":
        return set()
    starts = people.drop_duplicates("name_key").set_index("name_key")["start_date"]
    keys = {k for k, s_ in starts.items() if pd.notna(s_) and pd.Timestamp(s_) > pd.Timestamp(fy_start)}
    return set(sc.loc[sc["name_key"].isin(keys), "Timekeeper"])


def _individual_breakdown(view, people, leave, source, fy_start, fy_end):
    """Per-person hours breakdown: KPIs, pie charts, requirement bullets,
    position among peers, monthly charts (when the source has dates), and
    a downloadable one-page profile."""
    from dashboard.charts.person_breakdown import (
        credited_donut, hours_donut, monthly_stack, peer_strip, requirement_bullets)
    from dashboard.charts.target_progress import cumulative_vs_target

    st.subheader("Individual breakdown")
    names = view.sort_values("Timekeeper")["Timekeeper"].tolist()
    name = st.selectbox("Timekeeper", names, key="period_review_person")
    row = view[view["Timekeeper"] == name].iloc[0]
    role_label = _role_label(row["Role"])
    st.caption(f"{role_label} · {row['Zone']}")

    pto, hol = _pto_holiday(row, source, fy_start)
    total_all = float(hours_credit_total(row))
    pto_pct = pto / total_all * 100 if total_all else float("nan")

    c = st.columns(7)
    c[0].metric("Credited hours", f"{fmt_num(row['Credited Hours'])}")
    c[1].metric("Prorated expectation", f"{fmt_num(row['Expectation'])}",
                help=f"Annual {row['Annual Expectation']:,.0f}, prorated for {fmt_num(row['Leave Days'])} leave days / "
                     f"employment dates. Billable needed if the full {fmt_num(row['Creditable Cap'])}-hour creditable "
                     f"allowance is used: {fmt_num(row['Billable Needed'])}")
    c[2].metric("% of expectation", f"{fmt_pct_smart(row['% of Expectation'])}",
                delta=f"{row['Credited Hours'] - row['Expectation']:+,.1f} hrs", delta_color="normal")
    c[3].metric("Total activity", "—" if pd.isna(row["Total Hours"]) else f"{row['Total Hours']:,.0f}",
                help="All chargeable + non-chargeable hours, excluding PTO/holiday")
    c[4].metric("Bonus", row["Bonus Status"] or "—")
    c[5].metric("2-yr average", "—" if pd.isna(row.get("2-yr Avg %")) else fmt_pct_smart(row["2-yr Avg %"]),
                help=str(row.get("Promotion Lookback") or ""))
    c[6].metric("PTO % of hours", fmt_pct_smart(pto_pct),
                help=(f"{fmt_num(pto)} PTO hours of {fmt_num(total_all)} total hours"
                      + (f"; holidays {fmt_num(hol)} more ({fmt_pct_smart(hol / total_all * 100)})" if hol is not None else
                         " (includes holidays and sick time -- this source doesn't separate them)")))

    st.caption(
        f"Billable {fmt_num(row['Client'] + row['FOA'])} of {fmt_num(row['Billable Needed'])} needed "
        f"({fmt_pct_smart((row['Client'] + row['FOA']) / row['Billable Needed'] * 100)}) -- the prorated expectation less the "
        f"full {fmt_num(row['Creditable Cap'])}-hour creditable allowance."
        if row["Billable Needed"] > 0 else "")

    figs = [hours_donut(row), credited_donut(row), requirement_bullets(row, config.EVALUATION_WINDOW[0]),
            peer_strip(view[view["Role"] == row["Role"]], name, role_label)]
    a, b = st.columns(2)
    a.plotly_chart(figs[0], use_container_width=True, config={"displayModeBar": False})
    b.plotly_chart(figs[1], use_container_width=True, config={"displayModeBar": False})
    a, b = st.columns(2)
    a.plotly_chart(figs[2], use_container_width=True, config={"displayModeBar": False})
    b.plotly_chart(figs[3], use_container_width=True, config={"displayModeBar": False})

    if source in ("labor_detail", "monthly_hours"):
        monthly = mp._load_monthly(source, row["name_key"], fy_start, fy_end)
        if not monthly.empty:
            person = people[people["name_key"] == row["name_key"]].iloc[0]
            pace = hours_credit.cumulative_pace(monthly, person, row, leave, fy_start, fy_end)
            m1, m2 = monthly_stack(monthly), cumulative_vs_target(pace, name)
            a, b = st.columns(2)
            a.plotly_chart(m1, use_container_width=True, config={"displayModeBar": False})
            b.plotly_chart(m2, use_container_width=True, config={"displayModeBar": False})
            figs += [m1, m2]
    else:
        st.caption("Monthly charts need the Vantagepoint time-detail export (the summary export has full-year totals only).")

    time_off_rows = ([("PTO", pto, "No"), ("Holiday", hol, "No")] if hol is not None
                     else [("PTO / holiday / sick", row["Time Off"], "No")])
    detail = pd.DataFrame(
        [("Client (billable)", row["Client"], "Yes"), ("Firm's Own Account", row["FOA"], "Yes"),
         ("Pro bono", row["Pro Bono"], "Yes"),
         ("Creditable non-billable — counted", row["Creditable NB (counted)"], f"Yes (cap {fmt_num(row['Creditable Cap'])})"),
         ("Creditable non-billable — over cap", row["Creditable NB (over cap)"], "No"),
         ("Other non-billable", row["Other NB"], "Total activity only"), *time_off_rows],
        columns=["Category", "Hours", "Counts toward expectation"])
    detail["% of Total Hours"] = (detail["Hours"] / total_all * 100).round(1) if total_all else float("nan")
    detail = pd.concat([detail, pd.DataFrame([{"Category": "Total hours", "Hours": total_all,
                                               "Counts toward expectation": "", "% of Total Hours": 100.0}])],
                       ignore_index=True)
    detail["Hours"] = detail["Hours"].astype(float).round(1)
    st.dataframe(detail[["Category", "Hours", "% of Total Hours", "Counts toward expectation"]],
                 use_container_width=True, hide_index=True,
                 column_config={"Hours": st.column_config.NumberColumn(format="localized"),
                                "% of Total Hours": st.column_config.NumberColumn(format="%g%%")})

    p_leave = leave[leave["name_key"] == row["name_key"]] if not leave.empty else leave
    notes = []
    if not p_leave.empty:
        notes.append("Approved leave: " + "; ".join(hours_credit.describe_leave(r) for r in p_leave.itertuples()))
    if source != "labor_detail":
        notes.append(f"Source: {mp._SOURCE_LABELS.get(source, source)} -- pro bono is not separated from other credited time.")
    st.download_button(
        f"Download {name}'s breakdown (HTML)",
        leadership_report.person_profile_html(
            row, figs, fy_start, fy_end, role_label, notes,
            extra_kpis=[("PTO % of hours", fmt_pct_smart(pto_pct))],
            extra_detail=[("PTO hours", pto)] + ([("Holiday hours", hol)] if hol is not None else []),
        ).encode(),
        file_name=f"Hours_Breakdown_{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')}_FY{fy_end.year}.html",
        mime="text/html",
    )


def hours_credit_total(row) -> float:
    """All hours in the period, PTO / holiday included."""
    return sum(float(row.get(c) or 0) for c in
               ("Client", "FOA", "Pro Bono", "Creditable NB (logged)", "Other NB", "Time Off"))


def _pto_holiday(row, source, fy_start) -> tuple[float, float | None]:
    """(PTO hours, holiday hours) -- separately when the source reports them
    (the All Timekeepers Hours export does); otherwise (all time off, None)."""
    if source == "timekeeper_hours":
        raw = mp._timekeeper_hours_rows(fy_start)
        r = raw[raw["name_key"] == row["name_key"]]
        if not r.empty:
            return float(r["pto_hours"].fillna(0).sum()), float(r["hol_hours"].fillna(0).sum())
    return float(row.get("Time Off") or 0), None


def _role_label(r: str) -> str:
    return config.ROLE_LABELS.get(r, config.ROLE_LABELS["Custom"])


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
_REPORT_HELP = """
**Which Vantagepoint report:** a *time-detail* report with **one row per time entry**. Depending
on how your Vantagepoint is set up it may be called *Labor Detail* or *Time Analysis*, or your
admin can save a timesheet search. Run it for **all employees**, **{start} – {end}**, at detail
level (not summarized), and export to **Excel (.xlsx) or CSV**.

| Needed | Columns |
|---|---|
| Required | Employee Name, Transaction (work) Date, Hours, Project Number, Project Name, Billing Status (or Billable Y/N) |
| Recommended | Employee Number, Labor Code, Company |
| For profitability | Billing Extension, Billed Amount, Cost Extension |

Project name and labor code decide each entry's category (client, pro bono, creditable,
other non-billable, PTO / leave). Header names are matched loosely.
"""


def _has_period_hours(fy_start, fy_end) -> bool:
    return mp._hours_source(fy_start, fy_end) != "none"


def _upload_panel(fy_start, fy_end, expanded: bool):
    with st.expander("Upload hours from Vantagepoint", expanded=expanded):
        st.markdown(_REPORT_HELP.format(start=f"{fy_start:%m/%d/%Y}", end=f"{fy_end:%m/%d/%Y}"))
        up = st.file_uploader("Time-detail export (.xlsx / .csv), or the All Timekeepers Hours summary (.csv)",
                              type=["xlsx", "csv"], key="period_review_upload")
        if up is None:
            return
        from etl import parse_labor_detail

        suffix = Path(up.name).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(up.getbuffer())
            tmp_path = Path(tmp.name)
        if suffix == ".csv" and _is_hours_summary(tmp_path):
            _summary_upload(tmp_path, up.name, fy_start, fy_end)
            return
        rows = parse_labor_detail._parse_one(tmp_path)
        if not rows:
            st.error(
                "Couldn't read time entries from this file -- it needs a header row with at least "
                "Employee Name, a work date, and Hours, and one row per time entry. Check it's the "
                "detail (not summary) version of the report."
            )
            tmp_path.unlink(missing_ok=True)
            return
        df = pd.DataFrame(rows)
        dates = pd.to_datetime(df["transaction_date"])
        in_period = df[(dates >= pd.Timestamp(fy_start)) & (dates <= pd.Timestamp(fy_end))]
        c = st.columns(4)
        c[0].metric("Time entries", f"{len(df):,}")
        c[1].metric("Timekeepers", f"{df['name_key'].nunique()}")
        c[2].metric("Dates covered", f"{dates.min():%m/%d/%y} – {dates.max():%m/%d/%y}")
        c[3].metric("Hours in period", f"{in_period['hours'].sum():,.0f}")
        cat = in_period.groupby("hours_category")["hours"].sum().reindex(
            ["client", "foa", "pro_bono", "creditable", "other", "time_off"]).fillna(0)
        labels = {"client": "Client (billable)", **mp._CATEGORY_LABELS}
        st.caption("Hours by category: " + " · ".join(f"{labels[k]}: {v:,.0f}" for k, v in cat.items()))
        if len(in_period) < len(df):
            st.warning(f"{len(df) - len(in_period):,} entries fall outside {fy_start:%m/%d/%Y} – {fy_end:%m/%d/%Y} and will be ignored on this page.")
        if dates.max() < pd.Timestamp(fy_end) - pd.Timedelta(days=7) or dates.min() > pd.Timestamp(fy_start) + pd.Timedelta(days=7):
            st.warning("This file doesn't cover the whole measuring period -- results will be incomplete.")
        if st.button("Load into dashboard", type="primary"):
            config.RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
            dest = config.RAW_DATA_DIR / f"Labor_Detail_FY{fy_end.year}_upload_{datetime.datetime.now():%Y%m%d_%H%M%S}{suffix}"
            shutil.copyfile(tmp_path, dest)
            tmp_path.unlink(missing_ok=True)
            _rebuild(f"Loaded {up.name} -> {dest.name}")


def _is_hours_summary(path: Path) -> bool:
    """The 'All Timekeepers Hours' summary export (one row per person per
    company, period in the column headers) rather than a time-detail export."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        header = f.readline().lower()
    return "employee name" in header and "billable hours" in header and "credited hours" in header


def _summary_upload(tmp_path: Path, original_name: str, fy_start, fy_end):
    from etl import parse_timekeeper_hours

    rows = parse_timekeeper_hours._parse_one(tmp_path)
    if not rows:
        st.error("Couldn't read any timekeeper rows from this All Timekeepers Hours export.")
        return
    df = pd.DataFrame(rows)
    p_start, p_end = rows[0]["period_start"], rows[0]["period_end"]
    st.info(
        "This is the **All Timekeepers Hours** summary (one total per person per company). It works for "
        "the year-end scorecard, but it can't separate pro bono from other credited time or show "
        "month-by-month detail -- the time-detail export can.", icon="ℹ️")
    c = st.columns(4)
    c[0].metric("Timekeepers", f"{df['employee_name'].nunique()}")
    c[1].metric("Companies", f"{df['entity'].nunique()}")
    c[2].metric("Period in file", f"{p_start:%m/%d/%y} – {p_end:%m/%d/%y}")
    good = df[~df["data_error"]]
    c[3].metric("Billable hours", f"{good['billable_hours'].sum():,.0f}")
    bad = df[df["data_error"]]
    if not bad.empty:
        st.warning(
            "Negative hours -- a bad timesheet entry or adjustment in Vantagepoint. These rows are excluded; "
            "fix them at the source and re-export: "
            + ", ".join(f"{r.employee_name} ({r.entity}: {fmt_num(r.total_hours)} total)" for r in bad.itertuples()))
    if (p_start, p_end) != (fy_start, fy_end):
        st.error(f"This export covers {p_start:%m/%d/%Y} – {p_end:%m/%d/%Y}, not this page's period "
                 f"({fy_start:%m/%d/%Y} – {fy_end:%m/%d/%Y}). Re-run it for the right dates.")
        return
    if st.button("Load into dashboard", type="primary"):
        config.RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.RAW_DATA_DIR / f"All_Timekeepers_Hours_FY{fy_end.year}_upload_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
        shutil.copyfile(tmp_path, dest)
        tmp_path.unlink(missing_ok=True)
        _rebuild(f"Loaded {original_name} -> {dest.name}")


def _rebuild(message: str):
    from dashboard.data import release_connection
    from etl.build_warehouse import build

    with st.spinner("Rebuilding..."):
        release_connection()
        build()
    st.cache_data.clear()
    st.cache_resource.clear()
    st.success(message)
    st.rerun()


def _coverage_note(source, fy_start, fy_end):
    if source == "labor_detail":
        lo_d, hi_d = query(
            "SELECT MIN(transaction_date) AS lo, MAX(transaction_date) AS hi FROM labor_detail "
            "WHERE transaction_date BETWEEN ? AND ?", [fy_start, fy_end]).iloc[0]
        if pd.Timestamp(hi_d) < pd.Timestamp(fy_end) - pd.Timedelta(days=7):
            st.warning(f"Hours loaded only run through {pd.Timestamp(hi_d):%m/%d/%Y} -- upload a full-period export for final results.")
    else:
        st.warning(
            f"Hours for this period come from {mp._SOURCE_LABELS.get(source, source)}, not a Vantagepoint "
            "time-detail export -- pro bono / creditable time may be missing or approximated. Upload the "
            "time-detail export above for exact figures."
        )


# ---------------------------------------------------------------------------
# Excluded groups (Administrative, Somos MX): off the chart, summarized
# ---------------------------------------------------------------------------
def _person_hours(people, hours, fy_start, source) -> pd.DataFrame:
    """Per person-and-entity hours (total, billable, credited, other, time off)."""
    if source == "timekeeper_hours":
        raw = mp._timekeeper_hours_rows(fy_start)
        return raw.rename(columns={"billable_hours": "billable", "credited_hours": "credited",
                                   "other_hours": "other", "time_off_hours": "time_off"})[
            ["name_key", "employee_name", "entity", "billable", "credited", "other", "time_off"]]
    h = hours.copy()
    h["billable"] = h["client_hours"] + h["foa_hours"]
    h["credited"] = h["pro_bono_hours"] + h["creditable_hours"]
    h = h.rename(columns={"other_hours": "other", "time_off_hours": "time_off", "entities": "entity"})
    return h[["name_key", "employee_name", "entity", "billable", "credited", "other", "time_off"]]


def _excluded_people(people, hours, fy_start, source) -> tuple[pd.DataFrame, set]:
    """(rows to summarize, people to keep off the chart). A row (person x
    entity) belongs to every excluded group that applies: each of the
    person's staff_group values (several allowed, separated by ';') listed
    in config.REVIEW_EXCLUDED_STAFF_GROUPS, plus the group for its entity in
    config.REVIEW_EXCLUDED_ENTITIES -- so someone who is both Somos MX and
    Administrative is counted in both summaries. A person leaves the chart
    only if all of their hours fall in excluded rows."""
    ph = _person_hours(people, hours, fy_start, source)
    groups = people.set_index("name_key")["staff_group"] if "staff_group" in people else pd.Series(dtype=str)

    def groups_for(r) -> list[str]:
        out = []
        g = groups.get(r["name_key"]) if r["name_key"] in groups.index else None
        for part in re.split(r"[;,]", g) if isinstance(g, str) else []:
            label = config.REVIEW_EXCLUDED_STAFF_GROUPS.get(part.strip())
            if label and label not in out:
                out.append(label)
        for ent, label in config.REVIEW_EXCLUDED_ENTITIES.items():
            if ent in str(r["entity"] or "") and label not in out:
                out.append(label)
        return out

    ph["groups"] = ph.apply(groups_for, axis=1)
    all_excluded = ph.groupby("name_key")["groups"].apply(lambda g: all(len(x) > 0 for x in g))
    ex = ph[ph["groups"].map(len) > 0].explode("groups").rename(columns={"groups": "group"})
    return ex.drop_duplicates(subset=["name_key", "entity", "group"]), set(all_excluded[all_excluded].index)


def _excluded_summary(ex: pd.DataFrame):
    if ex.empty:
        return
    ex = ex.assign(activity=ex["billable"] + ex["credited"] + ex["other"])
    agg = ex.groupby("group").agg(
        people=("name_key", "nunique"), activity=("activity", "sum"), billable=("billable", "sum"),
        credited=("credited", "sum"), other=("other", "sum"), time_off=("time_off", "sum"),
    ).reset_index()
    agg["avg"] = agg["activity"] / agg["people"]
    agg["billable_pct"] = agg["billable"] / agg["activity"].where(agg["activity"] > 0) * 100
    agg, ex = round_for_display(agg), round_for_display(ex)
    labels = " and ".join(agg["group"])
    with st.expander(f"Excluded from the chart — {labels} (aggregate review)", expanded=False):
        both = ex.groupby("name_key")["group"].nunique()
        both_names = sorted(ex[ex["name_key"].isin(both[both > 1].index)]["employee_name"].unique())
        overlap = ""
        if both_names:
            one = len(both_names) == 1
            overlap = (f" {', '.join(both_names)} {'belongs' if one else 'belong'} to more than one group and "
                       f"{'is' if one else 'are'} counted in each, so the group totals overlap.")
        st.caption(
            "These staff have no hourly requirement and are kept off the chart above, but their hours are "
            "summarized here for review. Activity = billable + credited + other non-billable (PTO and "
            "holidays shown separately)." + overlap
        )
        h = st.column_config.NumberColumn(format="localized")
        st.dataframe(
            agg.rename(columns={"group": "Group", "people": "People", "activity": "Activity Hours",
                                "billable": "Billable", "credited": "Credited", "other": "Other Non-billable",
                                "time_off": "PTO + Holiday", "avg": "Avg Activity / Person",
                                "billable_pct": "Billable %"}),
            use_container_width=True, hide_index=True,
            column_config={c: h for c in ["Activity Hours", "Billable", "Credited", "Other Non-billable",
                                          "PTO + Holiday", "Avg Activity / Person"]}
                          | {"Billable %": st.column_config.NumberColumn(format="%g%%")},
        )
        st.markdown("**By person**")
        st.dataframe(
            ex.sort_values(["group", "employee_name"])[
                ["group", "employee_name", "entity", "activity", "billable", "credited", "other", "time_off"]]
            .rename(columns={"group": "Group", "employee_name": "Name", "entity": "Company",
                             "activity": "Activity Hours", "billable": "Billable", "credited": "Credited",
                             "other": "Other Non-billable", "time_off": "PTO + Holiday"}),
            use_container_width=True, hide_index=True,
            column_config={c: h for c in ["Activity Hours", "Billable", "Credited", "Other Non-billable", "PTO + Holiday"]},
        )


# ---------------------------------------------------------------------------
# 90-100% window
# ---------------------------------------------------------------------------
def _window_table(view, lo, hi):
    w = view[view["Zone"] == "90–100% window"].copy()
    st.markdown(f"**In the {lo:.0f}–{hi:.0f}% window ({len(w)})**")
    if w.empty:
        st.caption("No one finished the period inside the window.")
        return
    w["Hours Short of 100%"] = w["Expectation"] - w["Credited Hours"]
    w["Role"] = w["Role"].map(_role_label)
    cols = ["Timekeeper", "Role", "Annual Expectation", "Leave Days", "Expectation", "Billable Needed", "Client",
            "Credited Hours", "% of Expectation", "Hours Short of 100%", "Pro Bono", "Creditable NB (counted)",
            "Bonus Status", "Prior Period %", "2-yr Avg %", "Promotion Lookback"]
    out = w.sort_values("% of Expectation", ascending=False)[cols]
    for c in ("Prior Period %", "2-yr Avg %"):
        out[c] = out[c].map(lambda v: "—" if pd.isna(v) else fmt_pct_smart(v))
    h1 = st.column_config.NumberColumn(format="localized")
    st.dataframe(
        out, use_container_width=True, hide_index=True,
        column_config={
            "Annual Expectation": st.column_config.NumberColumn(format="localized"),
            "Leave Days": st.column_config.NumberColumn(format="localized", help="Workdays of approved leave (weighted by percent away)"),
            "Expectation": st.column_config.NumberColumn(format="localized", help="Prorated for leave / partial-year employment"),
            "Billable Needed": st.column_config.NumberColumn(format="localized", help="Prorated expectation less the full prorated creditable allowance -- billable hours needed, e.g. (1,600 - 75) x 46/52 = 1,349"),
            "Client": st.column_config.NumberColumn("Billable", format="localized"),
            "Credited Hours": h1, "Pro Bono": h1, "Creditable NB (counted)": h1,
            "% of Expectation": st.column_config.NumberColumn(format="%g%%"),
            "Hours Short of 100%": st.column_config.NumberColumn(format="localized"),
        },
    )


# ---------------------------------------------------------------------------
# Leave & proration
# ---------------------------------------------------------------------------
_LEAVE_COLS = ["full_name", "employee_number", "leave_start", "leave_end", "leave_weeks", "measuring_period",
               "percent_away", "leave_type", "note"]


def _leave_panel(sc_all, people, leave, fy_start, fy_end):
    sugg = _suggest_leave(sc_all, people, leave, fy_start, fy_end)
    n_prorated = int((sc_all["Expectation"] < sc_all["Annual Expectation"] - 0.05).sum())
    label = f"Leave & proration ({int((sc_all['Leave Days'] > 0).sum())} on leave · {n_prorated} prorated"
    label += f" · {len(sugg)} possible leave to review)" if len(sugg) else ")"
    with st.expander(label, expanded=bool(len(sugg))):
        st.caption(
            "Requirements (and the 75-hour creditable cap) are prorated by available workdays: annual × "
            "(workdays employed − approved leave days) ÷ workdays in the period. A 50% reduced schedule "
            "counts as half a day out. Ordinary PTO, sick days and holidays do **not** prorate."
        )
        pr = sc_all[(sc_all["Expectation"] < sc_all["Annual Expectation"] - 0.05) | (sc_all["Leave Days"] > 0)]
        if not pr.empty:
            st.markdown("**Prorated requirements**")
            st.dataframe(
                pr[["Timekeeper", "Annual Expectation", "Leave Days", "Expectation", "Credited Hours", "% of Expectation"]]
                .rename(columns={"Expectation": "Prorated Expectation"}),
                use_container_width=True, hide_index=True,
                column_config={
                    "Annual Expectation": st.column_config.NumberColumn(format="localized"),
                    "Leave Days": st.column_config.NumberColumn(format="localized"),
                    "Prorated Expectation": st.column_config.NumberColumn(format="localized"),
                    "Credited Hours": st.column_config.NumberColumn(format="localized"),
                    "% of Expectation": st.column_config.NumberColumn(format="%g%%"),
                },
            )
            st.caption("Prorated for a mid-period start/end date (employee_targets.csv) and/or approved leave below.")

        st.markdown("**Approved leave this period** — edit, add rows, then *Save leave*.")
        names = sorted(people.loc[people["name_key"].isin(sc_all["name_key"]), "full_name"].dropna().unique())
        current = _read_leave_csv()
        in_period = current[_overlaps(current, fy_start, fy_end)]
        if len(sugg):
            st.markdown(f"**Possible leave found in the hours data ({len(sugg)})** — tick the ones that were approved leave; they're added to the table below.")
            picked = st.data_editor(
                sugg.assign(add=False)[["add", "full_name", "leave_start", "leave_end", "percent_away", "leave_type", "evidence"]],
                key="leave_suggestions", hide_index=True, use_container_width=True, disabled=["full_name", "evidence"],
                column_config={
                    "add": st.column_config.CheckboxColumn("Add", width="small"),
                    "full_name": "Timekeeper",
                    "leave_start": st.column_config.DateColumn("Start", format="MM/DD/YYYY"),
                    "leave_end": st.column_config.DateColumn("End", format="MM/DD/YYYY"),
                    "percent_away": st.column_config.NumberColumn("% away", min_value=0, max_value=100, step=5),
                    "leave_type": "Type", "evidence": "Why it's suggested",
                },
            )
            chosen = picked[picked["add"]].drop(columns=["add", "evidence"])
            if not chosen.empty:
                in_period = pd.concat([in_period, chosen.assign(employee_number="", note="Confirmed from hours data")],
                                      ignore_index=True)
        edited = st.data_editor(
            in_period[_LEAVE_COLS], key="leave_editor", num_rows="dynamic", hide_index=True, use_container_width=True,
            column_config={
                "full_name": st.column_config.SelectboxColumn("Timekeeper", options=names, required=True),
                "employee_number": "Emp #",
                "leave_start": st.column_config.DateColumn("Start", format="MM/DD/YYYY"),
                "leave_end": st.column_config.DateColumn("End (blank = still out)", format="MM/DD/YYYY"),
                "leave_weeks": st.column_config.NumberColumn(
                    "Weeks (if no dates)", min_value=0, step=0.5,
                    help="When only the length is known, e.g. 6 weeks -- leave Start blank. Takes weeks x 5 workdays off."),
                "measuring_period": st.column_config.TextColumn(
                    "Period", help=f"For undated leave: the measuring period, e.g. FY{fy_end.year}"),
                "percent_away": st.column_config.NumberColumn("% away", min_value=0, max_value=100, step=5, default=100),
                "leave_type": st.column_config.SelectboxColumn(
                    "Type", options=["Parental", "Medical", "Family", "Military", "Sabbatical", "Reduced schedule", "Other"]),
                "note": "Note",
            },
        )
        if st.button("Save leave and recalculate"):
            outside = current[~_overlaps(current, fy_start, fy_end)]
            keep = edited.dropna(subset=["full_name"])
            keep = keep[keep["leave_start"].notna() | keep["leave_weeks"].notna()].copy()
            keep.loc[keep["leave_start"].isna(), "measuring_period"] = f"FY{fy_end.year}"
            _write_leave_csv(pd.concat([outside, keep], ignore_index=True))
            _rebuild("Leave saved -- requirements recalculated.")


def _read_leave_csv() -> pd.DataFrame:
    path = config.LEAVE_PATH
    if not path.exists():
        return pd.DataFrame(columns=_LEAVE_COLS)
    df = pd.read_csv(path, dtype=str).reindex(columns=_LEAVE_COLS)
    for c in ("leave_start", "leave_end"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df["percent_away"] = pd.to_numeric(df["percent_away"], errors="coerce").fillna(100.0)
    df["leave_weeks"] = pd.to_numeric(df["leave_weeks"], errors="coerce")
    return df


def _write_leave_csv(df: pd.DataFrame):
    out = df.reindex(columns=_LEAVE_COLS).copy()
    for c in ("leave_start", "leave_end"):
        out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%m/%d/%Y").fillna("")
    out["percent_away"] = pd.to_numeric(out["percent_away"], errors="coerce").fillna(100).map(lambda v: f"{v:g}")
    out["leave_weeks"] = pd.to_numeric(out["leave_weeks"], errors="coerce").map(lambda v: "" if pd.isna(v) else f"{v:g}")
    config.LEAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.fillna("").to_csv(config.LEAVE_PATH, index=False)


def _overlaps(df, fy_start, fy_end) -> pd.Series:
    """Rows that belong to this period: dated leave overlapping it, or
    undated leave (leave_weeks) tagged with this measuring period."""
    if df.empty:
        return pd.Series(dtype=bool)
    s = pd.to_datetime(df["leave_start"], errors="coerce")
    e = pd.to_datetime(df["leave_end"], errors="coerce").fillna(pd.Timestamp.max)
    dated = (s <= pd.Timestamp(fy_end)) & (e >= pd.Timestamp(fy_start))
    period = df["measuring_period"].fillna("").astype(str).str.extract(r"(\d{4})")[0]
    undated = s.isna() & (period == str(fy_end.year))
    return dated | undated


def _suggest_leave(sc_all, people, leave, fy_start, fy_end) -> pd.DataFrame:
    """Likely leave not yet recorded, for someone to confirm:
      1. leave-of-absence time entries (config.LEAVE_OF_ABSENCE_PATTERN),
         grouped into spans;
      2. runs of >= LEAVE_GAP_MIN_WORKDAYS workdays inside the person's
         employment window with no hours at all (labor detail), or whole
         months with no hours between months with hours (monthly sources).
    Spans already covered by recorded leave are skipped."""
    cols = ["full_name", "leave_start", "leave_end", "percent_away", "leave_type", "evidence"]
    keys = set(sc_all["name_key"])
    who = people[people["name_key"].isin(keys)].set_index("name_key")
    out = []

    def covered(key, s, e) -> bool:
        if leave is None or leave.empty:
            return False
        lv = leave[leave["name_key"] == key]
        for r in lv.itertuples():
            ls, le = pd.Timestamp(r.leave_start), pd.Timestamp(r.leave_end) if pd.notna(r.leave_end) else pd.Timestamp(fy_end)
            if ls <= e and le >= s:
                return True
        return False

    source = mp._hours_source(fy_start, fy_end)
    if source == "labor_detail":
        ent = query(
            "SELECT name_key, transaction_date AS d, SUM(hours) AS h, "
            "STRING_AGG(DISTINCT COALESCE(matter_name, '') || ' ' || COALESCE(labor_code, ''), '; ') AS txt "
            "FROM labor_detail WHERE transaction_date BETWEEN ? AND ? GROUP BY 1, 2", [fy_start, fy_end])
        ent["d"] = pd.to_datetime(ent["d"])
        loa = ent[ent["txt"].str.contains(config.LEAVE_OF_ABSENCE_PATTERN, case=False, regex=True, na=False)]
        for key, g in loa.groupby("name_key"):
            if key not in keys:
                continue
            g = g.sort_values("d")
            span_start, prev = g["d"].iloc[0], g["d"].iloc[0]
            for d in list(g["d"].iloc[1:]) + [None]:
                if d is None or len(pd.bdate_range(prev, d)) > 4:
                    if not covered(key, span_start, prev):
                        days = g[(g["d"] >= span_start) & (g["d"] <= prev)]
                        pct = min(100.0, round(days["h"].sum() / max(len(pd.bdate_range(span_start, prev)), 1) / 8 * 100 / 5) * 5)
                        out.append((who.loc[key, "full_name"], span_start.date(), prev.date(), pct or 100.0,
                                    "Other", f"Leave time entries ({days['h'].sum():,.0f} hrs)"))
                    if d is not None:
                        span_start = d
                if d is not None:
                    prev = d
        # Gaps with no hours at all.
        worked = ent[ent["h"] > 0].groupby("name_key")["d"].apply(lambda s: set(s.dt.normalize()))
        for key in keys:
            p = who.loc[key] if key in who.index else None
            s = max(pd.Timestamp(fy_start), pd.Timestamp(p["start_date"])) if p is not None and pd.notna(p.get("start_date")) else pd.Timestamp(fy_start)
            e = min(pd.Timestamp(fy_end), pd.Timestamp(p["end_date"])) if p is not None and pd.notna(p.get("end_date")) else pd.Timestamp(fy_end)
            days = worked.get(key, set())
            if not days:
                continue
            run = []
            for d in list(pd.bdate_range(s, e)) + [None]:
                if d is not None and d not in days:
                    run.append(d)
                    continue
                # Only gaps between worked days -- a run at the very start or end
                # is a hire / departure (start_date / end_date), not leave.
                if (len(run) >= config.LEAVE_GAP_MIN_WORKDAYS and run[0] > min(days) and run[-1] < max(days)
                        and not covered(key, run[0], run[-1])):
                    out.append((who.loc[key, "full_name"], run[0].date(), run[-1].date(), 100.0, "Other",
                                f"No hours for {len(run)} workdays"))
                run = []
    elif source == "monthly_hours":
        m = query(
            "SELECT name_key, month, billable_to_clients + nb_credited + nb_not_credited AS h FROM monthly_hours "
            "WHERE month BETWEEN ? AND ?", [fy_start, fy_end])
        m["month"] = pd.to_datetime(m["month"])
        for key, g in m.groupby("name_key"):
            if key not in keys:
                continue
            g = g.set_index("month")["h"].reindex(pd.date_range(fy_start, fy_end, freq="MS")).fillna(0)
            active = g[g > 0]
            if active.empty:
                continue
            median = active.median()
            first, last = active.index.min(), active.index.max()
            for month, h in g.items():
                if first < month < last and h < 0.25 * median:
                    s, e = month, month + pd.offsets.MonthEnd(0)
                    if not covered(key, s, e):
                        out.append((who.loc[key, "full_name"], s.date(), e.date(), 100.0, "Other",
                                    f"{h:,.0f} hrs in {month:%b %Y} vs. typical {median:,.0f}"))
    df = pd.DataFrame(out, columns=cols)
    return df.drop_duplicates(subset=["full_name", "leave_start"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Scorecard tabs
# ---------------------------------------------------------------------------
def _scorecard_tabs(view, roles):
    tabs = st.tabs(["Hours Expectation", "Total Activity", "Bonus Eligibility", "Promotion (2-yr lookback)"])
    specs = [
        ["Timekeeper", "Annual Expectation", "Leave Days", "Expectation", "Billable Needed", "Client", "FOA",
         "Pro Bono", "Creditable NB (logged)", "Creditable NB (counted)", "Credited Hours", "% of Expectation", "Zone"],
        ["Timekeeper", "Total Expectation", "Client", "FOA", "Pro Bono", "Creditable NB (logged)", "Other NB",
         "Time Off", "Total Hours", "Total %", "Total Status"],
        ["Timekeeper", "Bonus Threshold", "Client", "FOA", "Creditable NB (counted)", "Bonus Hours", "Bonus %",
         "Pro Bono", "Bonus Credited Hours", "Bonus Status"],
        ["Timekeeper", "% of Expectation", "Prior Period %", "2-yr Avg %", "Promotion Lookback"],
    ]
    for tab, cols in zip(tabs, specs):
        with tab:
            for role in roles:
                sub = view[view["Role"] == role].sort_values("% of Expectation", ascending=False)
                if sub.empty:
                    continue
                st.markdown(f"**{_role_label(role)}**")
                out = sub[cols].copy()
                cfg = {}
                for c in cols:
                    if c in ("Timekeeper", "Zone", "Promotion Lookback") or c.endswith("Status"):
                        continue
                    if out[c].isna().any():
                        out[c] = out[c].map(lambda v, pct=c.endswith("%"): "—" if pd.isna(v) else (fmt_pct_smart(v) if pct else fmt_num(v)))
                    else:
                        cfg[c] = st.column_config.NumberColumn(format="%g%%" if c.endswith("%") else "localized")
                st.dataframe(out, use_container_width=True, hide_index=True, column_config=cfg)
            if tab is tabs[2]:
                st.caption("Eligibility only -- bonuses remain discretionary and subject to firm performance and policy compliance.")
            if tab is tabs[3]:
                st.caption(f"Policy §1c: promotion in a year the requirement wasn't met needs a 2-year average of at least {config.PROMOTION_LOOKBACK_PCT}%.")


def _report_notes(source, sc, leave, flagged: set | None = None) -> list[str]:
    notes = []
    for name in sorted(flagged or []):
        notes.append(f"† {name}: requirement prorated from a mid-period start, but this export's full-year hours "
                     "include time before that date (e.g. as a contractor), so the result reads high and isn't "
                     "counted as met or bonus-eligible. The Vantagepoint time-detail export resolves it.")
    if source != "labor_detail":
        notes.append(f"Hours come from {mp._SOURCE_LABELS.get(source, source)} rather than a Vantagepoint time-detail export; pro bono and creditable time may be missing or approximated.")
    n_leave = int((sc["Leave Days"] > 0).sum())
    notes.append(
        f"{n_leave} timekeeper(s) had approved leave; their requirements (and the creditable cap) are prorated by available workdays."
        if n_leave else "No approved leave is recorded for this period; requirements are prorated only for mid-period start or end dates.")
    notes.append("Owners, contractors, advisory and administrative staff have no hourly requirement and are not shown.")
    return notes
