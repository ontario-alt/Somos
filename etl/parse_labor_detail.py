"""
Parse a Vantagepoint labor (time) detail export -- one row per time
entry for the measuring period -- into a tidy transaction table. This is
the source behind the Measuring Period page's creditable-hours scorecard
(billable + capped pro bono, per person, by month) and its timekeeper /
practice-group profitability.

Why this export and not just "All Timekeepers Hours": that summary gives
one total per person per entity, so it can't tell pro bono time apart
from other credited time, can't show month-by-month pace, and carries no
dollars. Transaction-level labor detail answers all three.

What to run in Vantagepoint: a labor/time detail report (e.g. a Project
"Labor Detail" or "Time Analysis" report, or a saved timesheet search)
for 10/1 - 9/30 (or 10/1 - today mid-year), every employee, exported to
CSV or Excel with these columns (names are matched loosely; see
_ALIASES -- rename a header or add an alias here if yours differs):

    required: Employee (name), Transaction/Work Date, Project (matter)
              Number, Hours
    strongly recommended: Employee Number, Project Name, Billing Status,
              Labor Code, Company
    for profitability: Billing Extension (hours x bill rate), Billed
              Amount (what was actually invoiced), Cost Extension
              (hours x cost rate)

Rows without an employee, a parseable date, and numeric hours (group
headers, subtotals, grand totals) are skipped, so a grouped report
flattens fine as long as each detail row carries its own employee and
date.

Each row gets an `hours_category` per the firm's Promotion and Bonus
Policy (config.classify_time): client / foa / pro_bono / creditable /
other / time_off, decided by project name and labor code keywords plus
any exact overrides in config.TIME_CATEGORY_OVERRIDES (the policy's old
file numbers no longer apply). With no billing status column at all,
every row not otherwise classified counts as client time and a warning
is logged.

Output grain: one row per time entry:
    entity, employee_number, employee_name, name_key, transaction_date,
    matter_code, matter_name, labor_code, billing_status, hours,
    hours_category, is_billable, is_pro_bono, is_time_off, standard_value, billed_amount, cost_amount,
    source_file
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
from etl.common import find_all_files, name_key, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.labor_detail")

# Normalized header (lowercase, alphanumerics only) -> field. First match
# wins per field, so more specific names come first.
_ALIASES = {
    "employee_name": ["employeename", "employeefullname", "fullname", "timekeepername", "timekeeper", "employee", "name"],
    # Bare "Employee" is a name in some exports and a number in others --
    # employee_name claims it first only when there's no "Employee Name".
    "employee_number": ["employeenumber", "employeeid", "employeeno", "empnumber", "empno", "employee"],
    "transaction_date": ["transactiondate", "transdate", "workdate", "timesheetdate", "entrydate", "date"],
    "matter_code": ["projectnumber", "projectno", "projectid", "project", "wbs1", "mattercode", "matternumber", "matter"],
    "matter_name": ["projectname", "wbs1name", "mattername", "projectlongname"],
    "labor_code": ["laborcode", "laborcodename", "activity", "activitycode", "task"],
    "billing_status": ["billingstatus", "billstatus", "billable"],
    "hours": ["hours", "hoursworked", "reghours", "regularhours", "totalhours", "hrs"],
    "standard_value": ["billingextension", "billext", "billextension", "billingamount", "amountatbillingrate", "standardvalue", "value"],
    "billed_amount": ["billedamount", "billedextension", "billedext", "amountbilled", "billed", "invoicedamount"],
    "cost_amount": ["costextension", "costext", "laborcost", "costamount", "regularcost", "cost"],
    "entity": ["company", "companyname", "entity", "firm"],
}
_REQUIRED = ("employee_name", "transaction_date", "hours")
_BILLABLE_WORDS = {"billable", "yes", "y", "true"}
_NONBILLABLE_WORDS = {"nonbillable", "non-billable", "no", "n", "false"}


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def _map_header(header: list) -> dict[str, int]:
    normed = [_norm(h) for h in header]
    col_idx: dict[str, int] = {}
    used: set[int] = set()
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            hits = [i for i, h in enumerate(normed) if h == alias and i not in used]
            if hits:
                col_idx[field] = hits[0]
                used.add(hits[0])
                break
    return col_idx


def _read_grid(path: Path) -> list[list]:
    if path.suffix.lower() == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return grid
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f)]


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%m/%d/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _cell_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _cell_str(v)
    if not s:
        return None
    s = s.split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cell_num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return parse_money(_cell_str(v))


def _is_billable(status: str | None, has_status_col: bool) -> bool:
    if not has_status_col:
        return True
    s = (status or "").strip()
    if s.lower() in _BILLABLE_WORDS:
        return True
    if s.lower() in _NONBILLABLE_WORDS:
        return False
    return s.upper() in config.LABOR_BILLABLE_STATUS_CODES


# ---------------------------------------------------------------------------
# Vantagepoint "Employee Labor Detail" report, exported to CSV. It's a grouped
# report flattened to one row per time entry, with the grouping in columns:
#   groupHeader1_GroupColumn  "Employee: 018 Zuniga, Jonathan"
#   groupHeader2_GroupColumn  "Matter: LLP25-099 [Pro-Bono] General Real Estate"
#   groupHeader3/4            "Phase: ..." / "Task: ..." (optional)
#   detail_LaborCode          B / N
#   detail_TransDate, detail_TotalHrs, detail_TotalAmt (hours x bill rate)
# plus repeated subtotal columns (ignored). Checked against the All
# Timekeepers Hours export for FY2026: total hours reconcile exactly for
# every timekeeper. That export's "Billable" = all time on client matters
# (B or N), including client-numbered "[Pro-Bono] ..." matters; its
# "Credited" / "Not Credited" = the firm's overhead (OH) time files; PTO /
# holiday = the ZZZ time files. So here billable vs. not is decided by the
# matter (client matter vs. OH / ZZZ file), and policy categories by name.
# ---------------------------------------------------------------------------
_VP_EMP_RE = re.compile(r"^Employee:\s*(\S+)\s+(.*)$")
_VP_MATTER_RE = re.compile(r"^Matter:\s*(\S+)\s*(.*)$")
# Single entries this large are bad postings, not time (seen: one person
# with entries of -3,000 to -255,000 hours on 2/28/2026). Month-end
# summary postings of 30-120 hours on one matter are real and kept.
VP_ENTRY_HOURS_RANGE = config.VP_ENTRY_HOURS_RANGE


def _is_vp_grouped(grid: list[list]) -> int | None:
    for i, row in enumerate(grid[:10]):
        cells = [str(c or "") for c in row]
        if "groupHeader1_GroupColumn" in cells and "detail_TransDate" in cells:
            return i
    return None


def _vp_entity(code: str, name: str) -> str | None:
    if code.upper().startswith("ZZZ"):
        if "mexico" in name.lower():
            return "Somos Group Mexico"
        for suffix, ent in (("- LLC", "Somos Group LLC"), ("- LLP", "Somos Law Group LLP")):
            if name.strip().upper().endswith(suffix.upper()):
                return ent
        return None
    m = re.match(r"^([A-Z]+?)(?:OH)?\d", code.upper())
    return config.MATTER_CODE_ENTITY_PREFIXES.get(m.group(1)) if m else None


def _parse_vp_grouped(grid: list[list], header_row: int, path: Path) -> tuple[list[dict], list[dict]]:
    """(time entries, rejected entries) from the grouped Vantagepoint export."""
    hdr = [str(c or "") for c in grid[header_row]]
    ix = {h: i for i, h in enumerate(hdr)}

    def g(row, col):
        i = ix.get(col)
        return row[i] if i is not None and i < len(row) else None

    rows, rejected, skipped = [], [], 0
    lo, hi = VP_ENTRY_HOURS_RANGE
    for raw in grid[header_row + 1:]:
        emp = _VP_EMP_RE.match(_cell_str(g(raw, "groupHeader1_GroupColumn")))
        mat = _VP_MATTER_RE.match(_cell_str(g(raw, "groupHeader2_GroupColumn")))
        txn_date = _cell_date(g(raw, "detail_TransDate"))
        hours = _cell_num(g(raw, "detail_TotalHrs"))
        if not emp or not mat or txn_date is None or not hours:
            skipped += 1
            continue
        emp_no, emp_name = emp.group(1), emp.group(2).strip()
        code, mname = mat.group(1).strip(), mat.group(2).strip()
        flag = (_cell_str(g(raw, "detail_LaborCode")) or "").upper() or None
        amount = _cell_num(g(raw, "detail_TotalAmt"))
        phase = _cell_str(g(raw, "groupHeader3_GroupColumn")).replace("Phase:", "").strip() or None
        task = _cell_str(g(raw, "groupHeader4_GroupColumn")).replace("Task:", "").strip() or None
        base = {
            "entity": _vp_entity(code, mname), "employee_number": emp_no, "employee_name": emp_name,
            "name_key": name_key(emp_name), "transaction_date": txn_date, "matter_code": code,
            "matter_name": mname, "labor_code": flag, "billing_status": flag, "hours": hours,
            "phase": phase, "task": task,
        }
        if not (lo <= hours <= hi):
            rejected.append({**base, "billed_amount": amount, "source_file": path.name,
                             "reason": f"entry of {hours:,.2f} hours is outside {lo:,.0f} to {hi:,.0f}"})
            continue
        client_matter = "OH" not in code.upper() and not code.upper().startswith("ZZZ")
        category = config.classify_time(code, mname, None, client_matter)
        rows.append({
            **base,
            "hours_category": category,
            "is_billable": category in ("client", "foa"),
            "is_pro_bono": category == "pro_bono",
            "is_time_off": category == "time_off",
            # detail_TotalAmt is hours x bill rate (median ~$605/hr checked) --
            # the billing value of the time, not what was invoiced.
            "standard_value": amount if client_matter else None,
            "billed_amount": None,
            "cost_amount": None,
            "source_file": path.name,
        })
    if rejected:
        by_person: dict[str, float] = {}
        for r in rejected:
            by_person[r["employee_name"]] = by_person.get(r["employee_name"], 0.0) + r["hours"]
        logger.warning("%s: %d entries rejected as bad postings (hours outside %s): %s", path.name, len(rejected),
                       VP_ENTRY_HOURS_RANGE, {k: round(v, 1) for k, v in by_person.items()})
    logger.info("%s: Vantagepoint grouped labor detail -- %d entries, %d non-entry rows skipped", path.name, len(rows), skipped)
    return rows, rejected


_LAST_REJECTED: list[dict] = []


def _parse_one(path: Path) -> list[dict]:
    logger.info("Parsing labor detail export: %s", path)
    grid = _read_grid(path)
    vp_hdr = _is_vp_grouped(grid)
    if vp_hdr is not None:
        rows, rejected = _parse_vp_grouped(grid, vp_hdr, path)
        _LAST_REJECTED.extend(rejected)
        _log_categories(rows, path)
        return rows

    # Report title/criteria lines often precede the real header -- take
    # the first row (within the first 25) that maps every required field.
    header_row, col_idx = None, {}
    for i, row in enumerate(grid[:25]):
        mapped = _map_header(row)
        if all(f in mapped for f in _REQUIRED):
            header_row, col_idx = i, mapped
            break
    if header_row is None:
        logger.warning(
            "Skipping %s: couldn't find a header row with employee, date and hours columns "
            "(add the export's header names to _ALIASES in parse_labor_detail.py)",
            path.name,
        )
        return []
    missing = [f for f in ("employee_number", "matter_code", "billing_status", "standard_value") if f not in col_idx]
    if missing:
        logger.warning("%s has no %s column(s) -- related figures will be blank or assumed", path.name, missing)

    has_status = "billing_status" in col_idx

    def get(row, field):
        idx = col_idx.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    rows: list[dict] = []
    skipped = 0
    for raw in grid[header_row + 1 :]:
        name = _cell_str(get(raw, "employee_name"))
        txn_date = _cell_date(get(raw, "transaction_date"))
        hours = _cell_num(get(raw, "hours"))
        if not name or txn_date is None or hours is None or name.lower().startswith(("total", "grand total")):
            skipped += 1
            continue
        matter_code = _cell_str(get(raw, "matter_code"))
        matter_name = _cell_str(get(raw, "matter_name"))
        labor_code = _cell_str(get(raw, "labor_code"))
        status = _cell_str(get(raw, "billing_status")) or None
        category = config.classify_time(matter_code, matter_name, labor_code, _is_billable(status, has_status))
        rows.append(
            {
                "entity": _cell_str(get(raw, "entity")) or None,
                "employee_number": _cell_str(get(raw, "employee_number")) or None,
                "employee_name": name,
                "name_key": name_key(name),
                "transaction_date": txn_date,
                "matter_code": matter_code or None,
                "matter_name": matter_name or None,
                "labor_code": labor_code or None,
                "billing_status": status,
                "hours": hours,
                "hours_category": category,
                # Convenience flags (client chargeable, incl. FOA; pro bono; time off).
                "is_billable": category in ("client", "foa"),
                "is_pro_bono": category == "pro_bono",
                "is_time_off": category == "time_off",
                "standard_value": _cell_num(get(raw, "standard_value")),
                "billed_amount": _cell_num(get(raw, "billed_amount")),
                "cost_amount": _cell_num(get(raw, "cost_amount")),
                "source_file": path.name,
            }
        )

    if not has_status:
        logger.warning(
            "%s has no billing status column -- every client-matter row is being counted as "
            "billable. Add Billing Status to the export so non-billable time is excluded.",
            path.name,
        )
    logger.info("Parsed %d time entries from %s (%d non-detail rows skipped)", len(rows), path.name, skipped)
    _log_categories(rows, path)
    return rows


def _log_categories(rows: list[dict], path: Path):
    by_cat: dict[str, float] = {}
    for r in rows:
        by_cat[r["hours_category"]] = by_cat.get(r["hours_category"], 0.0) + r["hours"]
    logger.info("%s hours by policy category: %s", path.name, {k: round(v, 1) for k, v in sorted(by_cat.items())})


def rejected_entries() -> list[dict]:
    """Entries the last parse() rejected as bad postings (see VP_ENTRY_HOURS_RANGE)."""
    return list(_LAST_REJECTED)


def parse(paths: list[Path] | None = None) -> list[dict]:
    """Every matching file is read. When two files cover the same dates
    (e.g. a fresh FY-to-date pull alongside last month's), the newer file
    wins for every date it covers, so re-exporting never double-counts."""
    paths = paths if paths is not None else find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["labor_detail"])
    _LAST_REJECTED.clear()
    if not paths:
        return []
    by_file = [(p, _parse_one(p)) for p in paths]  # oldest -> newest by mtime
    covered: set = set()
    out: list[dict] = []
    for _, rows in reversed(by_file):
        dates = {r["transaction_date"] for r in rows}
        out.extend(r for r in rows if r["transaction_date"] not in covered)
        covered |= dates
    # The grouped Vantagepoint export adds phase/task; give every row the same keys.
    keys = list(dict.fromkeys(k for r in out for k in r))
    return [{k: r.get(k) for k in keys} for r in out]


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No labor detail rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "labor_detail.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    print(f"{len(rows)} time entries, {len({r['name_key'] for r in rows})} timekeepers")
