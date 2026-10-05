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
    # The firm's hand-built "Monthly Hours Report by Timekeeper" workbook
    # (one tab per timekeeper: requirement header + one row per month).
    # Backfills closed measuring periods -- see parse_monthly_hours_workbook.py.
    "monthly_hours_workbook": ["*Monthly*Hours*Report*.xlsx"],
    # The firm's "Billing Hours Analysis" workbook -- its "FY20xx — Monthly
    # Billable" tabs backfill billable-only history (e.g. FY2025). See
    # parse_billing_hours_analysis.py.
    "billing_hours_analysis": ["*Billing*Hours*Analysis*.xlsx"],
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
# Measuring-period hours policy -- from the firm's "Promotion and Bonus
# Policy" (last updated 1/15/2023). The measuring period is the fiscal
# year above (Oct 1 - Sep 30). Update the numbers here once; every page
# recalculates.
#
# Hour categories (classified per time entry -- see classify_time()):
#   client     client-chargeable hours                         all count
#   foa        Firm's Own Account                              all count
#   pro_bono   approved Indigent / Non-Indigent Pro Bono       all count
#   creditable Creditable Non-Billable (recruiting, CLE, ...)  capped at 75
#   other      other non-billable (meetings, admin, B&C, ...)  don't count
#   time_off   PTO / sick / holiday                     never count (firm rule)
#
# Three tests per person, each with its own annual requirement:
#   Hours Expectation  client + FOA + pro bono + capped creditable
#                      >= 1900 Associates (attorneys) / 1600 Planners &
#                      Project Specialists. Drives promotion; promotion
#                      in exceptional years needs a 2-year average >= 90%.
#   Total Activity     all chargeable + non-chargeable (creditable and
#                      not), excluding PTO/sick/holiday, >= 2200 / 1800.
#   Bonus Threshold    client + FOA + capped creditable (pro bono NOT
#                      included) >= 1850 / 1550 to be eligible for an
#                      hours bonus; once met, pro bono is added back.
#
# All requirements -- and the 75-hour creditable cap, per the policy's
# last paragraph -- are prorated for a mid-period start/end date and
# for approved leave:
#   prorated = annual x available workdays / measuring-period workdays
# where available workdays = Mon-Fri days inside the employment window
# (start_date/end_date in employee_targets.csv), less approved leave
# from reference/leave.csv (weighted by percent_away). Ordinary PTO and
# holidays do NOT reduce requirements.
# ---------------------------------------------------------------------------
BILLABLE_HOUR_TARGETS = {          # Hours Expectation
    "Attorney": 1900,
    "Planner": 1600,
}
TOTAL_HOUR_TARGETS = {             # Total Activity
    "Attorney": 2200,
    "Planner": 1800,
}
BONUS_HOUR_THRESHOLDS = {          # Bonus Threshold
    "Attorney": 1850,
    "Planner": 1550,
}
CREDITABLE_NB_CAP = 75
CREDITABLE_CAP_PRORATED = True
PROMOTION_LOOKBACK_PCT = 90        # 2-year average % of Hours Expectation

# Individual terms (e.g. an offer letter with a 1,500 / 1,600 guideline
# and no creditable allowance) go in employee_targets.csv's optional
# billable_target / credit_cap / total_target / bonus_threshold columns,
# which override the role defaults above for that person.

# Role names accepted in employee_targets.csv's target_type column.
# LLP/LLC are from an earlier version of that file (law group =
# attorneys, planning = planners).
TARGET_TYPE_ALIASES = {
    "LLP": "Attorney",
    "LLC": "Planner",
    "ASSOCIATE": "Attorney",
    "PROJECT SPECIALIST": "Planner",
}

