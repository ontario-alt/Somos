"""
Central configuration for the Somos Group executive dashboard.

Nothing in etl/ or dashboard/ should hard-code a path, entity name, or
fiscal-year constant -- it all lives here so the bookkeeping team can
repoint the app at a new OneDrive sync folder, add an entity, or update
a target without touching any parsing or chart code.
"""
from pathlib import Path
import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# RAW_DATA_DIR is NOT managed by this app. It should point at the local
# folder OneDrive syncs from the SharePoint location where the bookkeeping
# team drops Vantagepoint exports. Override via the SOMOS_RAW_DIR env var
# (e.g. in a .env or shell profile) without editing this file, or just
# change the default below.
RAW_DATA_DIR = Path(
    os.environ.get("SOMOS_RAW_DIR", Path(__file__).parent / "data" / "raw")
).expanduser()

# Tidy, parsed output -- one file per source. Safe for this app to manage
# (created/overwritten on every ETL run).
PROCESSED_DATA_DIR = Path(
    os.environ.get("SOMOS_PROCESSED_DIR", Path(__file__).parent / "data" / "processed")
).expanduser()

# The combined queryable warehouse the dashboard reads from.
WAREHOUSE_PATH = Path(
    os.environ.get("SOMOS_WAREHOUSE_PATH", PROCESSED_DATA_DIR / "warehouse.duckdb")
).expanduser()

# ---------------------------------------------------------------------------
# Source file discovery
# ---------------------------------------------------------------------------
# Vantagepoint exports land in RAW_DATA_DIR with a version-y filename
# (e.g. "AR_Aging_1.csv", "WIP_Report_Last_Month_3.csv") that changes every
# time someone re-exports. Each parser picks the newest file (by mtime)
# matching its glob pattern rather than a fixed filename. Update these
# patterns if the bookkeeping team's export naming convention changes.
SOURCE_FILE_PATTERNS = {
    # CSV only -- this is the raw Vantagepoint invoice-level export
    # (parse_ar.py only reads CSV). The "Somos_AR_Aging_*.xlsx" workbook
    # below matches "*AR*Aging*" too but is a different report entirely
    # (ar_aging_workbook), so it's deliberately excluded here rather than
    # risking parse_ar.py picking it as its "newest" file and choking on
    # a binary xlsx read as CSV.
    "ar_aging": ["*AR*Aging*.csv"],
    # The hand-built multi-tab workbook (Summary / Week Over Week / AR
    # Aging Detail / Priority Board / Client Rollup) that defined this
    # app's own weekly AR page -- see parse_ar_aging_workbook.py. Scoped
    # to the "Somos_AR_Aging_" naming so it doesn't collide with the
    # ar_aging pattern above or with ar_detail's "All AR Report" exports.
    "ar_aging_workbook": ["*Somos*AR*Aging*.xlsx"],
    "ap_aging": ["*AP*Aging*.csv", "*AP*Aging*.xlsx", "*Accounts*Payable*.xlsx", "*Accounts*Payable*.csv"],
    "wip": ["*WIP*.csv", "*WIP*.xlsx"],
    "earnings": ["*Earnings*.csv", "*Earnings*.xlsx"],
    # Vantagepoint trial balances are run per entity, so a real refresh
    # will likely have one file per entity matching this pattern --
    # parse_gl.py reads all matches, not just the newest.
    # Same report, two names seen in practice: "Trial Balance" and
    # "GL Report" (the latter is this firm's saved-favorite name for it).
    "gl_trial_balance": ["*Trial*Balance*.csv", "*Trial*Balance*.xlsx", "*GL*Report*.xlsx", "*GL*Report*.csv"],
    "cash_receipts": ["*Receipts*.csv", "*Receipts*.xlsx"],
    "cash_disbursements": ["*Disbursements*.csv", "*Disbursements*.xlsx"],
    "originations": ["*Origination*.xlsx", "*Origination*.csv"],
    # Vantagepoint's "All AR Report" -- matter-level with an explicit
    # client field, unlike ar_aging above. Only seen as PDF so far;
    # ask for a CSV/Excel export if this pattern ever needs updating.
    # "All AR Report" -- prefer .xlsx (real cells) over .pdf (position-based
    # column recovery) when both cover the same "Aged as of" date; see
    # parse_ar_detail.py for how that preference is applied.
    "ar_detail_xlsx": ["*All*AR*.xlsx", "*AR*All*Compan*.xlsx"],
    "ar_detail_pdf": ["*All*AR*Report*.pdf"],
    # Matter master list -- matter code, name, client, and an
    # "Organization Name" field that doubles as a practice-group/
    # department taxonomy (e.g. "LLC Planning", "LLP Legal").
    "matter_list": ["*Matter*List*.xlsx"],
    # "Gone But Not Forgotten" -- old collectibles tracked separately from
    # the regular AR aging book. See parse_gbnf.py: deliberately its own
    # table, never merged into ar_aging_detail's "oldest"/Over 120 totals.
    "gbnf": ["*GBNF*.xlsx"],
    # Per-employee, per-entity hours for the current measuring period
    # (fiscal year) -- see parse_timekeeper_hours.py. Scoped to "All
    # Timekeepers Hours" specifically so it doesn't also pick up the
    # separate (non-entity-split) "Timekeeper Hours Summary" export.
    "timekeeper_hours": ["*All*Timekeepers*Hours*.csv"],
    # Monthly billed-activity-by-client export (distinct from AR balance
    # and from cash receipts -- see etl/parse_ar_summary.py).
    "ar_summary": ["*AR*Summary*.csv", "*AR*Summary*.xlsx"],
    "employee_cost": ["*Employee*Cost*Rate*.xlsx"],
    # Transaction-level labor (time) detail for the measuring period --
    # one row per time entry: employee, date, project/matter, labor
    # code, hours, billing status, and billing/cost extensions. Powers
    # the Measuring Period page's creditable-hours scorecard (billable +
    # capped pro bono), monthly pace, and timekeeper / practice-group
    # profitability. See etl/parse_labor_detail.py.
    "labor_detail": ["*Labor*Detail*.csv", "*Labor*Detail*.xlsx", "*Time*Analysis*.csv", "*Time*Analysis*.xlsx"],
    "nte_tracking": ["*NTE*Tracking*.xlsx"],
}

