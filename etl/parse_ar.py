"""
Parse the Vantagepoint AR Aging export into a tidy table.

Source shape (nested tree, flattened to CSV, no indentation):
    Matter row     -> "LLC25-002 PG&E Potter Valley Project Surrender", total, aging buckets...
      Invoice row  -> "12167", total, aging buckets... (Invoice Date blank)
        Line row   -> "", amount, Invoice Date populated, aging buckets...
    ... repeated for every matter, with a leading TOTALS row.

Leaf rows (payment/charge lines) are the only rows with an Invoice Date.
Header rows (matter, invoice) share the same "Matter Invoice" and
"Total Amount" columns as leaves, which is what reconstruct_hierarchy()
uses to figure out where each leaf sits in the matter/invoice tree.

Output grain: one row per AR line item, columns:
    matter_code, matter_name, invoice_number, invoice_date, line_amount,
    current_0_30, days_31_60, days_61_90, days_91_120, over_120,
    ar_comment, invoice_fully_paid, source_file
"""
from __future__ import annotations

import csv
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file, parse_bool_checkbox, parse_money, parse_vp_date, reconstruct_hierarchy

logger = logging.getLogger("somos.etl.ar")

RAW_COLUMNS = [
    "matter_invoice",
    "total_amount",
    "invoice_date",
    "bucket1",
    "bucket2",
    "bucket3",
    "bucket4",
    "bucket5",
    "ar_comment",
    "invoice_fully_paid",
]

_MATTER_CODE_RE = re.compile(r"^([A-Z]{2,4}\d{2,4}-\d{2,4})\s+(.*)$")


def _load_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)  # noqa: F841 -- header is fixed/known, not relied on
        rows = []
        for raw in reader:
            if not raw or all(c == "" for c in raw):
                continue
            row = dict(zip(RAW_COLUMNS, raw))
            rows.append(row)
    # Drop the leading TOTALS row -- it's a report footer, not a matter.
    if rows and rows[0]["matter_invoice"].strip().upper() == "TOTALS":
        rows = rows[1:]
    return rows


def _is_leaf(row: dict) -> bool:
    return row["invoice_date"].strip() != ""


def parse(path: Path | None = None) -> list[dict]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["ar_aging"])
    if path is None:
        raise FileNotFoundError(
            f"No AR aging export found in {config.RAW_DATA_DIR} matching "
            f"{config.SOURCE_FILE_PATTERNS['ar_aging']!r}"
        )
    logger.info("Parsing AR aging export: %s", path)
    rows = _load_rows(path)

    leaves = reconstruct_hierarchy(
        rows,
        level_names=["matter_invoice_raw", "invoice_number"],
        name_field="matter_invoice",
        total_fields=["total_amount"],
        leaf_predicate=_is_leaf,
        money_fields=["total_amount"],
    )

    tidy = []
    for r in leaves:
        matter_raw = r.get("matter_invoice_raw") or ""
        m = _MATTER_CODE_RE.match(matter_raw)
        matter_code, matter_name = (m.group(1), m.group(2)) if m else (None, matter_raw)
        tidy.append(
            {
                "matter_code": matter_code,
                "matter_name": matter_name,
                "invoice_number": r.get("invoice_number"),
                "invoice_date": parse_vp_date(r.get("invoice_date")),
                "line_amount": parse_money(r.get("total_amount")),
                config.AGING_BUCKETS[0]: parse_money(r.get("bucket1")),
                config.AGING_BUCKETS[1]: parse_money(r.get("bucket2")),
                config.AGING_BUCKETS[2]: parse_money(r.get("bucket3")),
                config.AGING_BUCKETS[3]: parse_money(r.get("bucket4")),
                config.AGING_BUCKETS[4]: parse_money(r.get("bucket5")),
                "ar_comment": (r.get("ar_comment") or "").strip() or None,
                "invoice_fully_paid": parse_bool_checkbox(r.get("invoice_fully_paid")),
                "source_file": path.name,
            }
        )
    logger.info("Parsed %d AR line items", len(tidy))
    return tidy


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path:
    out_path = out_path or (config.PROCESSED_DATA_DIR / "ar_aging.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    total = sum(r["line_amount"] or 0 for r in rows)
    print(f"{len(rows)} AR line items, total {total:,.2f}")
