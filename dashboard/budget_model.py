"""
Budget model for the Budget page and its Excel export. Pure pandas -- no
Streamlit -- so the same numbers come out of the page, the export and a
test script.

Hybrid method, for one calendar year (config.BUDGET_YEAR):

- **Fee revenue** (people plan): billable hours x billing rate x
  realization, per person. Hours are spread across months by the
  seasonality weights (Mon-Fri workdays by default) and only count in the
  months the person is on staff. New rates apply from the rate-increase
  month.
- **Salaries + fringe** (people plan): annual salary / 12 for each month
  on staff, with the raise from the raise month, plus fringe %.
- **Overhead and other lines**: prior-year actuals (P&L workbook, or the
  Vantagepoint GL if no P&L is loaded) x (1 + change %), or a fixed
  amount you type in, spread evenly across the year. Revenue and payroll
  lines in the prior year are replaced by the people plan so nothing is
  counted twice.
- **Budget drivers**: lines you enter yourself -- owner draws,
  guaranteed payments, bonuses, a new lease, capex, loan payments -- as
  an amount per month, per year or one-time, between a start and end
  month. Owner draws sit below net income: the budget shows profit
  before draws, the draws, and what's left after.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import config

MONTHS = list(range(1, 13))
MONTH_LABELS = [calendar.month_abbr[m] for m in MONTHS]

# Overhead line treatments.
PRIOR_PLUS = "Prior year + %"
PEOPLE_PLAN = "People plan"
EXCLUDE = "Exclude"
TREATMENTS = [PRIOR_PLUS, PEOPLE_PLAN, EXCLUDE]

# Budget driver sections and bases.
DRIVER_SECTIONS = ["Owner draws", "Personnel", "Operating expense", "Other expense", "Revenue", "Other income"]
BASES = ["Per month", "Per year", "One-time"]

PEOPLE_COLUMNS = [
    "include", "name", "employee_number", "role", "start_month", "end_month",
    "annual_salary", "billable_hours", "bill_rate", "realization_pct",
    "prior_billable_hours", "prior_rate", "note",
]
OVERHEAD_COLUMNS = [
    "section", "category", "account_number", "line_item", "treatment",
    "prior_amount", "growth_pct", "override_amount",
]
DRIVER_COLUMNS = ["include", "driver", "section", "person", "amount", "basis", "start_month", "end_month", "note"]


# ---------------------------------------------------------------------------
# Assumptions + seasonality
# ---------------------------------------------------------------------------
@dataclass
class Assumptions:
    year: int = config.BUDGET_YEAR
    rate_increase_pct: float = config.BUDGET_DEFAULTS["rate_increase_pct"]
    rate_increase_month: int = config.BUDGET_DEFAULTS["rate_increase_month"]
    salary_increase_pct: float = config.BUDGET_DEFAULTS["salary_increase_pct"]
    salary_increase_month: int = config.BUDGET_DEFAULTS["salary_increase_month"]
    fringe_pct: float = config.BUDGET_DEFAULTS["fringe_pct"]
    realization_pct: float = config.BUDGET_DEFAULTS["realization_pct"]
    overhead_growth_pct: float = config.BUDGET_DEFAULTS["overhead_growth_pct"]
    seasonality: list[float] = field(default_factory=list)  # 12 weights summing to 1

    def __post_init__(self):
        if len(self.seasonality) != 12:
            self.seasonality = workday_weights(self.year)


def workday_weights(year: int) -> list[float]:
    """Share of the year's Mon-Fri workdays in each month."""
    days = [int(np.busday_count(date(year, m, 1), date(year + (m == 12), m % 12 + 1, 1))) for m in MONTHS]
    total = sum(days)
    return [d / total for d in days]


def normalized_weights(weights) -> np.ndarray:
    w = np.array([float(x or 0) for x in weights], dtype=float)
    return w / w.sum() if w.sum() > 0 else np.full(12, 1 / 12)


