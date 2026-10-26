"""
Parse Insperity (the firm's PEO) payroll exports for the Budget page:
actual salaries, and what each person really costs on top of salary
(employer taxes, benefits, workers' comp, Insperity's fees).

Not built from a real sample yet, so columns are matched by name and the
report type is detected from its headers. Two kinds are read:

1. **Roster / compensation report** (one row per employee, no pay dates):
   name, employee ID, pay type (salary/hourly), annual salary or pay rate,
   pay frequency, status, hire/termination date, department.
   -> table `insperity_roster`
2. **Payroll register / invoice detail** (one row per employee per pay
   date): gross wages, employer taxes, employer benefits, workers' comp,
   Insperity service fees.
   -> table `insperity_payroll`

Employee-side deductions and withholdings (EE medical, federal withholding,
net pay, ...) are ignored -- only employer cost counts toward the budget.
Every run logs which columns were mapped to what, so the first real export
can be checked against Insperity's own totals.

CSV or Excel; every sheet is read; the header row is found by scanning the
top rows for a name column plus a salary/rate or gross-wages column.

Output grain:
    insperity_roster:  employee_id, employee_name, name_key, pay_type,
                       annual_salary, pay_rate, pay_frequency, status,
                       hire_date, term_date, department, source_file
    insperity_payroll: employee_id, employee_name, name_key, check_date,
                       gross_wages, employer_taxes, employer_benefits,
                       workers_comp, peo_fees, source_file
"""
from __future__ import annotations

import csv
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_all_files, name_key, parse_money

logger = logging.getLogger("somos.etl.insperity")


