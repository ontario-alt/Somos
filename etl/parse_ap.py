"""
Parse the Vantagepoint AP Aging export into a tidy table.

STUB -- no sample AP aging export has been provided yet. Based on the
AR aging export's shape (same Vantagepoint "aging detail" report family),
this will very likely be the same nested tree pattern: Vendor > Bill >
line, with the same rolling-30-day bucket columns. Once a sample lands
in data/raw/, update RAW_COLUMNS / the leaf predicate / bucket mapping
below to match it exactly -- don't assume, verify against the real file
the way parse_ar.py's column layout was verified against AR_Aging_1.csv.

Expected output grain once implemented: one row per AP line item:
    vendor_name, bill_number, bill_date, line_amount,
    current_0_30, days_31_60, days_61_90, days_91_120, over_120,
    source_file
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file

logger = logging.getLogger("somos.etl.ap")


def parse(path: Path | None = None) -> list[dict]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["ap_aging"])
    if path is None:
        logger.warning(
            "No AP aging export found in %s matching %r -- skipping. "
            "AP pages will be empty until a sample export is added and this "
            "parser is implemented against its real column layout.",
            config.RAW_DATA_DIR,
            config.SOURCE_FILE_PATTERNS["ap_aging"],
        )
        return []
    raise NotImplementedError(
        f"Found an AP aging export at {path}, but parse_ap.py hasn't been "
        "implemented against real AP column layout yet. Share the file's "
        "header row and this parser can be finished the same way parse_ar.py "
        "was verified against AR_Aging_1.csv."
    )


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No AP rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "ap_aging.csv")
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
    print(f"{len(rows)} AP line items")