# The NTE Tracking Report only covers matters billed against a
# not-to-exceed cap (a "Records Selected" filter in Vantagepoint,
# confirmed: 42 of the ~315 matters in the matter list) -- real
# revenue/profit data, but for a subset of the portfolio, not the whole
# thing. Not a coverage gap to fix with more of this export: flat-fee
# and T&E matters are never NTE-capped in the first place, so most of
# the portfolio structurally can't appear here. Keep this in one place
# so every page that surfaces matter_earnings can caption it consistently.
MATTER_EARNINGS_IS_PARTIAL = True

# Red/Yellow/Green collections priority, matching the bookkeeping team's
# own weekly AR report: Red = an over-90 balance at or above this
# threshold; Yellow = aged past 60 days but below it; Green = nothing
# aged past 60 days. Single input -- every weekly AR view recalculates
# from this.
AR_RED_THRESHOLD = 25_000.00

# ---------------------------------------------------------------------------
# Entities (billing companies within the Somos Group family)
# ---------------------------------------------------------------------------
# Seeded from what's visible in the sample WIP export. Add/remove entries
# as new billing companies show up -- dashboard pages read this list to
# order/label the "by entity" breakdowns rather than discovering entities
# ad hoc from whatever happens to be in the current export.
ENTITIES = [
    "Somos Group LLC",
    "Somos Law Group LLP",
    "Somos Group Mexico",
]

# The AR aging export has no entity/company column, only a matter code
# (e.g. "LLC25-002", "LLP26-086"). The prefix matches the WIP export's
# company field, so parse_ar.py derives entity from it. Update this map
# if a new matter-code prefix / entity shows up.
MATTER_CODE_ENTITY_PREFIXES = {
    "LLC": "Somos Group LLC",
    "LLP": "Somos Law Group LLP",
    "MEX": "Somos Group Mexico",
}

# The AP export's "Liability Code" and "Voucher BankCode" columns are
# another entity signal (seen: "PWP-LLC"/"PWP-LLP", "LLC"/"LLP"/
# "BILLLLC"/"BILLLLP") for rows where the matter code doesn't resolve
# (payment lines have no matter; overhead vouchers use a placeholder
# matter like "ZZZ00-100"). parse_ap.py checks matter code first, then
# falls back to whichever of these contains "LLC" or "LLP".
AP_ENTITY_CODE_SUFFIXES = {
    "LLC": "Somos Group LLC",
    "LLP": "Somos Law Group LLP",
}

# ---------------------------------------------------------------------------
# GL account type, derived from the leading digit of the account number
# (standard chart-of-accounts convention seen in the trial balance
# export: 1=Asset, 2=Liability, 3=Equity, 4=Revenue, 5=COGS, 6-9=Expense).
# Update if Somos's chart of accounts uses a different convention.
# ---------------------------------------------------------------------------
GL_ACCOUNT_TYPE_PREFIXES = {
    "1": "Asset",
    "2": "Liability",
    "3": "Equity",
    "4": "Revenue",
    "5": "COGS",
    "6": "Expense",
    "7": "Expense",
    "8": "Expense",
    "9": "Expense",
}

# ---------------------------------------------------------------------------
# Fiscal year
# ---------------------------------------------------------------------------
FISCAL_YEAR_START_MONTH = 10  # October
FISCAL_YEAR_START_DAY = 1


def fiscal_year_bounds(as_of) -> tuple:
    """(start, end) dates of the fiscal year containing `as_of`, per
    FISCAL_YEAR_START_MONTH/DAY above. Used by the Measuring Period page."""
    import datetime

    fy_start_this_year = datetime.date(as_of.year, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY)
    start = fy_start_this_year if as_of >= fy_start_this_year else datetime.date(
        as_of.year - 1, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY
    )
    end = datetime.date(start.year + 1, FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY) - datetime.timedelta(days=1)
    return start, end

