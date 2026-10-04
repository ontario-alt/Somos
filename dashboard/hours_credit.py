"""
Measuring-period hours policy, as plain pandas (no Streamlit) so the math
can be checked on its own:

  * Annual target by role (config.BILLABLE_HOUR_TARGETS).
  * Prorated for partial-year employment and approved leave, on Mon-Fri
    workdays: target x available workdays / measuring-period workdays.
  * Creditable hours = billable + pro bono, pro bono capped at
    config.PRO_BONO_CREDIT_CAP per person (optionally prorated too).
  * Pace = creditable hours vs. expected-to-date, where expected-to-date
    is the prorated target scaled by the share of that person's own
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

STATUS_ORDER = ["Behind", "Watch", "On Track", "Met"]


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
    if expected <= 0:
        return "On Track"
    ratio = creditable / expected
    on_track, watch = config.PACE_STATUS_THRESHOLDS
    if ratio >= on_track:
        return "On Track"
    if ratio >= watch:
        return "Watch"
    return "Behind"


def build_scorecard(
    people: pd.DataFrame,
    hours: pd.DataFrame,
    leave: pd.DataFrame | None,
    period_start,
    period_end,
    as_of,
) -> pd.DataFrame:
    """people: name_key, full_name, employee_number, role, start_date, end_date
    hours:  name_key, billable_hours, pro_bono_hours (to date), optionally entities
    leave:  name_key, employee_number, leave_start, leave_end, percent_away

    Returns one row per person with a role, with target, credit and pace columns."""
    period_start, period_end, as_of = _ts(period_start), _ts(period_end), _ts(as_of)
    as_of = min(max(as_of, period_start - pd.Timedelta(days=1)), period_end)
    period_wd = len(workdays(period_start, period_end))
    hrs = hours.set_index("name_key") if not hours.empty else pd.DataFrame()

    out = []
    for _, p in people.iterrows():
        role = p.get("role")
        if role not in config.BILLABLE_HOUR_TARGETS:
            continue
        annual = float(config.BILLABLE_HOUR_TARGETS[role])
        person_leaves = _leaves_for(p, leave)
        avail = availability(period_start, period_end, p.get("start_date"), p.get("end_date"), person_leaves)
        avail_total = float(avail.sum())
        avail_elapsed = float(avail[avail.index <= as_of].sum())
        share = avail_total / period_wd if period_wd else 0.0
        target = annual * share
        elapsed_frac = avail_elapsed / avail_total if avail_total else 0.0
        expected = target * elapsed_frac

        # Employment-window workdays not available = leave days (weighted).
        employed = availability(period_start, period_end, p.get("start_date"), p.get("end_date"))
        leave_days = float(employed.sum() - avail_total)

        key = p.get("name_key")
        h = hrs.loc[key] if key in hrs.index else None
        billable = float(h["billable_hours"]) if h is not None else 0.0
        pro_bono = float(h["pro_bono_hours"]) if h is not None else 0.0
        cap = config.PRO_BONO_CREDIT_CAP * (share if config.PRO_BONO_CAP_PRORATED else 1.0)
        pb_credited = min(pro_bono, cap)
        creditable = billable + pb_credited
        remaining = max(target - creditable, 0.0)
        remaining_weeks = (avail_total - avail_elapsed) / 5.0

        out.append(
            {
                "name_key": key,
                "Timekeeper": p.get("full_name"),
                "Role": role,
                "Entities": (h.get("entities") if h is not None and "entities" in h else None) or "",
                "Annual Target": annual,
                "Leave Days": round(leave_days, 1),
                "Prorated Target": target,
                "Billable": billable,
                "Pro Bono (logged)": pro_bono,
                "Pro Bono (credited)": pb_credited,
                "Pro Bono (over cap)": pro_bono - pb_credited,
                "Creditable": creditable,
                "Expected to Date": expected,
                "Variance to Expected": creditable - expected,
                "% of Target": (creditable / target * 100) if target else np.nan,
                "Pace %": (creditable / expected * 100) if expected else np.nan,
                "Projected": (creditable / elapsed_frac) if elapsed_frac > 0 else np.nan,
                "Remaining": remaining,
                "Needed / Week": (remaining / remaining_weeks) if remaining_weeks > 0 and remaining > 0 else 0.0,
                "Status": status_for(creditable, target, expected),
                "has_hours": h is not None,
            }
        )
    cols = [
        "name_key", "Timekeeper", "Role", "Entities", "Annual Target", "Leave Days", "Prorated Target",
        "Billable", "Pro Bono (logged)", "Pro Bono (credited)", "Pro Bono (over cap)", "Creditable",
        "Expected to Date", "Variance to Expected", "% of Target", "Pace %", "Projected", "Remaining",
        "Needed / Week", "Status", "has_hours",
    ]
    return pd.DataFrame(out, columns=cols)


def cumulative_pace(
    monthly: pd.DataFrame, person: pd.Series, scorecard_row: pd.Series, leave: pd.DataFrame | None,
    period_start, period_end,
) -> pd.DataFrame:
    """Month-end cumulative creditable hours (pro bono cap applied to the
    running total) vs. the prorated target's expected path for one person.
    monthly: month (Timestamp, month start), billable_hours, pro_bono_hours."""
    period_start, period_end = _ts(period_start), _ts(period_end)
    avail = availability(
        period_start, period_end, person.get("start_date"), person.get("end_date"), _leaves_for(person, leave)
    )
    months = pd.date_range(period_start, period_end, freq="MS")
    m = monthly.set_index("month").reindex(months).fillna(0.0)
    share = scorecard_row["Prorated Target"] / scorecard_row["Annual Target"] if scorecard_row["Annual Target"] else 0.0
    cap = config.PRO_BONO_CREDIT_CAP * (share if config.PRO_BONO_CAP_PRORATED else 1.0)
    credited = m["billable_hours"].cumsum() + np.minimum(m["pro_bono_hours"].cumsum(), cap)
    total = avail.sum()
    month_end = months + pd.offsets.MonthEnd(0)
    expected = [scorecard_row["Prorated Target"] * (avail[avail.index <= me].sum() / total if total else 0) for me in month_end]
    return pd.DataFrame({"month": months, "creditable_cum": credited.values, "expected_cum": expected})


def salary_cost(monthly_rate: float, start, end) -> float:
    """Salaried cost over [start, end]: monthly rate x elapsed months
    (calendar days / (365/12)). Hours don't change salary cost."""
    s, e = _ts(start), _ts(end)
    if s is None or e is None or e < s:
        return 0.0
    return float(monthly_rate) * ((e - s).days + 1) / (365.0 / 12.0)