def _norm(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9#()%/ ]", " ", str(h or "").lower())).strip()


# Exact-ish header names per field (normalized). First match wins.
_FIELDS = {
    "employee_name": ["employee name", "name", "employee", "full name", "worksite employee", "associate name", "employee full name"],
    "last_name": ["last name", "last"],
    "first_name": ["first name", "first"],
    "employee_id": ["employee id", "emp id", "employee #", "employee number", "ee id", "ee #", "file number", "id", "employee no"],
    "pay_type": ["pay type", "pay basis", "salary/hourly", "salary hourly", "rate type", "flsa status", "comp type", "pay class"],
    "annual_salary": ["annual salary", "annual rate", "annual pay", "annualized salary", "annual compensation",
                      "annual base", "annual base salary", "annualized pay", "annual amount", "salary"],
    "pay_rate": ["pay rate", "rate", "hourly rate", "base rate", "current rate", "rate amount", "base pay rate"],
    "pay_frequency": ["pay frequency", "frequency", "pay period", "pay cycle"],
    "status": ["status", "employment status", "employee status"],
    "hire_date": ["hire date", "original hire date", "date of hire", "start date"],
    "term_date": ["termination date", "term date", "separation date", "end date"],
    "department": ["department", "dept", "division", "cost center", "location"],
    "check_date": ["check date", "pay date", "payroll date", "period end date", "pay period end", "period end",
                   "invoice date", "date"],
    "gross_wages": ["gross wages", "gross pay", "gross", "total gross", "gross earnings", "total earnings",
                    "gross amount", "wages"],
}

# Employer-cost columns, matched by keyword (a payroll register has many).
_EMPLOYEE_SIDE = re.compile(r"\b(ee|employee|withh|w/h|net pay|net|deduct|garnish|ded)\b")
_EMPLOYER_SIDE = re.compile(r"\b(er|employer|company|co)\b")
_TAX = re.compile(r"tax|fica|medicare|social security|oasdi|futa|suta|sui\b|sdi\b|unemploy")
_BENEFIT = re.compile(r"benefit|medical|dental|vision|health|401|retire|match|life|ltd|std|disab|hsa|fsa|insur")
_WC = re.compile(r"workers comp|worker s comp|work comp|\bwc\b|workers compensation")
_FEE = re.compile(r"service fee|admin|peo fee|insperity fee|professional fee|\bfee\b|fees")
_TOTAL = re.compile(r"^total\b|grand total|invoice total")


def _employer_bucket(h: str) -> str | None:
    """Which employer-cost bucket a header belongs to, or None."""
    if _TOTAL.search(h) and not re.search(r"tax|benefit", h):
        return None
    if _WC.search(h):
        return "workers_comp"
    if _FEE.search(h) and not _EMPLOYEE_SIDE.search(h):
        return "peo_fees"
    employer = bool(_EMPLOYER_SIDE.search(h))
    employee = bool(_EMPLOYEE_SIDE.search(h))
    if employee and not employer:
        return None
    if re.search(r"\bfuta\b|\bsuta\b|\bsui\b|unemploy", h):
        return "employer_taxes"  # unemployment taxes are employer-only
    if _TAX.search(h):
        # "Employer Taxes" / "ER FICA" / an invoice's plain "Taxes" column.
        return "employer_taxes" if employer or h in ("taxes", "payroll taxes", "total taxes", "employer taxes") else None
    if _BENEFIT.search(h):
        if re.search(r"match|employer paid|company paid", h):
            return "employer_benefits"
        return "employer_benefits" if employer or h in ("benefits", "benefit cost", "benefits cost", "total benefits") else None
    return None


def _map_header(cells: list) -> dict:
    """{field: col index} plus {'_employer': {col: bucket}}."""
    heads = [_norm(c) for c in cells]
    mapping: dict = {}
    used: set[int] = set()
    for field, names in _FIELDS.items():
        for name in names:
            for i, h in enumerate(heads):
                if i not in used and h == name:
                    mapping[field] = i
                    used.add(i)
                    break
            if field in mapping:
                break
    employer = {}
    for i, h in enumerate(heads):
        if i in used or not h:
            continue
        b = _employer_bucket(h)
        if b:
            employer[i] = b
    mapping["_employer"] = employer
    return mapping


def _is_header(m: dict) -> bool:
    has_name = "employee_name" in m or ("last_name" in m and "first_name" in m)
    return has_name and any(k in m for k in ("annual_salary", "pay_rate", "gross_wages"))


def _to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _money(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return parse_money(str(v))


_PERIODS = {"weekly": 52, "week": 52, "biweekly": 26, "bi weekly": 26, "every other week": 26,
            "semimonthly": 24, "semi monthly": 24, "monthly": 12, "annual": 1, "annually": 1, "yearly": 1}


def _annualize(pay_type: str, rate: float | None, frequency: str) -> float | None:
    """Annual salary from a pay rate when the report has no annual column."""
    if rate is None or rate <= 0:
        return None
    t = (pay_type or "").lower()
    f = _norm(frequency).replace("-", " ")
    if "hour" in t or rate < 500:
        return rate * 2080
    if rate >= 20000:
        return rate  # already annual
    periods = next((n for k, n in _PERIODS.items() if f == k or f.startswith(k)), None)
    return rate * periods if periods else None


def _rows_from_file(path: Path):
    """Yield (sheet name, list of row lists) for each sheet."""
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            yield path.stem, list(csv.reader(f))
        return
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]


def _parse_table(rows: list[list], path: Path, sheet: str):
    header_i, m = None, None
    for i, r in enumerate(rows[:40]):
        mm = _map_header(r)
        if _is_header(mm):
            header_i, m = i, mm
            break
    if header_i is None:
        return [], []
    heads = rows[header_i]
    kind = "payroll" if "gross_wages" in m and "check_date" in m else "roster"
    logger.info(
        "Insperity %s / %s: %s report; columns %s; employer cost columns %s",
        path.name, sheet, kind,
        {k: heads[v] for k, v in m.items() if k != "_employer"},
        {heads[c]: b for c, b in m["_employer"].items()},
    )

    def get(r, field):
        i = m.get(field)
        return r[i] if i is not None and i < len(r) else None

    roster, payroll = [], []
    for r in rows[header_i + 1:]:
        if not any(v not in (None, "") for v in r):
            continue
        name = get(r, "employee_name")
        if not name and "last_name" in m:
            last, first = get(r, "last_name"), get(r, "first_name")
            name = f"{first or ''} {last or ''}".strip() if (last or first) else None
        if not name or not isinstance(name, str) or _TOTAL.search(_norm(name)) or _norm(name) in ("total", "totals"):
            continue
        name = name.strip()
        emp_id = get(r, "employee_id")
        emp_id = str(int(emp_id)) if isinstance(emp_id, float) and emp_id.is_integer() else (str(emp_id).strip() if emp_id not in (None, "") else None)
        base = {"employee_id": emp_id, "employee_name": name, "name_key": name_key(name)}
        if kind == "payroll":
            d = _to_date(get(r, "check_date"))
            gross = _money(get(r, "gross_wages"))
            if d is None or gross is None:
                continue
            costs = {"employer_taxes": 0.0, "employer_benefits": 0.0, "workers_comp": 0.0, "peo_fees": 0.0}
            for c, b in m["_employer"].items():
                v = _money(r[c]) if c < len(r) else None
                if v:
                    costs[b] += v
            payroll.append({**base, "check_date": d, "gross_wages": gross, **costs, "source_file": path.name})
        else:
            pay_type = str(get(r, "pay_type") or "")
            rate = _money(get(r, "pay_rate"))
            annual = _money(get(r, "annual_salary"))
            freq = str(get(r, "pay_frequency") or "")
            if annual is None or annual <= 0:
                annual = _annualize(pay_type, rate, freq)
            roster.append({
                **base, "pay_type": pay_type or None, "annual_salary": annual, "pay_rate": rate,
                "pay_frequency": freq or None, "status": str(get(r, "status") or "") or None,
                "hire_date": _to_date(get(r, "hire_date")), "term_date": _to_date(get(r, "term_date")),
                "department": str(get(r, "department") or "") or None, "source_file": path.name,
            })
    return roster, payroll


def parse(raw_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
    """(roster rows, payroll rows). The roster comes from the newest roster
    file only (it's a point-in-time list); payroll rows from every file,
    newest file winning for a pay date it shares with an older one."""
    raw_dir = raw_dir or config.RAW_DATA_DIR
    files = [f for f in find_all_files(raw_dir, config.SOURCE_FILE_PATTERNS["insperity"]) if not f.name.startswith("~$")]
    if not files:
        logger.info("No Insperity export found in %s (patterns: %s)", raw_dir, config.SOURCE_FILE_PATTERNS["insperity"])
        return [], []
    rosters: list[tuple[Path, list]] = []
    payroll: list[dict] = []
    for path in files:
        file_roster, file_payroll = [], []
        try:
            for sheet, rows in _rows_from_file(path):
                ro, pa = _parse_table(rows, path, sheet)
                file_roster += ro
                file_payroll += pa
        except Exception as e:  # noqa: BLE001 -- one bad file shouldn't stop the build
            logger.warning("Skipping %s: %s", path.name, e)
            continue
        if not file_roster and not file_payroll:
            logger.warning("%s: no employee/salary or employee/gross-wages header found -- check the layout", path.name)
        if file_roster:
            rosters.append((path, file_roster))
        payroll += file_payroll

    roster = rosters[-1][1] if rosters else []
    latest = {}
    for r in payroll:
        latest[r["check_date"]] = r["source_file"]
    payroll = [r for r in payroll if latest[r["check_date"]] == r["source_file"]]
    if roster:
        logger.info("Insperity roster: %d employees, total annual salary %s", len(roster),
                    f"{sum(r['annual_salary'] or 0 for r in roster):,.0f}")
    if payroll:
        gross = sum(r["gross_wages"] for r in payroll)
        extra = sum(r["employer_taxes"] + r["employer_benefits"] + r["workers_comp"] + r["peo_fees"] for r in payroll)
        logger.info("Insperity payroll: %d rows, %s to %s, gross %s, employer cost on top %s (%.1f%%)",
                    len(payroll), min(r["check_date"] for r in payroll), max(r["check_date"] for r in payroll),
                    f"{gross:,.0f}", f"{extra:,.0f}", 100 * extra / gross if gross else 0)
    return roster, payroll


def write_processed(roster: list[dict], payroll: list[dict]) -> None:
    for rows, name in ((roster, "insperity_roster.csv"), (payroll, "insperity_payroll.csv")):
        if not rows:
            continue
        out = config.PROCESSED_DATA_DIR / name
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        logger.info("Wrote %d rows -> %s", len(rows), out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parse()