# How each time entry is put in a policy category (classify_time()).
# The billing system's project/file numbers have changed since the
# policy was written, so classification goes by project name and labor
# code, in this order:
#   1. TIME_CATEGORY_OVERRIDES -- exact project number (or project name)
#      -> category. Use this once you see the new system's codes; it
#      always wins.
#   2. Approved pro bono (name matches PRO_BONO_NAME_PATTERN, but not
#      "non-legal pro bono", which the policy lists as creditable).
#   3. Client time: billing status in LABOR_BILLABLE_STATUS_CODES.
#   4. Non-billable time by keyword (TIME_CATEGORY_KEYWORDS, checked in
#      order: time off, FOA, creditable, other).
#   5. Anything left is "other" non-billable (counts toward Total
#      Activity only). The page's Data checks list the non-billable
#      projects that fell through to "other", so the keywords or
#      overrides can be tuned.
TIME_CATEGORY_OVERRIDES: dict[str, str] = {
    # "NB-RECRUIT": "creditable",
    # "Firm Litigation - Fee Collection": "foa",
}
PRO_BONO_NAME_PATTERN = r"pro[\s\-]*bono"
TIME_CATEGORY_KEYWORDS = {
    # PTO, sick and holidays never count toward any requirement.
    "time_off": r"\b(pto|paid time off|time off|holiday|vacation|sick|bereavement|jury duty|leave of absence)\b",
    "foa": r"firm'?s own account|\bfoa\b",
    "creditable": (
        r"recruit|interview|summer associate|\bpgl\b|practice group lead|team work|industry team|"
        r"\bcle\b|\bmcle\b|continuing legal education|client development|business development|"
        r"internal education|training|career development|mentor|professional development|"
        r"non[\s\-]*legal pro[\s\-]*bono|bar activit|judicial committee|diversity|inclusion|\bd&i\b|"
        r"\bdei\b|innovation"
    ),
    "other": (
        r"public|alumni|billing|collection|meeting|committee|administration|admin|other office|"
        r"marketing|general office|overhead"
    ),
}
VALID_TIME_CATEGORIES = {"client", "foa", "pro_bono", "creditable", "other", "time_off"}


def classify_time(matter_code: str | None, matter_name: str | None, labor_code: str | None,
                  is_billable_status: bool) -> str:
    """Policy category for one time entry -- see the comment above."""
    import re as _re

    for key in (matter_code, matter_name):
        cat = TIME_CATEGORY_OVERRIDES.get((key or "").strip())
        if cat in VALID_TIME_CATEGORIES:
            return cat
    text = f"{matter_name or ''} {labor_code or ''}"
    if _re.search(PRO_BONO_NAME_PATTERN, text, _re.I) and not _re.search(r"non[\s\-]*legal", text, _re.I):
        return "pro_bono"
    if is_billable_status:
        return "client"
    for cat in ("time_off", "foa", "creditable", "other"):
        if _re.search(TIME_CATEGORY_KEYWORDS[cat], text, _re.I):
            return cat
    return "other"


# Vantagepoint billing status codes that count as billable hours worked.
# B = billable, H = held, F = final billed, T = transferred. Written-off
# time (W/X) is excluded by default -- move them in here if the firm
# credits written-off hours toward the target.
LABOR_BILLABLE_STATUS_CODES = {"B", "H", "F", "T"}

# Pace status bands on creditable hours vs. expected-to-date (the
# prorated target scaled to how much of the person's available time has
# elapsed): >= first value is On Track, >= second is Watch, else Behind.
PACE_STATUS_THRESHOLDS = (0.95, 0.85)

# ---------------------------------------------------------------------------
# Profitability (Measuring Period page). From the firm's draft
# profitability analysis: loaded cost = direct salary/labor cost x
# (1 + LABOR_BURDEN_RATE), where the burden covers fringe (16.4%) plus
# non-labor opex and shared allocations -- 103.4% in total. Update when
# finance re-derives it.
# ---------------------------------------------------------------------------
LABOR_BURDEN_RATE = 1.0344
# Cost per billable hour bands ($/hr): <= first = Efficient, <= second =
# Moderate, above = High cost relative to billable output.
COST_PER_BILLABLE_HOUR_BANDS = (150, 250)
# Margin bands (%): >= first = Healthy, >= second = Marginal, below = Unprofitable.
MARGIN_BANDS = (30, 10)

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
