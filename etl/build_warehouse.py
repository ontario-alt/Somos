"""
Build the combined DuckDB warehouse from all parsed/tidy sources.

Run this after the individual parsers (or just run this directly --
it calls each parser itself, so `python etl/build_warehouse.py` is the
one command the refresh workflow needs). Sources with no export available
yet (project earnings & labor) are skipped with a warning rather than
failing the whole build -- see parse_earnings.py.

Every run replaces the warehouse tables (CREATE OR REPLACE) from the
latest files in data/raw/, keyed by a `snapshot_date` column so monthly
history can accumulate if this script is run against archived exports
over time (see README.md for the monthly refresh + archive workflow).
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
from etl import parse_ap, parse_ar, parse_earnings, parse_gl, parse_originations, parse_receipts, parse_wip

logger = logging.getLogger("somos.etl.warehouse")

# Columns that are legitimately text but can be all-null in a given export
# snapshot (e.g. no AR comments this period) -- pandas would otherwise
# infer an ambiguous dtype from all-NaN data and DuckDB could pick the
# wrong column type. Force these to string explicitly.
_TEXT_COLUMNS = {"ar_comment", "matter_code", "employee_name", "invoice_number", "entity", "check_ref_no"}


def _create_table(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict], snapshot_date: date):
    if not rows:
        logger.warning("Skipping table %s -- no rows available", table)
        return
    for r in rows:
        r["snapshot_date"] = snapshot_date
    columns = list(rows[0].keys())
    df = pd.DataFrame(rows)
    for col in _TEXT_COLUMNS & set(df.columns):
        df[col] = df[col].astype("string")
    con.register("_tmp_rows", df)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _tmp_rows")
    con.unregister("_tmp_rows")
    logger.info("Loaded table %s: %d rows, columns=%s", table, len(rows), columns)


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
    gl_rows = parse_gl.parse()
    parse_gl.write_processed(gl_rows)
    _create_table(con, "gl_trial_balance", gl_rows, snapshot_date)

    # --- Origination credits --------------------------------------------
    origination_rows, origination_flagged = parse_originations.parse()
    parse_originations.write_processed(origination_rows, origination_flagged)
    _create_table(con, "originations", origination_rows, snapshot_date)
    _create_table(con, "originations_flagged", origination_flagged, snapshot_date)

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
