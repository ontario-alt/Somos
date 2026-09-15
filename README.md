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
| WIP / unbilled | Parsed (same verification; also produces a matter-level rollup table) |
| Cash receipts | Parsed (supplementary weekly-page feed, not one of the 5 core sources) |
| AP aging | **Stub** -- no sample export provided yet. Drop one in `data/raw/` and `etl/parse_ap.py` can be finished against its real columns. |
| Project earnings & labor | **Stub** -- same as above. This is also the source needed for real cost/margin figures; WIP only carries hours and billing value at standard rate, not cost. |
| GL trial balance | **Stub** -- same as above. Needed for a real P&L by entity. |

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
