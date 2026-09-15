"""
Parse the Vantagepoint GL trial balance export into a tidy table.

STUB -- no sample provided yet. Update this once a sample lands in
data/raw/. Trial balance exports are typically already flat (one row
per GL account per entity/period), unlike the AR/WIP nested-tree
reports, but verify against the real file rather than assuming.

Expected output grain once implemented: one row per account/entity/period:
    entity, account_number, account_name, account_type,
    period, debit, credit, balance, source_file
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file

logger = logging.getLogger("somos.etl.gl")


def parse(path: Path | None = None) -> list[dict]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["gl_trial_balance"])
    if path is None:
        logger.warning(
            "No GL trial balance export found in %s matching %r -- skipping. "
            "P&L and profitability pages will be unavailable until a sample "
            "export is added and this parser is implemented.",
            config.RAW_DATA_DIR,
            config.SOURCE_FILE_PATTERNS["gl_trial_balance"],
        )
        return []
    raise NotImplementedError(
        f"Found a GL trial balance export at {path}, but parse_gl.py hasn't been "
        "implemented against its real column layout yet."
    )


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No GL rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "gl_trial_balance.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    print(f"{len(rows)} GL rows")
