"""
Parse the Vantagepoint cash receipts export -- a flat file (no nested
tree, unlike AR/WIP) used for the weekly cash position page.

Note: this is not one of the five official source types the warehouse
is built from; it's a supplementary "cash in" feed for the weekly page.
Cash disbursements (cash out) has no sample yet -- see config.py /
build_warehouse.py for where that plugs in once available.

Output grain: one row per receipt line:
    client_name, matter_name, receipt_date, invoice_number, amount, source_file
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.receipts")

RAW_COLUMNS = ["client_name", "matter_name", "receipt_date", "invoice_number", "amount"]


def parse(path: Path | None = None) -> list[dict]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["cash_receipts"])
    if path is None:
        raise FileNotFoundError(
            f"No cash receipts export found in {config.RAW_DATA_DIR} matching "
            f"{config.SOURCE_FILE_PATTERNS['cash_receipts']!r}"
        )
    logger.info("Parsing cash receipts export: %s", path)

    tidy = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for raw in reader:
            if not raw or all(c == "" for c in raw):
                continue
            row = dict(zip(RAW_COLUMNS, raw))
            if row["client_name"].strip().upper() == "TOTALS":
                continue
            tidy.append(
                {
                    "client_name": row["client_name"].strip() or None,
                    "matter_name": row["matter_name"].strip() or None,
                    "receipt_date": parse_vp_date(row["receipt_date"]),
                    "invoice_number": row["invoice_number"].strip() or None,
                    "amount": parse_money(row["amount"]),
                    "source_file": path.name,
                }
            )
    logger.info("Parsed %d cash receipt lines", len(tidy))
    return tidy


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path:
    out_path = out_path or (config.PROCESSED_DATA_DIR / "cash_receipts.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    total = sum(r["amount"] or 0 for r in rows)
    print(f"{len(rows)} receipt lines, total {total:,.2f}")
