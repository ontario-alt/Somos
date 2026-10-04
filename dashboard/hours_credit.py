"""
Measuring-period hours policy, as plain pandas (no Streamlit) so the math
can be checked on its own:

  * The firm's Promotion and Bonus Policy (see config.py): Hours
    Expectation (client + FOA + pro bono + creditable non-billable capped
    at 75), Total Activity (all chargeable + non-chargeable), and the
    Bonus Threshold (client + FOA + capped creditable, no pro bono).
  * Every requirement -- and the creditable cap -- prorated for
    partial-year employment and approved leave, on Mon-Fri workdays:
    annual x available workdays / measuring-period workdays.
  * Pace = hours vs. expected-to-date, where expected-to-date is the
    prorated requirement scaled by the share of that person's own
    available workdays that have elapsed -- so someone back from three
    months of leave isn't marked behind for the months they were out.

Also the per-timekeeper cost/profit roll-up used by the profitability
section. Everything here takes DataFrames in and returns DataFrames out;
the page module does the querying and rendering.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

import config

STATUS_ORDER = ["Not Met", "Behind", "Watch", "On Track", "Met"]


def _ts(d) -> pd.Timestamp | None:
    if d is None:
        return None
    try:
        t = pd.Timestamp(d)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(t) else t.normalize()


def workdays(start, end) -> pd.DatetimeIndex:
    """Mon-Fri dates from start through end, inclusive."""
    start, end = _ts(start), _ts(end)
    if start is None or end is None or end < start:
        return pd.DatetimeIndex([])
    return pd.bdate_range(start, end)


def availability(period_start, period_end, start_date=None, end_date=None, leaves=()) -> pd.Series:
    """One value per workday in the measuring period: 1.0 = available,
    0.0 = not employed or fully on leave, 0.5 = half-time leave. Overlapping
    leaves take the larger percent_away for a day rather than stacking.
    `leaves` is an iterable of (leave_start, leave_end or None, percent_away)."""
    days = workdays(period_start, period_end)
    avail = pd.Series(1.0, index=days)
    s, e = _ts(start_date), _ts(end_date)
    if s is not None:
        avail[days < s] = 0.0
    if e is not None:
        avail[days > e] = 0.0
    away = pd.Series(0.0, index=days)
    for ls, le, pct in leaves:
        ls = _ts(ls)
        le = _ts(le) or _ts(period_end)
        if ls is None:
            continue
        frac = (100.0 if pct is None or pd.isna(pct) else float(pct)) / 100.0
        mask = (days >= ls) & (days <= le)
        away[mask] = np.maximum(away[mask], frac)
    return (avail * (1.0 - away)).clip(lower=0.0)


def _leaves_for(person: pd.Series, leave: pd.DataFrame | None) -> list[tuple]:
    if leave is None or leave.empty:
        return []
    num = str(person.get("employee_number") or "").strip()
    by_num = leave["employee_number"].fillna("").astype(str).str.strip()
    mask = (by_num == num) & (num != "")
    mask |= (by_num == "") & (leave["name_key"] == person.get("name_key"))
    return list(leave.loc[mask, ["leave_start", "leave_end", "percent_away"]].itertuples(index=False, name=None))


def status_for(creditable: float, target: float, expected: float) -> str:
    if target > 0 and creditable >= target:
        return "Met"
    if target > 0 and expected >= target - 1e-9:
        return "Not Met"  # period over (for this person) and short of the requirement
    if expected <= 0:
        return "On Track"
    ratio = creditable / expected
    on_track, watch = config.PACE_STATUS_THRESHOLDS
    if ratio >= on_track:
        return "On Track"
    if ratio >= watch:
        return "Watch"
    return "Behind"


def _num_or_none(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def person_targets(p: pd.Series) -> dict:
    """Annual requirements for one person: their own override from
    employee_targets.csv (individual terms) where set, else their role's
    default from config. Keys: expectation, cap, total, bonus (None =
    no such requirement)."""
    role = p.get("role")

    def pick(col, default):
        v = _num_or_none(p.get(col))
        return v if v is not None else (float(default) if default is not None else None)

    return {
        "expectation": pick("billable_target", config.BILLABLE_HOUR_TARGETS.get(role)),
        "cap": pick("credit_cap", config.CREDITABLE_NB_CAP),
        "total": pick("total_target", config.TOTAL_HOUR_TARGETS.get(role)),
        "bonus": pick("bonus_threshold", config.BONUS_HOUR_THRESHOLDS.get(role)),
    }


def _worse(a: str, b: str | None) -> str:
    if not b:
        return a
    return min(a, b, key=STATUS_ORDER.index)


HOURS_COLS = ["client_hours", "foa_hours", "pro_bono_hours", "creditable_hours", "other_hours", "time_off_hours"]


def _total_activity(h: dict) -> float:
    total = h["client_hours"] + h["foa_hours"] + h["pro_bono_hours"] + h["creditable_hours"] + h["other_hours"]
    return total + (h["time_off_hours"] if config.TOTAL_INCLUDES_TIME_OFF else 0.0)


def build_scorecard(
    people: pd.DataFrame,
    hours: pd.DataFrame,
    leave: pd.DataFrame | None,
    period_start,
    period_end,
    as_of,
) -> pd.DataFrame:
    """people: name_key, full_name, employee_number, role, start_date, end_date,
               optional billable_target / credit_cap / total_target / bonus_threshold
    hours:  name_key + HOURS_COLS (hours to date by policy category), optional entities
    leave:  name_key, employee_number, leave_start, leave_end, percent_away

    One row per tracked person (anyone with an Hours Expectation from role
    or override), scored on the policy's three tests: Hours Expectation,
    Total Activity and Bonus Threshold."""
    period_start, period_end, as_of = _ts(period_start), _ts(period_end), _ts(as_of)
    as_of = min(max(as_of, period_start - pd.Timedelta(days=1)), period_end)
    period_wd = len(workdays(period_start, period_end))
    hrs = hours.set_index("name_key") if not hours.empty else pd.DataFrame()

    out = []
    for _, p in people.iterrows():
        t = person_targets(p)
        if t["expectation"] is None:
            continue
        role = p.get("role") if p.get("role") in config.BILLABLE_HOUR_TARGETS else "Custom"
        avail = availability(period_start, period_end, p.get("start_date"), p.get("end_date"), _leaves_for(p, leave))
        avail_total = float(avail.sum())
        avail_elapsed = float(avail[avail.index <= as_of].sum())
        share = avail_total / period_wd if period_wd else 0.0
        elapsed_frac = avail_elapsed / avail_total if avail_total else 0.0
        employed = availability(period_start, period_end, p.get("start_date"), p.get("end_date"))
        leave_days = float(employed.sum() - avail_total)
        remaining_weeks = (avail_total - avail_elapsed) / 5.0

        def prorate(annual):
            return annual * share if annual is not None else None

        key = p.get("name_key")
        hrow = hrs.loc[key] if key in hrs.index else None
        h = {c: (float(hrow[c]) if hrow is not None and c in hrow and pd.notna(hrow[c]) else 0.0) for c in HOURS_COLS}

        cap = t["cap"] * (share if config.CREDITABLE_CAP_PRORATED else 1.0)
        counted = min(h["creditable_hours"], cap)
        chargeable = h["client_hours"] + h["foa_hours"]
        credited = chargeable + h["pro_bono_hours"] + counted
        bonus_hours = chargeable + counted
        total_hours = _total_activity(h)

        exp_target = prorate(t["expectation"])
        exp_expected = exp_target * elapsed_frac
        exp_status = status_for(credited, exp_target, exp_expected)
        remaining = max(exp_target - credited, 0.0)
        projected = credited / elapsed_frac if elapsed_frac > 0 else np.nan

        total_target = prorate(t["total"])
        total_status = status_for(total_hours, total_target, total_target * elapsed_frac) if total_target else None

        bonus_target = prorate(t["bonus"])
        if bonus_target is None:
            bonus_status, bonus_credited = "", np.nan
        elif bonus_hours >= bonus_target:
            bonus_status, bonus_credited = "Eligible", bonus_hours + h["pro_bono_hours"]
        else:
            bonus_proj = bonus_hours / elapsed_frac if elapsed_frac > 0 else 0.0
            bonus_status = "On pace" if bonus_proj >= bonus_target and elapsed_frac < 1 else "Not met" if elapsed_frac >= 1 else "Not on pace"
            bonus_credited = np.nan

        out.append(
            {
                "name_key": key,
                "Timekeeper": p.get("full_name"),
                "Role": role,
                "Entities": (hrow.get("entities") if hrow is not None and "entities" in hrow else None) or "",
                "Leave Days": round(leave_days, 1),
                "Client": h["client_hours"],
                "FOA": h["foa_hours"],
                "Pro Bono": h["pro_bono_hours"],
                "Creditable NB (logged)": h["creditable_hours"],
                "Creditable Cap": cap,
                "Creditable NB (counted)": counted,
                "Creditable NB (over cap)": h["creditable_hours"] - counted,
                "Other NB": h["other_hours"],
                "Time Off": h["time_off_hours"],
                "Annual Expectation": t["expectation"],
                "Expectation": exp_target,
                "Credited Hours": credited,
                "Expected to Date": exp_expected,
                "Variance to Expected": credited - exp_expected,
                "% of Expectation": credited / exp_target * 100 if exp_target else np.nan,
                "Pace %": credited / exp_expected * 100 if exp_expected else np.nan,
                "Projected": projected,
                "Remaining": remaining,
                "Needed / Week": remaining / remaining_weeks if remaining_weeks > 0 and remaining > 0 else 0.0,
                "Expectation Status": exp_status,
                "Total Hours": total_hours,
                "Total Expectation": total_target if total_target is not None else np.nan,
                "Total %": total_hours / total_target * 100 if total_target else np.nan,
                "Total Status": total_status or "",
                "Bonus Hours": bonus_hours,
                "Bonus Threshold": bonus_target if bonus_target is not None else np.nan,
                "Bonus %": bonus_hours / bonus_target * 100 if bonus_target else np.nan,
                "Bonus Status": bonus_status,
                "Bonus Credited Hours": bonus_credited,
                "Status": _worse(exp_status, total_status),
                "has_hours": hrow is not None,
            }
        )
    return pd.DataFrame(out, columns=SCORECARD_COLS)


SCORECARD_COLS = [
    "name_key", "Timekeeper", "Role", "Entities", "Leave Days", "Client", "FOA", "Pro Bono",
    "Creditable NB (logged)", "Creditable Cap", "Creditable NB (counted)", "Creditable NB (over cap)",
    "Other NB", "Time Off", "Annual Expectation", "Expectation", "Credited Hours", "Expected to Date",
    "Variance to Expected", "% of Expectation", "Pace %", "Projected", "Remaining", "Needed / Week",
    "Expectation Status", "Total Hours", "Total Expectation", "Total %", "Total Status", "Bonus Hours",
    "Bonus Threshold", "Bonus %", "Bonus Status", "Bonus Credited Hours", "Status", "has_hours",
]


def cumulative_pace(
    monthly: pd.DataFrame, person: pd.Series, scorecard_row: pd.Series, leave: pd.DataFrame | None,
    period_start, period_end,
) -> pd.DataFrame:
    """Month-end cumulative Credited Hours (creditable cap applied to the
    running total) and Total Activity vs. each prorated requirement's
    expected path for one person. monthly: month + HOURS_COLS."""
    period_start, period_end = _ts(period_start), _ts(period_end)
    avail = availability(
        period_start, period_end, person.get("start_date"), person.get("end_date"), _leaves_for(person, leave)
    )
    months = pd.date_range(period_start, period_end, freq="MS")
    m = monthly.set_index("month").reindex(months).fillna(0.0)
    for c in HOURS_COLS:
        if c not in m:
            m[c] = 0.0
    credited = (m["client_hours"] + m["foa_hours"] + m["pro_bono_hours"]).cumsum() + np.minimum(
        m["creditable_hours"].cumsum(), scorecard_row["Creditable Cap"]
    )
    total = avail.sum()
    month_end = months + pd.offsets.MonthEnd(0)
    frac = np.array([avail[avail.index <= me].sum() / total if total else 0 for me in month_end])
    out = pd.DataFrame(
        {"month": months, "creditable_cum": credited.values, "expected_cum": scorecard_row["Expectation"] * frac}
    )
    if pd.notna(scorecard_row.get("Total Expectation")):
        out["total_cum"] = m.apply(lambda r: _total_activity(r), axis=1).cumsum().values
        out["total_expected_cum"] = scorecard_row["Total Expectation"] * frac
    return out


def salary_cost(monthly_rate: float, start, end) -> float:
    """Salaried cost over [start, end]: monthly rate x elapsed months
    (calendar days / (365/12)). Hours don't change salary cost."""
    s, e = _ts(start), _ts(end)
    if s is None or e is None or e < s:
        return 0.0
    return float(monthly_rate) * ((e - s).days + 1) / (365.0 / 12.0)