# ---------------------------------------------------------------------------
# Prior-year actuals (baseline)
# ---------------------------------------------------------------------------
def gl_to_actuals(gl: pd.DataFrame) -> pd.DataFrame:
    """Vantagepoint trial balance rows -> the same shape as pl_actuals.
    Uses each month's activity (debits/credits), not closing balances, and
    only one-month periods, so YTD trial balances aren't double counted."""
    if gl is None or gl.empty:
        return pd.DataFrame()
    g = gl.copy()
    g["period_start"] = pd.to_datetime(g["period_start"])
    g["period_end"] = pd.to_datetime(g["period_end"])
    one_month = (g["period_start"].dt.day == 1) & (
        g["period_start"].dt.to_period("M") == g["period_end"].dt.to_period("M")
    )
    g = g[one_month & g["account_type"].isin(["Revenue", "COGS", "Expense"])]
    if g.empty:
        return pd.DataFrame()
    debit_minus_credit = g["debits"].fillna(0) - g["credits"].fillna(0)
    g["amount"] = np.where(g["account_type"] == "Revenue", -debit_minus_credit, debit_minus_credit)
    return pd.DataFrame({
        "entity": g["entity"], "sheet": g["entity"], "is_consolidated": False,
        "section": g["account_type"], "category": None,
        "account_number": g["account_number"].astype(str), "line_item": g["account_name"],
        "period_start": g["period_start"], "period_end": g["period_end"], "months": 1,
        "amount": g["amount"],
    })


def baseline_windows(actuals: pd.DataFrame) -> list[str]:
    """Choices for the prior-year window, best first."""
    if actuals is None or actuals.empty:
        return []
    a = actuals.copy()
    a["period_start"] = pd.to_datetime(a["period_start"])
    monthly = a[a["months"] == 1]
    opts = []
    if not monthly.empty:
        last = monthly["period_start"].max()
        n = monthly["period_start"].dt.to_period("M").nunique()
        if n >= 12:
            opts.append(f"Trailing 12 months to {last:%b %Y}")
        years = monthly.groupby(monthly["period_start"].dt.year)["period_start"].apply(
            lambda s: s.dt.month.nunique())
        opts += [f"Calendar {y}" for y, k in years.sort_index(ascending=False).items() if k == 12]
        ytd_year = last.year
        if years.get(ytd_year, 12) < 12:
            opts.append(f"{ytd_year} year to date, annualized")
        if n < 12:
            opts.append(f"All {n} months available, annualized")
    for y in sorted(a.loc[a["months"] == 12, "period_start"].dt.year.unique(), reverse=True):
        label = f"Calendar {y}"
        if label not in opts:
            opts.append(label)
    return opts


def baseline_lines(actuals: pd.DataFrame, window: str, sheets: list[str] | None = None) -> pd.DataFrame:
    """Prior-year amount per line item (summed across entities) for the
    chosen window. Columns: section, category, account_number, line_item,
    prior_amount."""
    cols = ["section", "category", "account_number", "line_item", "prior_amount"]
    if actuals is None or actuals.empty or not window:
        return pd.DataFrame(columns=cols)
    a = actuals.copy()
    a["period_start"] = pd.to_datetime(a["period_start"])
    if sheets is not None:
        a = a[a["sheet"].isin(sheets)]
    factor = 1.0
    monthly = a[a["months"] == 1]
    if window.startswith("Trailing 12"):
        last = monthly["period_start"].max()
        a = monthly[monthly["period_start"] > last - pd.DateOffset(months=12)]
    elif window.startswith("Calendar"):
        y = int(window.split()[1])
        in_year = a[a["period_start"].dt.year == y]
        # Prefer monthly rows; fall back to the annual column.
        a = in_year[in_year["months"] == 1] if (in_year["months"] == 1).any() else in_year
    elif "year to date" in window:
        y = int(window.split()[0])
        a = monthly[monthly["period_start"].dt.year == y]
        factor = 12 / max(a["period_start"].dt.month.nunique(), 1)
    elif window.startswith("All"):
        a = monthly
        factor = 12 / max(a["period_start"].dt.to_period("M").nunique(), 1)
    if a.empty:
        return pd.DataFrame(columns=cols)
    a["category"] = a["category"].fillna("")
    a["account_number"] = a["account_number"].fillna("").astype(str)
    out = (a.groupby(["section", "category", "account_number", "line_item"], dropna=False)["amount"]
           .sum().mul(factor).reset_index().rename(columns={"amount": "prior_amount"}))
    order = {s: i for i, s in enumerate(["Revenue", "Other Income", "COGS", "Expense", "Other Expense"])}
    out["_o"] = out["section"].map(order).fillna(9)
    return out.sort_values(["_o", "account_number", "category", "line_item"]).drop(columns="_o").reset_index(drop=True)


