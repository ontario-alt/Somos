"""
Warehouse access layer for the dashboard. Every page queries through
here rather than opening its own DuckDB connection, so caching and the
"table doesn't exist yet" handling (for AP/earnings/GL, still stubbed in
the ETL layer) live in exactly one place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import pandas as pd
import streamlit as st

import config


@st.cache_resource(show_spinner=False)
def get_connection() -> duckdb.DuckDBPyConnection:
    if not config.WAREHOUSE_PATH.exists():
        raise FileNotFoundError(
            f"No warehouse found at {config.WAREHOUSE_PATH}. Run "
            "`python etl/build_warehouse.py` first."
        )
    return duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)


def table_exists(table: str) -> bool:
    con = get_connection()
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone() is not None


@st.cache_data(show_spinner=False)
def query(sql: str, params: list | None = None) -> pd.DataFrame:
    con = get_connection()
    return con.execute(sql, params or []).fetchdf()


def warehouse_last_built() -> str | None:
    if not config.WAREHOUSE_PATH.exists():
        return None
    import datetime

    mtime = config.WAREHOUSE_PATH.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
