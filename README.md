# Somos Group Executive Dashboard

Local Streamlit app that turns Vantagepoint exports into weekly / monthly /
quarterly / fiscal-year ("measuring period") reporting, backed by a DuckDB
warehouse so charts don't re-parse raw exports on every run.

## How it fits together

```
data/raw/         <- points at your OneDrive-synced SharePoint folder (config.py)
data/processed/   <- tidy, one-table-per-source CSVs (etl output, regenerated each run)
reference/         employee_targets.csv = hand-maintained, not a Vantagepoint export (see below)
etl/               parse_*.py  = one parser per Vantagepoint export
                   build_warehouse.py = combines tidy tables into data/processed/warehouse.duckdb
dashboard/app.py   Streamlit entrypoint
dashboard/report_pages/   weekly.py, monthly.py, quarterly.py, measuring_period.py
dashboard/charts/  reusable Plotly chart components
config.py          paths, entity list, fiscal year, targets -- edit this, not the code
```

## Measuring period hours & profitability

The measuring period is the fiscal year, **Oct 1 - Sep 30**. The Measuring
Period page scores every hours-required timekeeper against firm policy:

| Rule | Where it lives |
|---|---|
| Annual target by role: Attorney / Planner | `config.BILLABLE_HOUR_TARGETS` (currently 1,900 / 1,600, **confirm**) |
| Creditable hours = billable + pro bono, pro bono credit capped at 75 hrs | `config.PRO_BONO_CREDIT_CAP` (`PRO_BONO_CAP_PRORATED` if the cap also shrinks with leave) |
| How pro bono time is recognized | `config.PRO_BONO_MATTER_CODES` / `PRO_BONO_NAME_PATTERN` (matter name or labor code containing "pro bono") |
| Which billing statuses count as billable | `config.LABOR_BILLABLE_STATUS_CODES` (B, H, F, T; written-off W/X excluded) |
| Target prorated for leave and mid-year start/leave | `reference/leave.csv` + `start_date`/`end_date` in `reference/employee_targets.csv` |
| On Track / Watch / Behind bands | `config.PACE_STATUS_THRESHOLDS` (95% / 85% of expected-to-date) |

**Proration** is on Mon-Fri workdays: `target x available workdays / period
workdays`. Approved leave is weighted by `percent_away` (so a half-time
schedule counts as half a day out), and ordinary PTO and holidays don't
reduce the target. "Expected to date" is the prorated target times the
share of *that person's* available workdays that have passed, so someone
back from leave isn't marked behind for the months they were out.

