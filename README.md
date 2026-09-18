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

## Billable-hour targets (utilization)

`reference/employee_targets.csv` assigns each employee a `target_type`
("LLC", "LLP", or blank for no target -- executives, admin, consultants
typically have none). The annual target hours and credit for each type
live in `config.py` (`BILLABLE_HOUR_TARGETS`, `BILLABLE_HOUR_CREDIT`) --
change a number there and every utilization figure recalculates.

The file isn't a Vantagepoint export -- nothing in Vantagepoint says
who's exempt or which target type applies to whom, that's firm policy.
If it doesn't exist yet, `python etl/build_warehouse.py` generates a
starter with every current employee and `target_type` left blank; open
it, fill in `target_type` for each row, and re-run. It's never
regenerated once it exists, so your edits are safe across runs. It's
also gitignored (real employee names), so this is a one-time local setup
per machine, not something that comes from the repo.

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
| Origination credits | Parsed (`etl/parse_originations.py`) from the origination credit matrix -- one row per (matter, attorney, credit fraction). `etl/build_originations_model.py` applies the firm's per-matter take-home waterfall (see `config.py` for the formula and cost percentages) to every eligible row, computed on both a billed and a collected revenue basis, and writes `project_list_by_entity`, `originations_pct_by_matter`, and `originations_by_matter_originator_year` (all surfaced on the Measuring Period page). Dollarizing still needs a shared matter key: against a real 363-row origination export and a real 315-matter list, the matrix's free-text matter names only bridge to the matter list ~22% of the time by exact normalized name, so most rows are flagged with why they can't be dollarized (`data_status`) rather than shown with a fabricated number. Fix at the source by having the origination export carry the same matter code (e.g. "LLC25-002") that AR/WIP use. |
| Project earnings & labor | **Stub** -- no sample export provided yet. This is the source needed for real timekeeper cost/utilization/realization; WIP only carries hours and billing value at standard rate, not cost or a billed-vs-worked distinction. |
| AR Aging workbook | Parsed (`etl/parse_ar_aging_workbook.py`) from the hand-built "Somos_AR_Aging_MM.DD.YYYY.xlsx" report (the same one that defined this app's own weekly AR page) -- its "AR Aging Detail" tab already has real Entity/Client/Matter columns, no PDF/string-splitting needed. Feeds the same `ar_aging_detail` table as the raw "All AR Report" export, deduped by date so the two sources never double-count. |
| GBNF (Gone But Not Forgotten) | Parsed (`etl/parse_gbnf.py`) from the "GBNF AR Aged" export -- old collectibles the firm tracks separately. Its own `gbnf_ar_aging` table, deliberately never merged into `ar_aging_detail`, so a GBNF matter's balance never inflates the regular aging book's Over 120/oldest totals or the Monthly page's Total AR. Shown in its own section on the Weekly page. |
| Timekeeper hours (measuring period) | Parsed (`etl/parse_timekeeper_hours.py`) from the "All Timekeepers Hours" export -- per-employee, per-entity hours (total/billable/credited/PTO/HOL) for the current fiscal year. Powers the Measuring Period page's hours-required-individuals-by-entity tracker: real per-person credited hours (not the flat `BILLABLE_HOUR_CREDIT` assumption), a straight-line pace projection to fiscal year end, and Pace vs. Target. Only shows employees whose `target_type` is set in `reference/employee_targets.csv`. Hours-to-date, not a final figure -- re-upload the same export any time (e.g. month-end close) to refresh with newer actuals; it replaces rather than accumulates, since the period itself doesn't change mid-year. |

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
