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
Period page scores every hours-required timekeeper against the firm's
**Promotion and Bonus Policy** (last updated 1/15/2023). All the numbers
live in `config.py`.

**Hour categories.** Every labor-detail entry is classified by
`config.classify_time()` using its project name and labor code. The
policy's old file numbers no longer apply since the billing system
changed.

| Category | Recognized by | Counts toward |
|---|---|---|
| Client | billable status | everything |
| Firm's Own Account | "Firm's Own Account" / "FOA" | everything |
| Pro bono | "pro bono" (not "non-legal pro bono") | Hours Expectation in full; bonus only after the threshold is met |
| Creditable non-billable | recruiting, PGL/team work, CLE, client/business development, internal education/training, career development/mentoring, non-legal pro bono/bar activities, diversity & inclusion, innovation | capped at **75 hrs** (cap prorated) |
| Other non-billable | meetings, billing & collections, administration, public/alumni, anything unrecognized | Total Activity only |
| PTO / sick / holiday | PTO, paid time off, sick, holiday, vacation, ... | **never counts** |

The keywords are in `config.TIME_CATEGORY_KEYWORDS`. Once you see the new
system's project numbers, pin any project to a category in
`config.TIME_CATEGORY_OVERRIDES`; overrides always win. The page's **How
non-billable time was classified** panel lists every non-client project with
its category and hours, so you can check it.

**Three tests per person.** Associates are the Attorney role. Planners and
Project Specialists are the Planner role.

| Test | Hours | Associates / Planners |
|---|---|---|
| Hours Expectation (promotion) | client + FOA + pro bono + capped creditable | 1,900 / 1,600 |
| Total Activity | all chargeable + non-chargeable, excluding PTO/sick/holiday | 2,200 / 1,800 |
| Bonus Threshold | client + FOA + capped creditable (no pro bono) | 1,850 / 1,550 |
| Promotion lookback | 2-year average % of Hours Expectation | ≥ 90% |

**Proration.** Every requirement, and the 75-hour cap, is prorated on Mon-Fri
workdays for a mid-period start or end date and for approved leave
(`reference/leave.csv`, weighted by `percent_away`). The formula is
`annual x available workdays / period workdays`. "Expected to date" uses
each person's own available workdays, so time on leave doesn't count against
pace. A closed period shows Met or Not Met. An open one shows On Track, Watch
or Behind.

**On the page:** a status summary and a progress chart, then tabs for Hours
Expectation, Total Activity, Bonus Eligibility and Promotion (2-yr lookback),
each split by role. Below that are a month-by-month chart per person, data
checks, Timekeeper and Practice Group Profitability, and downloads. Use the
"Hours through" date to review any period. For example, 9/30/2024 shows FY24
from the firm's workbook.

### Hours sources (best first, per period)

1. **Vantagepoint labor detail export** (`*Labor*Detail*` / `*Time*Analysis*`):
   one row per time entry. Columns are Employee Name, Employee Number,
   Transaction Date, Project Number, Project Name, Labor Code, Billing Status,
   Hours, Billing Extension, Billed Amount, Cost Extension and Company
   (matched loosely, see `_ALIASES` in `etl/parse_labor_detail.py`). This is
   the only source that separates pro bono, FOA and creditable time, so use it
   going forward. **Not yet verified against a real export.** The first time,
   check the build log's "Hours by policy category" line and the
   classification panel against Vantagepoint.
2. **The firm's Monthly Hours Report by Timekeeper workbook**
   (`*Monthly*Hours*Report*.xlsx`, `etl/parse_monthly_hours_workbook.py`).
   It has one tab per timekeeper, and each person's totals reconcile to the
   workbook's own totals rows. It backfills closed periods, including the
   per-person requirements recorded in it. It has only billable, credited and
   not-credited buckets, so all credited hours are treated as creditable
   (capped). That understates anyone whose credited hours were pro bono, and
   the page says so.
3. **All Timekeepers Hours** summary, with the same bucket limitation.

Employee Cost Rate Details and the Matter List feed the profitability views.

### What you maintain by hand (firm policy, not in Vantagepoint)

`reference/employee_targets.csv` has one row per employee:

    employee_number,full_name,labor_type,target_type,start_date,end_date,billable_target,credit_cap,total_target,bonus_threshold
    101,Jonathan Zuniga,Employee,Attorney,,,,,,
    104,New Associate,Employee,Associate,3/2/2026,,,,,
    205,Jade Crawford,Employee,Planner,,9/15/2024,,,,
    210,Reuben Duarte,Employee,,,,1500,0,1600,

- `target_type` is Attorney/Associate, Planner/Project Specialist, or blank
  (no requirement). Legacy LLP/LLC values still work.
- The last four columns override the role defaults for individual terms,
  such as the offer-letter guideline above.
- A starter file is generated on the first build and never overwritten.

`reference/leave.csv` has one row per approved leave:

    full_name,employee_number,leave_start,leave_end,percent_away,leave_type,note
    Lauren Kim,202,1/5/2026,3/27/2026,100,Parental,

Both files are gitignored because they contain real names. Set
`SOMOS_REFERENCE_DIR` to keep them in the shared SharePoint folder.

### Sharing with leadership

- **Leadership report (HTML).** The Measuring Period page has a **Download
  leadership report** button. It produces one self-contained file with KPIs,
  the progress chart, the scorecard for all three tests and the promotion
  lookback, plus the method and data notes. It opens offline in any browser.
  Email it, post it to a SharePoint or Teams channel, or print it to PDF. This
  is the simplest option for a period-end review.
- **Scorecard CSV.** Use this for anyone who wants to slice the numbers in
  Excel.
- **A live dashboard.** Leadership can get a link instead of a file in two
  ways:
  - Run this app on an always-on machine or Azure VM that can read the
    SharePoint folder, and put it behind your Microsoft sign-in, for example
    with Azure App Service authentication.
  - Point Power BI at `data/processed/*.csv` (synced to SharePoint) and
    publish it to a leadership workspace with scheduled refresh.
  - Don't use public hosting such as Streamlit Community Cloud. These are
    compensation-relevant figures with employee names.

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
| Monthly Hours Report workbook | Parsed (`etl/parse_monthly_hours_workbook.py`) from the firm's hand-built per-timekeeper workbook. It was verified against the FY24 sample: each person's 12 months reconcile to the workbook's own totals row. It backfills closed measuring periods for the scorecard and the 2-year promotion lookback. |
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