**What the page shows:** status counts and team pace, a progress bar per
person (with a tick showing where they should be by now), Attorney and
Planner tables (prorated target, leave days, billable, pro bono logged and
credited, creditable, variance, projected year-end, hours per week still
needed), a CSV download for review meetings, a month-by-month pace chart
per person, and data checks (name mismatches, exempt people billing heavily,
leave rows that don't match anyone). **Timekeeper Profitability** shows
revenue against direct labor cost by person and role, and **Practice
Group Profitability** now covers every matter with time logged, not just the
NTE-capped ones. Use the "Hours through" date to review a closed period (for
example 9/30/2026 for FY26).

### What you need from Vantagepoint

1. **Labor detail (time detail) export**, the main source. It's one row per time
   entry for 10/1 to the review date (or the full year), all employees, CSV or
   Excel, with a filename containing "Labor Detail" or "Time Analysis".
   Columns: Employee Name, Employee Number, Transaction Date, Project Number,
   Project Name, Labor Code, Billing Status, Hours, Billing Extension, Billed
   Amount, Cost Extension, Company. Header names are matched loosely (see
   `_ALIASES` in `etl/parse_labor_detail.py`). Billed Amount and Cost
   Extension are optional. Without them revenue falls back to standard
   value, and cost falls back to the cost-rate export below.
2. **Employee Cost Rate Details**, which the app already loads, for labor cost.
3. **Matter List**, also already loaded, for the practice-group view.
4. *(Fallback)* **All Timekeepers Hours**. If no labor detail is loaded,
   the scorecard uses this summary, treating its Credited Hours column as
   pro bono. The page shows a warning when that happens. It has no monthly
   pace and no dollars.

### What you maintain by hand (firm policy, not in Vantagepoint)

`reference/employee_targets.csv`: one row per employee. Columns:

    employee_number,full_name,labor_type,target_type,start_date,end_date
    101,Maria Lopez,Employee,Attorney,,
    104,James Okafor,Employee,Attorney,3/2/2026,
    204,Ethan Wright,Employee,Planner,,6/30/2026
    003,Alfred Fraijo Jr.,Principal,,,

`target_type` is `Attorney`, `Planner`, or blank (no target). Legacy `LLP`
and `LLC` values still work as Attorney and Planner. `python
etl/build_warehouse.py` generates a starter from the cost-rate export the
first time. It's never overwritten after that.

`reference/leave.csv`: one row per approved leave of absence:

    full_name,employee_number,leave_start,leave_end,percent_away,leave_type,note
    Lauren Kim,202,1/5/2026,3/27/2026,100,Parental,
    Ana Ruiz,105,6/1/2026,8/28/2026,50,Reduced schedule,

An empty file (header only) is created on the first build. Both files are
gitignored because they contain real names. Set `SOMOS_REFERENCE_DIR` to
keep them in the shared SharePoint folder so the whole team edits one copy.

Names are matched across exports regardless of format ("Lopez, Maria" and
"Maria Lopez" match). Anyone who doesn't match is listed under the page's
**Data checks**.

## Monthly refresh (bookkeeping team)

1. Export the latest reports from Vantagepoint and save them into the
   SharePoint folder that syncs to your `data/raw/` path (set once in
   `config.py`, or via the `SOMOS_RAW_DIR` environment variable if you'd
   rather not edit the file). Keep the export names roughly as
   Vantagepoint generates them (e.g. `AR_Aging_...csv`) -- the parsers
   pick the newest file matching a pattern, not an exact filename.
2. From the project folder, run:
   ```
   python etl/build_warehouse.py
   ```
   This re-parses every source it finds, rebuilds `data/processed/*.csv`,
   and rebuilds `data/processed/warehouse.duckdb`. It prints the full
   schema (tables, columns, row counts) when it finishes -- check that
   before trusting the dashboard.
3. Start (or refresh) the dashboard:
   ```
   streamlit run dashboard/app.py
   ```

That's it -- one script, then the app. No manual data wrangling.

## Weekly refresh (AR/AP only)

Drop the fresh AR/AP aging and cash receipts exports into the same
`data/raw/` folder and re-run `python etl/build_warehouse.py`. It's the
same command either way; the weekly page just reads whatever's newest.

## What's implemented vs. stubbed

| Source | Status |
|---|---|
| AR aging | Parsed (nested tree reconstruction verified against sample -- reconciles to the export's own TOTALS row) |
| AR detail (client-level) | Parsed (`etl/parse_ar_detail.py`) from Vantagepoint's "All AR Report" -- matter-level with an explicit client field, which the AR aging export above doesn't have. Handles both a real .xlsx export (reliable, real cells) and a .pdf export (values recovered by matching each number's x-position to the header's column positions); .xlsx is preferred when both cover the same date. Reconciles exactly to each source's own Final Totals line. Backs the weekly AR page's Summary/Priority/Client Rollup/Week-over-Week views -- two real snapshots are loaded, so Week over Week is live, not a placeholder. |
| Matter list | Parsed (`etl/parse_matter_list.py`) -- matter code -> matter name -> client -> entity, plus an "Organization Name" field that doubles as a practice-group/department taxonomy. Unblocked "AR by Practice Group" on the Quarterly page (89% of AR matters matched by exact matter code). |
| AR Summary (monthly billed activity) | Parsed (`etl/parse_ar_summary.py`) -- monthly $ by client, Jan-Dec. Distinct from AR balance and from cash receipts: this is billed/invoiced activity. Each row is tagged with its own month, so one file backfills 9-12 real historical snapshots at once (see "Monthly Billings by Entity" on the Quarterly page) instead of waiting for weekly/monthly accumulation. One entity (Somos Law Group LLP) had no client-level breakdown in the sample -- the parser falls back to that entity's own total rather than losing it. |
| WIP / unbilled | Parsed (same verification; also produces a matter-level rollup table) |
| AP aging | Parsed (`etl/parse_ap.py`) from the AP export's own voucher/payment lines -- open balance is netted per invoice since the source has no explicit paid/open flag. Reconciles: 35 open invoices out of 165 total in the sample. |
| GL trial balance | Parsed (`etl/parse_gl.py`) -- flat, one row per account; account type (Asset/Liability/Equity/Revenue/COGS/Expense) derived from the leading digit of the account number. Reconciles exactly to the source's own subtotal rows. Reads *every* file matching the pattern, not just the newest, since Vantagepoint runs trial balances per entity -- both entities loaded (combined books balance to zero, verified by hand). File pattern matches both "Trial Balance" and this firm's saved-favorite name "GL Report". |
| Employee cost rates | Parsed (`etl/parse_employee_cost.py`) -- real cost/pay rate per employee, turning WIP billing value into real cost and margin (Monthly page's Timekeeper Activity and P&L now show both). Checked directly: the "per entity" export is actually one firm-wide roster (identical rates in both files), so this is deduplicated by employee number rather than treated as two real datasets -- treating it as per-entity would have double-counted salaried staff who log time against both entities. 93% of WIP timekeepers matched by name. |
| Matter earnings | Parsed (`etl/parse_matter_earnings.py`) from the NTE Tracking Report -- real matter-level JTD revenue and profit, keyed by the same matter code AR/WIP use. Same "actually firm-wide, not per-entity" pattern as employee cost rates, deduplicated the same way. Reconciles exactly to the source's own Final Totals. Powers a real (if partial) Practice Group Profitability view on the Measuring Period page -- this report only covers matters billed against a not-to-exceed cap (42 of ~315 total matters). That's not a coverage gap: flat-fee and T&E matters are never NTE-capped, so most of the portfolio structurally can't appear here regardless of how much more of this export is loaded -- full-portfolio profitability needs a different bridge per billing type, not more NTE data. Checked whether this could also dollarize the origination credit matrix: only ~6% of origination matters bridge to an NTE-tracked matter, too low to use. |
| Cash receipts | Parsed (supplementary weekly-page feed, not one of the 5 core sources) |
| Cash disbursements | Parsed (`etl/parse_ap.py`) -- the AP export's payment lines ("AP Disb"/"Auto Check" rows with a Check Date) double as the disbursements source; no separate export needed. |
| Origination credits | Parsed (`etl/parse_originations.py`) from the origination credit matrix -- one row per (matter, attorney, credit fraction). Gives real originating-attorney data, but dollarizing it against revenue needs a shared matter key: the matrix's free-text matter names only match AR's matter names ~16% of the time, so the Measuring Period page shows matter-credit totals, not fabricated dollar figures. Fix at the source by having the origination export carry the same matter code (e.g. "LLC25-002") that AR/WIP use. |
| Project earnings & labor | **Stub** -- no sample export provided yet. This is the source needed for real timekeeper cost/utilization/realization; WIP only carries hours and billing value at standard rate, not cost or a billed-vs-worked distinction. |
| AR Aging workbook | Parsed (`etl/parse_ar_aging_workbook.py`) from the hand-built "Somos_AR_Aging_MM.DD.YYYY.xlsx" report (the same one that defined this app's own weekly AR page) -- its "AR Aging Detail" tab already has real Entity/Client/Matter columns, no PDF/string-splitting needed. Feeds the same `ar_aging_detail` table as the raw "All AR Report" export, deduped by date so the two sources never double-count. |
| GBNF (Gone But Not Forgotten) | Parsed (`etl/parse_gbnf.py`) from the "GBNF AR Aged" export -- old collectibles the firm tracks separately. Its own `gbnf_ar_aging` table, deliberately never merged into `ar_aging_detail`, so a GBNF matter's balance never inflates the regular aging book's Over 120/oldest totals or the Monthly page's Total AR. Shown in its own section on the Weekly page. |
| Labor detail (time entries) | Parsed (`etl/parse_labor_detail.py`). **Not yet verified against a real export.** It was built from Vantagepoint's standard labor fields and tested on synthetic data, so check the build log's hours and pro bono totals against Vantagepoint the first time. This is the preferred source for the measuring-period scorecard (pro bono split, monthly pace) and for timekeeper and practice-group profitability. |
| Approved leave | Hand-maintained `reference/leave.csv` (`etl/parse_leave.py`) and used to prorate targets. |
| Timekeeper hours (measuring period) | Parsed (`etl/parse_timekeeper_hours.py`) from the "All Timekeepers Hours" export -- per-employee, per-entity hours (total/billable/credited/PTO/HOL) for the current fiscal year. Powers the Measuring Period page's hours-required-individuals-by-entity tracker: now the *fallback* hours source for the creditable-hours scorecard when no labor detail export is loaded (Credited Hours treated as pro bono, capped at 75). Hours-to-date, not a final figure -- re-upload the same export any time (e.g. month-end close) to refresh with newer actuals; it replaces rather than accumulates, since the period itself doesn't change mid-year. |

`etl/build_warehouse.py` skips any stubbed source with a warning rather
than failing the whole build, so the warehouse always builds from
whatever's currently available.

## Requirements

```
pip install -r requirements.txt
```

## Notes on the export format

Vantagepoint's "detail" exports (AR aging, WIP) are a collapsed tree --
e.g. Matter > Invoice > payment line -- flattened to CSV with no
indentation or level markers. `etl/common.py`'s `reconstruct_hierarchy()`
walks each file once and rebuilds the tree by matching each header row's
stated subtotal against the sum of the leaf rows beneath it. If AP aging
or the earnings export turn out to follow the same pattern (likely, same
report family), the same helper should work with a new leaf predicate and
column mapping rather than a new algorithm.