def _matches(text: str, keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keywords)


def default_treatment(section: str, line_item: str, category: str = "") -> str:
    label = f"{category} {line_item}"
    if section == "Revenue":
        return PRIOR_PLUS if _matches(label, config.BUDGET_NON_FEE_REVENUE_KEYWORDS) else PEOPLE_PLAN
    if section in ("COGS", "Expense") and _matches(label, config.BUDGET_PERSONNEL_KEYWORDS):
        return PEOPLE_PLAN
    return PRIOR_PLUS


def default_overhead(baseline: pd.DataFrame, a: Assumptions, saved: pd.DataFrame | None = None) -> pd.DataFrame:
    """Overhead table from the baseline, keeping any saved choices
    (treatment, change %, fixed amount) for lines that still exist."""
    df = baseline.copy()
    if df.empty:
        return pd.DataFrame(columns=OVERHEAD_COLUMNS)
    df["treatment"] = [default_treatment(s, li, c) for s, li, c in zip(df["section"], df["line_item"], df["category"])]
    df["growth_pct"] = a.overhead_growth_pct
    df["override_amount"] = np.nan
    if saved is not None and not saved.empty:
        key = ["section", "category", "account_number", "line_item"]
        s = saved.copy()
        for k in key:
            s[k] = s[k].fillna("").astype(str)
            df[k] = df[k].fillna("").astype(str)
        s = s.drop_duplicates(key, keep="last").set_index(key)[["treatment", "growth_pct", "override_amount"]]
        df = df.set_index(key)
        df.update(s)
        df = df.reset_index()
    return df[OVERHEAD_COLUMNS]


# ---------------------------------------------------------------------------
# People plan
# ---------------------------------------------------------------------------
def _first_token(name: str) -> str:
    return re.sub(r"[^a-z ]", "", (name or "").lower()).split(" ")[0] if name else ""


def draw_people(drivers: pd.DataFrame) -> set[str]:
    """Lower-cased names of people paid through an owner-draw driver."""
    if drivers is None or drivers.empty:
        return set()
    d = drivers[(drivers["section"] == "Owner draws") & drivers["include"].fillna(True).astype(bool)]
    return {str(p).strip().lower() for p in d["person"].dropna() if str(p).strip()}


def is_draw_person(full_name: str, owners: set[str]) -> bool:
    """True if a driver's `person` names this employee: an exact name, or a
    first name / partial that appears in theirs ("Alfred" matches "Alfred
    Fraijo Jr.")."""
    n = (full_name or "").lower()
    return any(o == n or (o and re.search(rf"\b{re.escape(o)}\b", n)) for o in owners)


