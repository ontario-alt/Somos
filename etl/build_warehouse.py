"""
Build the combined DuckDB warehouse from all parsed/tidy sources.

Run this after the individual parsers (or just run this directly --
it calls each parser itself, so `python etl/build_warehouse.py` is the
one command the refresh workflow needs). Sources with no export available
yet (project earnings & labor) are skipped with a warning rather than
failing the whole build -- see parse_earnings.py.

Every table carries a `snapshot_date` column, and every run *upserts*
by that column rather than wiping the table: rows for any snapshot_date
present in this run's data replace the old rows for that same date, and
every other date already in the warehouse is left alone. That's what
lets you either (a) run this weekly/monthly as new exports arrive, or
(b) drop several weeks/months of archived exports into data/raw/ at
once and backfill real history in a single run -- both parsers that
carry a genuine per-row date (parse_ar_detail's "Aged as of", parse_gl's
trial balance period) process every matching file, not just the newest,
and each row keeps its own date rather than being stamped with today's.
Sources with no such date of their own (ar_aging, WIP, AP, receipts)
still use the run's snapshot_date -- picking their newest file is a
"batch daily/weekly, one date per run" model rather than one file per
date. If a parser's output schema changes, rebuild from empty (delete
data/processed/warehouse.duckdb) rather than upserting into an old
schema.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import pandas as pd

import config
from etl import (
    parse_ap,
    parse_billing_hours_analysis,
    parse_ar,
    parse_ar_aging_workbook,
    parse_ar_detail,
    parse_ar_summary,
    parse_earnings,
    parse_gbnf,
    parse_employee_cost,
    parse_employee_targets,
    parse_gl,
    parse_labor_detail,
    parse_leave,
    parse_matter_earnings,
    parse_matter_list,
    parse_monthly_hours_workbook,
    parse_originations,
    parse_receipts,
    parse_timekeeper_hours,
    parse_wip,
)

logger = logging.getLogger("somos.etl.warehouse")

# Columns that are legitimately text but can be all-null in a given export
# snapshot (e.g. no AR comments this period) -- pandas would otherwise
# infer an ambiguous dtype from all-NaN data and DuckDB could pick the
# wrong column type. Force these to string explicitly.
_TEXT_COLUMNS = {
    "ar_comment", "matter_code", "employee_name", "invoice_number", "entity", "check_ref_no",
    "client_name_confidence", "target_type", "employee_number", "name_key", "matter_name",
    "labor_code", "billing_status", "leave_type", "note", "sheet", "hours_category", "role_hint", "staff_group", "designation",
}
# Optional date columns that are often entirely blank (nobody joined or
# left mid-period, no open-ended leave) -- an all-None column would
# otherwise land in DuckDB with no usable type.
_DATE_COLUMNS = {"start_date", "end_date", "leave_start", "leave_end"}
# Optional dollar columns (labor detail exports vary in which extensions
# they carry) -- forced to float so an all-blank column doesn't land as
# INTEGER and then reject real values on a later upsert.
_FLOAT_COLUMNS = {
    "leave_weeks", "measuring_period_end_year",
    "standard_value", "billed_amount", "cost_amount", "billable_target", "credit_cap", "total_target", "bonus_threshold",
    "billable_requirement", "total_requirement",
}


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return (
        con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()
        is not None
    )


def _create_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows: list[dict],
    default_snapshot_date: date,
    snapshot_date_col: str | None = None,
):
    """Upserts `rows` into `table` by snapshot_date: replaces every row
    whose snapshot_date matches one present in `rows`, leaves all other
    snapshot_dates already in the table untouched. If `snapshot_date_col`
    names a column the rows already carry (e.g. an "as of" date read from
    the source itself), that value is used as-is instead of
    `default_snapshot_date` -- so a batch of files spanning several dates
    lands as several distinct snapshots, not one."""
    if not rows:
        logger.warning("Skipping table %s -- no rows available", table)
        return
    for r in rows:
        if snapshot_date_col and r.get(snapshot_date_col) is not None:
            r["snapshot_date"] = r[snapshot_date_col]
        else:
            r.setdefault("snapshot_date", default_snapshot_date)
    columns = list(rows[0].keys())
    df = pd.DataFrame(rows)
    for col in _TEXT_COLUMNS & set(df.columns):
        df[col] = df[col].astype("string")
    for col in _FLOAT_COLUMNS & set(df.columns):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in _DATE_COLUMNS & set(df.columns):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        df[col] = df[col].astype("date32[pyarrow]")
    con.register("_tmp_rows", df)
    if not _table_exists(con, table):
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM _tmp_rows")
    else:
        dates = df["snapshot_date"].unique().tolist()
        placeholders = ", ".join("?" for _ in dates)
        con.execute(f"DELETE FROM {table} WHERE snapshot_date IN ({placeholders})", dates)
        con.execute(f"INSERT INTO {table} SELECT * FROM _tmp_rows")
    con.unregister("_tmp_rows")
    n_dates = df["snapshot_date"].nunique()
    logger.info(
        "Loaded table %s: %d rows across %d snapshot date(s), columns=%s", table, len(rows), n_dates, columns
    )


def build(snapshot_date: date | None = None) -> Path:
    snapshot_date = snapshot_date or date.today()
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(config.WAREHOUSE_PATH))

    # --- AR aging ---------------------------------------------------
    try:
        ar_rows = parse_ar.parse()
        parse_ar.write_processed(ar_rows)
        _create_table(con, "ar_aging", ar_rows, snapshot_date)
    except FileNotFoundError as e:
        logger.warning(str(e))

    # --- AR detail (client-level, from the "All AR Report" export) ----
    # Every matching PDF is parsed (not just the newest) and each row
    # keeps its own "Aged as of" date, so dropping several weeks in at
    # once backfills real history instead of collapsing to one snapshot.
    ar_detail_rows, _ = parse_ar_detail.parse()
    parse_ar_detail.write_processed(ar_detail_rows)
    covered_dates = {r["as_of_date"] for r in ar_detail_rows if r.get("as_of_date") is not None}

    # Second, easier source for the same table: the hand-built
    # "Somos_AR_Aging_*.xlsx" workbook (already has real Entity/Client/
    # Matter columns, no PDF/string-splitting needed). Only added for
    # dates the "All AR Report" export above doesn't already cover, so a
    # date present in both isn't double-counted.
    workbook_rows = parse_ar_aging_workbook.parse()
    workbook_rows = [r for r in workbook_rows if r.get("as_of_date") not in covered_dates]
    parse_ar_aging_workbook.write_processed(workbook_rows)
    ar_detail_rows += workbook_rows

    _create_table(con, "ar_aging_detail", ar_detail_rows, snapshot_date, snapshot_date_col="as_of_date")

    # --- GBNF (Gone But Not Forgotten) -- tracked separately, never merged
    # into ar_aging_detail above, so it never inflates the main aging book. ---
    gbnf_rows = parse_gbnf.parse()
    parse_gbnf.write_processed(gbnf_rows)
    _create_table(con, "gbnf_ar_aging", gbnf_rows, snapshot_date, snapshot_date_col="as_of_date")

    # --- WIP ----------------------------------------------------------
    try:
        wip_txns, wip_by_matter = parse_wip.parse()
        parse_wip.write_processed(wip_txns, wip_by_matter)
        _create_table(con, "wip_transactions", wip_txns, snapshot_date)
        _create_table(con, "wip_by_matter", wip_by_matter, snapshot_date)
    except FileNotFoundError as e:
        logger.warning(str(e))

    # --- Cash receipts (supplementary, weekly cash page) --------------
    try:
        receipt_rows = parse_receipts.parse()
        parse_receipts.write_processed(receipt_rows)
        _create_table(con, "cash_receipts", receipt_rows, snapshot_date)
    except FileNotFoundError as e:
        logger.warning(str(e))

    # --- AP aging + cash disbursements (same source export) -----------
    ap_rows, disbursement_rows = parse_ap.parse()
    parse_ap.write_processed(ap_rows, disbursement_rows)
    _create_table(con, "ap_aging", ap_rows, snapshot_date)
    _create_table(con, "cash_disbursements", disbursement_rows, snapshot_date)

    # --- Earnings & labor (stub until sample export provided) ---------
    earnings_rows = parse_earnings.parse()
    parse_earnings.write_processed(earnings_rows)
    _create_table(con, "earnings", earnings_rows, snapshot_date)

    # --- GL trial balance -----------------------------------------------
    # Reads every matching file (Vantagepoint runs trial balances per
    # entity), and each row keeps its own period_end as snapshot_date, so
    # dropping several months in at once backfills a real revenue-by-
    # month-by-entity trend instead of one snapshot.
    gl_rows = parse_gl.parse()
    parse_gl.write_processed(gl_rows)
    _create_table(con, "gl_trial_balance", gl_rows, snapshot_date, snapshot_date_col="period_end")

    # --- AR Summary (monthly billed activity by client) -----------------
    # Each row already carries its own month -- tagging by month_date
    # means this one file backfills 9-12 real historical snapshots
    # instead of collapsing to a single run date.
    ar_summary_rows = parse_ar_summary.parse()
    parse_ar_summary.write_processed(ar_summary_rows)
    _create_table(con, "ar_summary_monthly", ar_summary_rows, snapshot_date, snapshot_date_col="month_date")

    # --- Employee cost rates (real cost, not billing value at standard rate) ---
    cost_rows = parse_employee_cost.parse()
    parse_employee_cost.write_processed(cost_rows)
    _create_table(con, "employee_cost_rates", cost_rows, snapshot_date)

    # --- Employee billable-hour targets (hand-maintained, see the file) ---
    # Fully replaced each run like employee_leave below: it's a small
    # hand-maintained file whose columns have grown over time (role,
    # start/end dates), so upserting into an older table's schema would fail.
    target_rows = parse_employee_targets.parse(cost_rows)
    parse_employee_targets.write_processed(target_rows)
    if target_rows:
        con.execute("DROP TABLE IF EXISTS employee_targets")
    _create_table(con, "employee_targets", target_rows, snapshot_date)

    # --- Matter earnings (NTE-tracked matters only -- real revenue/profit) --
    matter_earnings_rows = parse_matter_earnings.parse()
    parse_matter_earnings.write_processed(matter_earnings_rows)
    _create_table(con, "matter_earnings", matter_earnings_rows, snapshot_date)

    # --- Matter master list (matter code -> client -> entity -> org) ----
    matter_rows = parse_matter_list.parse()
    parse_matter_list.write_processed(matter_rows)
    _create_table(con, "matter_list", matter_rows, snapshot_date)

    # --- Origination credits --------------------------------------------
    origination_rows, origination_flagged = parse_originations.parse()
    parse_originations.write_processed(origination_rows, origination_flagged)
    _create_table(con, "originations", origination_rows, snapshot_date)
    _create_table(con, "originations_flagged", origination_flagged, snapshot_date)

    # --- Timekeeper hours (measuring period, per entity) -----------------
    tk_hours_rows = parse_timekeeper_hours.parse()
    parse_timekeeper_hours.write_processed(tk_hours_rows)
    # Every export is re-read each run (newest per period wins), so rebuilt
    # rather than upserted -- also keeps the schema current.
    if tk_hours_rows:
        con.execute("DROP TABLE IF EXISTS timekeeper_hours")
    _create_table(con, "timekeeper_hours", tk_hours_rows, snapshot_date, snapshot_date_col="period_end")

    # --- Labor (time) detail -- transaction-level, measuring period -------
    # Each row keeps its own work date as snapshot_date, so a fresh
    # FY-to-date export replaces exactly the dates it covers.
    labor_rows = parse_labor_detail.parse()
    parse_labor_detail.write_processed(labor_rows)
    # Every export is re-read each run (newest wins per date), so rebuilt.
    if labor_rows:
        con.execute("DROP TABLE IF EXISTS labor_detail")
    _create_table(con, "labor_detail", labor_rows, snapshot_date, snapshot_date_col="transaction_date")
    # Entries rejected as bad postings (e.g. -255,000 hours) -- shown as a data check.
    con.execute("DROP TABLE IF EXISTS labor_rejected")
    _create_table(con, "labor_rejected", parse_labor_detail.rejected_entries(), snapshot_date,
                  snapshot_date_col="transaction_date")

    # --- Firm's monthly hours workbook (closed measuring periods) ----------
    # The Billing Hours Analysis workbook's billable-only monthly tabs only
    # fill months the Monthly Hours Report doesn't cover (that one has the
    # full billable / credited / not-credited breakdown). Combined into one
    # batch because the table upserts by month.
    monthly_hours_rows = parse_monthly_hours_workbook.parse()
    covered_months = {r["month"] for r in monthly_hours_rows}
    monthly_hours_rows += [
        r for r in parse_billing_hours_analysis.parse() if r["month"] not in covered_months
    ]
    parse_monthly_hours_workbook.write_processed(monthly_hours_rows)
    # Both workbooks are re-read in full every run, so the table is rebuilt
    # rather than upserted (also keeps its schema current).
    if monthly_hours_rows:
        con.execute("DROP TABLE IF EXISTS monthly_hours")
    _create_table(con, "monthly_hours", monthly_hours_rows, snapshot_date, snapshot_date_col="month")

    # --- Approved leave (hand-maintained, prorates hour targets) ---------
    # Fully replaced each run (it's a small reference list, and a deleted
    # row must actually disappear rather than linger under an old date).
    leave_rows = parse_leave.parse()
    parse_leave.write_processed(leave_rows)
    con.execute("DROP TABLE IF EXISTS employee_leave")
    _create_table(con, "employee_leave", leave_rows, snapshot_date)

    con.close()
    logger.info("Warehouse build complete -> %s", config.WAREHOUSE_PATH)
    return config.WAREHOUSE_PATH


def print_schema():
    con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    for (table,) in tables:
        print(f"\n=== {table} ===")
        info = con.execute(f"DESCRIBE {table}").fetchall()
        for col_name, col_type, *_ in info:
            print(f"  {col_name:<22} {col_type}")
        (count,) = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  -- {count} rows")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    build()
    print_schema()
