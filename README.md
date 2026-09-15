# Somos Group Executive Dashboard

Local Streamlit app that turns Vantagepoint exports into weekly / monthly /
quarterly / fiscal-year ("measuring period") reporting, backed by a DuckDB
warehouse so charts don't re-parse raw exports on every run.

## How it fits together

```
data/raw/         <- points at your OneDrive-synced SharePoint folder (config.py)
data/processed/   <- tidy, one-table-per-source CSVs (etl output, regenerated each run)
etl/               parse_*.py  = one parser per Vantagepoint export
                   build_warehouse.py = combines tidy tables into data/processed/warehouse.duckdb
dashboard/app.py   Streamlit entrypoint
dashboard/pages/   weekly.py, monthly.py, quarterly.py, measuring_period.py
dashboard/charts/  reusable Plotly chart components
config.py          paths, entity list, fiscal year, targets -- edit this, not the code
```

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
| AR detail (client-level) | Parsed (`etl/parse_ar_detail.py`) from Vantagepoint's "All AR Report" PDF -- matter-level with an explicit client field, which the AR aging export above doesn't have. Column values recovered by matching each number's x-position to the header's column positions (blank cells are absent, not "0.00"). Reconciles exactly to the source's own Final Totals line. Backs the weekly AR page's Summary/Priority/Client Rollup views. Only a PDF sample seen so far -- ask for CSV/Excel if this ever needs updating, since PDF layout parsing is inherently more fragile. |
| WIP / unbilled | Parsed (same verification; also produces a matter-level rollup table) |
| AP aging | Parsed (`etl/parse_ap.py`) from the AP export's own voucher/payment lines -- open balance is netted per invoice since the source has no explicit paid/open flag. Reconciles: 35 open invoices out of 165 total in the sample. |
| GL trial balance | Parsed (`etl/parse_gl.py`) -- flat, one row per account; account type (Asset/Liability/Equity/Revenue/COGS/Expense) derived from the leading digit of the account number. Reconciles exactly to the source's own subtotal rows. Reads *every* file matching the pattern, not just the newest, since Vantagepoint runs trial balances per entity. |
| Cash receipts | Parsed (supplementary weekly-page feed, not one of the 5 core sources) |
| Cash disbursements | Parsed (`etl/parse_ap.py`) -- the AP export's payment lines ("AP Disb"/"Auto Check" rows with a Check Date) double as the disbursements source; no separate export needed. |
| Origination credits | Parsed (`etl/parse_originations.py`) from the origination credit matrix -- one row per (matter, attorney, credit fraction). Gives real originating-attorney data, but dollarizing it against revenue needs a shared matter key: the matrix's free-text matter names only match AR's matter names ~16% of the time, so the Measuring Period page shows matter-credit totals, not fabricated dollar figures. Fix at the source by having the origination export carry the same matter code (e.g. "LLC25-002") that AR/WIP use. |
| Project earnings & labor | **Stub** -- no sample export provided yet. This is the source needed for real timekeeper cost/utilization/realization; WIP only carries hours and billing value at standard rate, not cost or a billed-vs-worked distinction. |

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