def default_people(
    cost_rates: pd.DataFrame,
    targets: pd.DataFrame | None,
    prior_hours: pd.DataFrame | None,
    a: Assumptions,
    drivers: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Starter people plan from Vantagepoint.

    - Salary: Salary-type cost rate x 12 (it's monthly); Hourly-type rate x
      prior-year total hours (or 2,080).
    - Hours: the person's billable target (employee_targets.csv), else the
      role default, else last 12 months' billable hours.
    - Rate: last 12 months' standard value / billable hours.
    - Anyone named in an owner-draw driver gets $0 salary -- the draw is
      their pay -- but keeps their billable revenue.
    - Terminated or ended staff start unticked.
    prior_hours columns: name_key or employee_number, billable_hours,
    total_hours, standard_value.
    """
    if cost_rates is None or cost_rates.empty:
        return pd.DataFrame(columns=PEOPLE_COLUMNS)
    from etl.common import name_key

    p = cost_rates.copy()
    p["name_key"] = p["full_name"].map(name_key)
    p["employee_number"] = p["employee_number"].astype(str)
    if targets is not None and not targets.empty:
        t = targets.copy()
        t["employee_number"] = t["employee_number"].astype(str)
        t = t.drop_duplicates("employee_number")[["employee_number", "target_type", "end_date", "billable_target"]]
        p = p.merge(t, on="employee_number", how="left")
    else:
        p["target_type"] = None
        p["end_date"] = None
        p["billable_target"] = np.nan
    if prior_hours is not None and not prior_hours.empty:
        ph = prior_hours.copy()
        on = "employee_number" if "employee_number" in ph.columns and ph["employee_number"].notna().any() else "name_key"
        if on == "employee_number":
            ph["employee_number"] = ph["employee_number"].astype(str)
        ph = ph.groupby(on, as_index=False)[["billable_hours", "total_hours", "standard_value"]].sum(min_count=1)
        p = p.merge(ph, on=on, how="left")
    else:
        p[["billable_hours", "total_hours", "standard_value"]] = np.nan

    owners = draw_people(drivers)
    rows = []
    year_start = pd.Timestamp(a.year, 1, 1)
    for r in p.itertuples(index=False):
        role = config.resolve_role(getattr(r, "target_type", None))
        status = str(getattr(r, "status", "") or "")
        end = pd.to_datetime(getattr(r, "end_date", None), errors="coerce")
        active = not re.search(r"terminat|inactive", status, re.I) and (pd.isna(end) or end >= year_start)
        rate = float(r.job_cost_rate or 0)
        prior_total = float(r.total_hours) if pd.notna(r.total_hours) else np.nan
        if str(r.job_cost_type).lower().startswith("hour"):
            salary = rate * (prior_total if prior_total and prior_total > 0 else 2080)
        else:
            salary = rate * 12
        note = ""
        if is_draw_person(r.full_name, owners):
            salary = 0.0
            note = "Paid by owner draw (Budget drivers)"
        prior_b = float(r.billable_hours) if pd.notna(r.billable_hours) else np.nan
        target = r.billable_target if pd.notna(r.billable_target) else config.BILLABLE_HOUR_TARGETS.get(role)
        hours = float(target) if target is not None and pd.notna(target) else (prior_b if pd.notna(prior_b) else 0.0)
        prior_rate = (float(r.standard_value) / prior_b) if pd.notna(r.standard_value) and prior_b and prior_b > 0 else np.nan
        if hours > 0 and pd.isna(prior_rate):
            note = (note + "; " if note else "") + "No prior rate found -- enter one"
        rows.append({
            "include": bool(active), "name": r.full_name, "employee_number": r.employee_number,
            "role": role or (getattr(r, "labor_type", None) or ""),
            "start_month": 1, "end_month": 12,
            "annual_salary": round(salary, 2), "billable_hours": round(hours, 1),
            "bill_rate": round(prior_rate, 2) if pd.notna(prior_rate) else 0.0,
            "realization_pct": a.realization_pct,
            "prior_billable_hours": round(prior_b, 1) if pd.notna(prior_b) else np.nan,
            "prior_rate": round(prior_rate, 2) if pd.notna(prior_rate) else np.nan,
            "note": note,
        })
    out = pd.DataFrame(rows, columns=PEOPLE_COLUMNS)
    return out.sort_values(["include", "role", "name"], ascending=[False, True, True]).reset_index(drop=True)


def apply_draw_rule(people: pd.DataFrame, drivers: pd.DataFrame) -> pd.DataFrame:
    """Zero the salary of anyone newly named in an owner-draw driver."""
    owners = draw_people(drivers)
    if people.empty or not owners:
        return people
    p = people.copy()
    hit = p["name"].map(lambda n: is_draw_person(n, owners)) & ~p["note"].fillna("").str.contains("owner draw")
    p.loc[hit, "annual_salary"] = 0.0
    p.loc[hit, "note"] = "Paid by owner draw (Budget drivers)"
    return p


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------
def _num(s, default=0.0) -> np.ndarray:
    return pd.to_numeric(s, errors="coerce").fillna(default).to_numpy(dtype=float)


def _month_ints(s, default) -> np.ndarray:
    return pd.to_numeric(s, errors="coerce").fillna(default).clip(1, 12).round().to_numpy(dtype=int)


def people_monthly(people: pd.DataFrame, a: Assumptions) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(revenue, salary, hours) arrays shaped (people, 12)."""
    n = len(people)
    if n == 0:
        z = np.zeros((0, 12))
        return z, z, z
    m = np.arange(1, 13)
    inc = people["include"].fillna(False).astype(bool).to_numpy()
    start = _month_ints(people["start_month"], 1)
    end = _month_ints(people["end_month"], 12)
    on = inc[:, None] & (m[None, :] >= start[:, None]) & (m[None, :] <= end[:, None])
    w = normalized_weights(a.seasonality)
    hours = _num(people["billable_hours"])[:, None] * w[None, :] * on
    rate_f = np.where(m >= a.rate_increase_month, 1 + a.rate_increase_pct, 1.0)
    real = _num(people["realization_pct"], a.realization_pct)
    revenue = hours * _num(people["bill_rate"])[:, None] * rate_f[None, :] * real[:, None]
    raise_f = np.where(m >= a.salary_increase_month, 1 + a.salary_increase_pct, 1.0)
    salary = _num(people["annual_salary"])[:, None] / 12 * raise_f[None, :] * on
    return revenue, salary, hours


def drivers_monthly(drivers: pd.DataFrame) -> np.ndarray:
    """(drivers, 12) amounts."""
    n = len(drivers)
    if n == 0:
        return np.zeros((0, 12))
    m = np.arange(1, 13)
    inc = drivers["include"].fillna(True).astype(bool).to_numpy()
    start = _month_ints(drivers["start_month"], 1)
    end = np.maximum(_month_ints(drivers["end_month"], 12), start)
    amt = _num(drivers["amount"])
    basis = drivers["basis"].fillna("Per month").to_numpy()
    on = (m[None, :] >= start[:, None]) & (m[None, :] <= end[:, None])
    per_month = np.where(basis == "Per year", amt / (end - start + 1), amt)
    out = np.where(on, per_month[:, None], 0.0)
    one_time = basis == "One-time"
    out[one_time] = np.where(m[None, :] == start[one_time, None], amt[one_time, None], 0.0)
    return out * inc[:, None]


def overhead_annual(overhead: pd.DataFrame) -> np.ndarray:
    if overhead.empty:
        return np.zeros(0)
    prior = _num(overhead["prior_amount"])
    g = _num(overhead["growth_pct"])
    ov = pd.to_numeric(overhead["override_amount"], errors="coerce").to_numpy(dtype=float)
    budget = np.where(np.isnan(ov), prior * (1 + g), ov)
    return np.where(overhead["treatment"].to_numpy() == PRIOR_PLUS, budget, 0.0)


@dataclass
class BudgetResult:
    pnl: pd.DataFrame          # one row per P&L line: kind, group, line, Jan..Dec, Total, Prior year
    people: pd.DataFrame       # per-person annual summary
    kpis: dict


def compute(a: Assumptions, people: pd.DataFrame, overhead: pd.DataFrame, drivers: pd.DataFrame) -> BudgetResult:
    rev, sal, hrs = people_monthly(people, a)
    drv = drivers_monthly(drivers)
    ov_annual = overhead_annual(overhead)
    rows: list[dict] = []

    def add(kind, group, line, monthly, prior=np.nan):
        monthly = np.asarray(monthly, dtype=float)
        rows.append({"kind": kind, "group": group, "line": line, **dict(zip(MONTH_LABELS, monthly)),
                     "Total": monthly.sum(), "Prior year": prior})
        return monthly

    def prior_sum(mask):
        return float(_num(overhead.loc[mask, "prior_amount"]).sum()) if not overhead.empty else 0.0

    def ov_lines(section_names, group):
        total = np.zeros(12)
        if overhead.empty:
            return total
        mask = overhead["section"].isin(section_names) & (overhead["treatment"] == PRIOR_PLUS)
        for i in np.where(mask.to_numpy())[0]:
            r = overhead.iloc[i]
            label = r["line_item"] if not r["category"] else f"{r['category']}: {r['line_item']}"
            total += add("line", group, label, np.full(12, ov_annual[i] / 12), r["prior_amount"])
        return total

    def drv_lines(section, group):
        total = np.zeros(12)
        if drivers.empty:
            return total
        for i in np.where((drivers["section"] == section).to_numpy())[0]:
            if not bool(pd.Series([drivers.iloc[i]["include"]]).fillna(True).iloc[0]):
                continue
            total += add("driver", group, f"{drivers.iloc[i]['driver']}", drv[i])
        return total

    ov = overhead if not overhead.empty else pd.DataFrame(columns=OVERHEAD_COLUMNS)
    replaced_rev = (ov["section"] == "Revenue") & (ov["treatment"] == PEOPLE_PLAN)
    replaced_pay = ov["section"].isin(["COGS", "Expense"]) & (ov["treatment"] == PEOPLE_PLAN)

    # Revenue
    fee = add("line", "Revenue", "Fee revenue (people plan)", rev.sum(axis=0), prior_sum(replaced_rev))
    other_rev = ov_lines(["Revenue"], "Revenue") + drv_lines("Revenue", "Revenue")
    total_rev = add("total", "Revenue", "Total revenue", fee + other_rev,
                    prior_sum((ov["section"] == "Revenue") & (ov["treatment"] != EXCLUDE)) if not ov.empty else np.nan)

    # Cost of goods sold (if the P&L has any)
    cogs = ov_lines(["COGS"], "Cost of sales")
    if cogs.any():
        add("total", "Cost of sales", "Total cost of sales", cogs,
            prior_sum((ov["section"] == "COGS") & (ov["treatment"] == PRIOR_PLUS)))

    # Personnel
    salaries = add("line", "Personnel", "Salaries (people plan)", sal.sum(axis=0))
    fringe = add("line", "Personnel", f"Payroll taxes & benefits ({a.fringe_pct:.1%})", sal.sum(axis=0) * a.fringe_pct)
    pers_drv = drv_lines("Personnel", "Personnel")
    personnel = add("total", "Personnel", "Total personnel", salaries + fringe + pers_drv, prior_sum(replaced_pay))

    # Operating expenses
    opex = ov_lines(["Expense"], "Operating expenses") + drv_lines("Operating expense", "Operating expenses")
    add("total", "Operating expenses", "Total operating expenses", opex,
        prior_sum((ov["section"] == "Expense") & (ov["treatment"] == PRIOR_PLUS)))

    # Other income / expense
    oth_inc = ov_lines(["Other Income"], "Other income & expense") + drv_lines("Other income", "Other income & expense")
    oth_exp = ov_lines(["Other Expense"], "Other income & expense") + drv_lines("Other expense", "Other income & expense")

    total_exp = cogs + personnel + opex + oth_exp
    prior_net = prior_exp = np.nan
    if not ov.empty:
        used = ov["treatment"] != EXCLUDE
        inc_prior = prior_sum(used & ov["section"].isin(["Revenue", "Other Income"]))
        prior_exp = prior_sum(used & ov["section"].isin(["COGS", "Expense", "Other Expense"]))
        prior_net = inc_prior - prior_exp
    add("total", "Summary", "Total expenses", total_exp, prior_exp)
    net = add("result", "Summary", "Net income before owner draws", total_rev + oth_inc - total_exp, prior_net)

    draws = drv_lines("Owner draws", "Owner draws")
    add("total", "Owner draws", "Total owner draws", draws)
    after = add("result", "Owner draws", "Remaining after owner draws", net - draws)

    pnl = pd.DataFrame(rows)

    p_rev, p_sal = rev.sum(axis=1), sal.sum(axis=1) * (1 + a.fringe_pct)
    ppl = pd.DataFrame({
        "name": people["name"].to_numpy() if len(people) else [],
        "role": people["role"].to_numpy() if len(people) else [],
        "included": people["include"].fillna(False).astype(bool).to_numpy() if len(people) else [],
        "billable_hours": hrs.sum(axis=1), "revenue": p_rev, "salary_and_fringe": p_sal,
        "contribution": p_rev - p_sal,
    })
    ppl = ppl[ppl["included"]].drop(columns="included")
    total_rev_y = float(total_rev.sum())
    kpis = {
        "revenue": total_rev_y,
        "expenses": float(total_exp.sum()),
        "net_income": float(net.sum()),
        "net_margin": float(net.sum()) / total_rev_y if total_rev_y else 0.0,
        "owner_draws": float(draws.sum()),
        "after_draws": float(after.sum()),
        "headcount": int(people["include"].fillna(False).astype(bool).sum()) if len(people) else 0,
        "billable_hours": float(hrs.sum()),
        "prior_revenue": float(pnl.loc[pnl["line"] == "Total revenue", "Prior year"].iloc[0])
        if not ov.empty else np.nan,
        "prior_net_income": prior_net,
    }
    return BudgetResult(pnl=pnl, people=ppl, kpis=kpis)


# ---------------------------------------------------------------------------
# Saved inputs: reference/budget_<year>/ (gitignored -- names and pay)
# ---------------------------------------------------------------------------
def budget_dir(year: int) -> Path:
    return Path(config.BUDGET_DIR) / f"budget_{year}"


def save_inputs(a: Assumptions, people: pd.DataFrame, overhead: pd.DataFrame, drivers: pd.DataFrame) -> Path:
    d = budget_dir(a.year)
    d.mkdir(parents=True, exist_ok=True)
    (d / "assumptions.json").write_text(json.dumps(a.__dict__, indent=2))
    people.to_csv(d / "people.csv", index=False)
    overhead.to_csv(d / "overhead.csv", index=False)
    drivers.to_csv(d / "drivers.csv", index=False)
    return d


def load_inputs(year: int):
    """(assumptions, people, overhead, drivers) -- each None if not saved."""
    d = budget_dir(year)

    def csv(name, cols):
        f = d / name
        if not f.exists():
            return None
        df = pd.read_csv(f, dtype={"employee_number": str, "account_number": str})
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        for c in ("category", "account_number", "note", "person"):
            if c in df.columns:
                df[c] = df[c].fillna("").astype(str)
        return df[cols]

    a = None
    if (d / "assumptions.json").exists():
        raw = json.loads((d / "assumptions.json").read_text())
        a = Assumptions(**{k: v for k, v in raw.items() if k in Assumptions.__dataclass_fields__})
    return a, csv("people.csv", PEOPLE_COLUMNS), csv("overhead.csv", OVERHEAD_COLUMNS), csv("drivers.csv", DRIVER_COLUMNS)


def empty_drivers() -> pd.DataFrame:
    return pd.DataFrame(columns=DRIVER_COLUMNS).astype({"include": bool, "amount": float})


def guess_draw_drivers(gl: pd.DataFrame | None) -> pd.DataFrame:
    """Starter owner-draw drivers from the GL: equity accounts named like
    draws/distributions, at their last-12-months average monthly debits."""
    if gl is None or gl.empty:
        return empty_drivers()
    g = gl[(gl["account_type"] == "Equity")
           & gl["account_name"].str.contains(r"draw|distribution|guaranteed", case=False, na=False)].copy()
    if g.empty:
        return empty_drivers()
    g["period_end"] = pd.to_datetime(g["period_end"])
    g = g[g["period_end"] > g["period_end"].max() - pd.DateOffset(months=12)]
    months = max(g["period_end"].dt.to_period("M").nunique(), 1)
    by = g.groupby("account_name")["debits"].sum() / months
    return pd.DataFrame([{
        "include": True, "driver": name, "section": "Owner draws", "person": "",
        "amount": round(float(v), 2), "basis": "Per month", "start_month": 1, "end_month": 12,
        "note": f"GL average, last {months} months",
    } for name, v in by.items() if v > 0], columns=DRIVER_COLUMNS)
