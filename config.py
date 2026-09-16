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
    "nte_tracking": ["*NTE*Tracking*.xlsx"],
}

# The NTE Tracking Report only covers matters with a not-to-exceed cap
# set (a "Records Selected" filter in Vantagepoint, confirmed: 42 of the
# ~315 matters in the matter list) -- real revenue/profit data, but for
# a subset of the portfolio, not the whole thing. Keep this in one place
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
# Billable hour targets, for real utilization (actual billable hours vs.
# what's expected of that timekeeper) instead of raw activity. Update
# these two numbers once -- everywhere utilization is shown recalculates.
#
# BILLABLE_HOUR_CREDIT is a flat number of hours credited toward the
# target regardless of what's actually billed (e.g. CLE, firm
# administration) -- current assumption is that it *reduces* how many
# hours a timekeeper actually needs to bill (target - credit), not that
# it's added on top. Confirm this against the firm's actual hours policy
# once it's available and adjust EMPLOYEE_TARGETS_CREDIT_REDUCES_TARGET
# below if the policy works the other way.
# ---------------------------------------------------------------------------
BILLABLE_HOUR_TARGETS = {
    "LLC": 1600,
    "LLP": 1900,
}
BILLABLE_HOUR_CREDIT = 75
EMPLOYEE_TARGETS_CREDIT_REDUCES_TARGET = True

# Not every employee has a billable-hour target (executives, admin team
# members, consultants/contractors typically don't). Rather than
# guessing who's exempt, reference/employee_targets.csv is a plain,
# hand-maintained file -- one row per employee, a `target_type` column
# that's one of BILLABLE_HOUR_TARGETS' keys ("LLC"/"LLP") or blank for
# no target. (Not "config/" -- that would collide with this file,
# config.py, as a package name.) etl/parse_employee_targets.py
# auto-generates a starter version (every employee currently in
# employee_cost_rates, target_type blank) the first time it's needed if
# the file doesn't exist yet -- fill it in and re-run
# build_warehouse.py; it won't be overwritten once it exists.
EMPLOYEE_TARGETS_PATH = Path(__file__).parent / "reference" / "employee_targets.csv"

# ---------------------------------------------------------------------------
# Targets (fill in as the firm sets them; used by the Measuring Period page)
# ---------------------------------------------------------------------------
ORIGINATION_TARGETS = {
    # "Attorney Name": 500_000.00,
}

# Origination formula -- the firm's own per-matter waterfall (from the
# "Originations Model" workbook), reproduced exactly in
# etl/build_originations_model.py::compute_matter_takehome and verified
# there against the workbook's own worked example (Steerpoint / Escondido
# Mall) to the penny:
#
#   Cost Basis(matter)        = Billed Amount(matter, year)
#   Adjusted Revenue          = Collected Amount(matter, year) - Reimbursements
#   Direct Costs              = Cost Basis x ORIGINATION_DIRECT_COST_PCT
#   Indirect Costs            = Cost Basis x ORIGINATION_INDIRECT_COST_PCT
#   Gross Profit to Somos     = Adjusted Revenue - Direct Costs
#                               - Originator Costs - Indirect Costs
#   Capital Expense Adj.      = Gross Profit to Somos x ORIGINATION_CAPITAL_EXPENSE_PCT
#   Total Take Home (matter)  = Gross Profit to Somos - Capital Expense Adj.
#
#   Origination_$(attorney, matter, year)
#       = credit_fraction(attorney, matter) x Total Take Home(matter, year)
#
#   Attorney_Originations(attorney, year)
#       = SUM over matter of Origination_$(attorney, matter, year)
#
# Revenue Basis is Collected (cash receipts) Amount only -- the firm has
# decided originations run on money actually collected, not billed.
# Billed Amount is still used, unchanged, as the Cost Basis that sets the
# Direct/Indirect Cost percentages above; see
# build_originations_model.py's module docstring and
# originations_by_matter_originator_year output.
#
# Eligibility (a matter/attorney pair must clear ALL of these before the
# formula runs at all -- see build_originations_model.py::is_eligible):
#   - origination matrix status is "OK" (not a GAP, INCOMPLETE, Pro Bono,
#     or duplicate row)
#   - credit_fraction > 0
#   - entity is in ORIGINATABLE_ENTITIES below
ORIGINATION_DIRECT_COST_PCT = 0.30
ORIGINATION_INDIRECT_COST_PCT = 0.35
ORIGINATION_CAPITAL_EXPENSE_PCT = 0.20

# Entities whose matters currently go through the origination-credit
# process. Somos Group Mexico is a real entity (ENTITIES above,
# MATTER_CODE_ENTITY_PREFIXES["MEX"]) with matters already appearing in
# the matter list export, so it's a future originatable entity worth
# planning for -- but it has no origination matrix, matter_earnings, or
# revenue data yet, so it's deliberately left out of this list until
# that's built out.
ORIGINATABLE_ENTITIES = [
    "Somos Group LLC",
    "Somos Law Group LLP",
]