# ---------------------------------------------------------------------------
# AR aging bucket labels, oldest-last, matching column order in the
# Vantagepoint AR aging export (column headers are rolling date ranges,
# e.g. "Total 8/16/2026 - 9/15/2026", so we rename positionally to these
# fixed, sortable labels).
# ---------------------------------------------------------------------------
AGING_BUCKETS = ["current_0_30", "days_31_60", "days_61_90", "days_91_120", "over_120"]
AGING_FLAG_THRESHOLDS = (90, 120)  # days -- weekly page flags new items crossing these

# ---------------------------------------------------------------------------
# Measuring-period hour targets (firm policy). The measuring period is
# the fiscal year above (Oct 1 - Sep 30). Each hours-required timekeeper
# has a role -- attorney or planner -- and an annual creditable-hour
# target for that role. Update the numbers here once; every page that
# shows targets recalculates.
#
# Creditable hours = billable hours + pro bono hours, with pro bono
# capped at PRO_BONO_CREDIT_CAP per person per measuring period (hours
# above the cap are still reported, just not credited).
#
# Targets are prorated for leave and for partial-year employment:
#   prorated target = annual target x available workdays / FY workdays
# where available workdays = Mon-Fri days inside the person's
# employment window (start_date/end_date in employee_targets.csv), less
# approved leave from reference/leave.csv (weighted by percent_away, so
# a 50% reduced schedule counts as half a day away). Ordinary PTO and
# firm holidays do NOT reduce the target -- the annual number already
# assumes them.
# ---------------------------------------------------------------------------
BILLABLE_HOUR_TARGETS = {
    "Attorney": 1900,
    "Planner": 1600,
}
# Earlier versions of reference/employee_targets.csv used the entity
# abbreviation as the target type (LLP = law group = attorneys, LLC =
# planning = planners). Still accepted so an existing file keeps working.
TARGET_TYPE_ALIASES = {
    "LLP": "Attorney",
    "LLC": "Planner",
}
PRO_BONO_CREDIT_CAP = 75
# Whether the 75-hour cap itself shrinks for someone on leave (e.g. a
# half-year leave -> 37.5 creditable pro bono hours). Policy says targets
# are prorated; it's silent on the cap, so it's left whole by default.
PRO_BONO_CAP_PRORATED = False

# How pro bono time is recognized in the labor detail export: a matter
# code listed here, or a matter name / labor code matching the pattern.
# Add the firm's pro bono project numbers here if they aren't named
# "Pro Bono ..." in Vantagepoint.
PRO_BONO_MATTER_CODES: list[str] = []
PRO_BONO_NAME_PATTERN = r"pro[\s\-]*bono"

# Vantagepoint billing status codes that count as billable hours worked.
# B = billable, H = held, F = final billed, T = transferred. Written-off
# time (W/X) is excluded by default -- move them in here if the firm
# credits written-off hours toward the target.
LABOR_BILLABLE_STATUS_CODES = {"B", "H", "F", "T"}

# Pace status bands on creditable hours vs. expected-to-date (the
# prorated target scaled to how much of the person's available time has
# elapsed): >= first value is On Track, >= second is Watch, else Behind.
PACE_STATUS_THRESHOLDS = (0.95, 0.85)

# Hand-maintained reference files (employee_targets.csv, leave.csv) --
# override the folder with SOMOS_REFERENCE_DIR, e.g. to keep them in the
# same SharePoint folder as the exports.
REFERENCE_DIR = Path(
    os.environ.get("SOMOS_REFERENCE_DIR", Path(__file__).parent / "reference")
).expanduser()
LEAVE_PATH = REFERENCE_DIR / "leave.csv"


def resolve_role(target_type: str | None) -> str | None:
    """Normalize an employee_targets.csv target_type ("Attorney",
    "planner", legacy "LLP", ...) to a BILLABLE_HOUR_TARGETS key, or None."""
    if not target_type:
        return None
    t = str(target_type).strip()
    t = TARGET_TYPE_ALIASES.get(t.upper(), t)
    for role in BILLABLE_HOUR_TARGETS:
        if role.lower() == t.lower():
            return role
    return None


# Not every employee has a billable-hour target (executives, admin team
# members, consultants/contractors typically don't). Rather than
# guessing who's exempt, reference/employee_targets.csv is a plain,
# hand-maintained file -- one row per employee, a `target_type` column
# that's one of BILLABLE_HOUR_TARGETS' keys ("Attorney"/"Planner") or
# blank for no target, plus optional start_date/end_date for anyone who
# joined or left mid-period. (Not "config/" -- that would collide with this file,
# config.py, as a package name.) etl/parse_employee_targets.py
# auto-generates a starter version (every employee currently in
# employee_cost_rates, target_type blank) the first time it's needed if
# the file doesn't exist yet -- fill it in and re-run
# build_warehouse.py; it won't be overwritten once it exists.
EMPLOYEE_TARGETS_PATH = REFERENCE_DIR / "employee_targets.csv"

# ---------------------------------------------------------------------------
# Targets (fill in as the firm sets them; used by the Measuring Period page)
# ---------------------------------------------------------------------------
ORIGINATION_TARGETS = {
    # "Attorney Name": 500_000.00,
}
