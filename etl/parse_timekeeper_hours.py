"""
Parse the "All Timekeepers Hours" export -- per-employee hours for the
current measuring period (fiscal year), split by entity. Powers the
Measuring Period page's hours-required-individuals-by-entity tracker.

Source shape: flat CSV, one row per employee, with a "Company" break row
(entity name in the Company column, blank Employee Name) preceding each
entity's employee rows, plus a leading "TOTALS" row. Column headers carry
the period as text, e.g. "Total Hours 10/1/2025 - 9/30/2026" -- read once
from the header rather than hardcoded, so a new period each fiscal year
doesn't need a code change.

This is hours-to-date within the period, not a final figure -- the sample
is a mid-year pull; re-uploading a fresh export later in the year (or
after the fiscal year closes with real actuals) replaces it the same way
every other snapshot-dated source in this warehouse does.

Output grain: one row per (entity, employee):
    entity, employee_name, total_hours, billable_hours, credited_hours,
    not_credited_hours, pto_hours, hol_hours, period_start, period_end,
    source_file
"""
from __future__ import annotations

import csv
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_all_files, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.timekeeper_hours")

_PERIOD_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})")
_COL_MAP = {
    "Total Hours": "total_hours",
    "Billable Hours": "billable_hours",
    "Credited Hours": "credited_hours",
    "Not Credited Hours": "not_credited_hours",
    "PTO Hours": "pto_hours",
    "HOL Hours": "hol_hours",
}


def _parse_one(path: Path) -> list[dict]:
    logger.info("Parsing All Timekeepers Hours export: %s", path)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)

        period_start = period_end = None
        col_idx: dict[str, int] = {}
        for i, h in enumerate(header):
            for label, field in _COL_MAP.items():
                if h.startswith(label):
                    col_idx[field] = i
                    if period_start is None:
                        m = _PERIOD_RE.search(h)
                        if m:
                            period_start = parse_vp_date(m.group(1))
                            period_end = parse_vp_date(m.group(2))
            if h.strip() == "Company":
                col_idx["entity_raw"] = i
            if h.strip() == "Employee Name":
                col_idx["employee_name"] = i

        rows: list[dict] = []
        entity = None
        for raw in reader:
            if not raw or all(c.strip() == "" for c in raw):
                continue
            entity_raw = raw[col_idx["entity_raw"]].strip() if col_idx.get("entity_raw") is not None else ""
            name = raw[col_idx["employee_name"]].strip() if col_idx.get("employee_name") is not None else ""

            if entity_raw and entity_raw.upper() == "TOTALS":
                continue
            if entity_raw and not name:
                # Entity break row (e.g. "Somos Group LLC") -- carries
                # forward for every employee row until the next one.
                entity = entity_raw
                continue
            if not name:
                continue

            rows.append(
                {
                    "entity": entity,
                    "employee_name": name,
                    "period_start": period_start,
                    "period_end": period_end,
                    "source_file": path.name,
                    **{
                        field: parse_money(raw[idx]) or 0.0
                        for field, idx in col_idx.items()
                        if field not in ("entity_raw", "employee_name") and idx < len(raw)
                    },
                }
            )

    total_billable = round(sum(r.get("billable_hours") or 0.0 for r in rows), 1)
    logger.info(
        "Parsed %d timekeeper/entity rows from %s (%s billable hours total)", len(rows), path.name, total_billable
    )
    return rows


def parse(paths: list[Path] | None = None) -> list[dict]:
    paths = paths if paths is not None else find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["timekeeper_hours"])
    if not paths:
        return []
    all_rows: list[dict] = []
    for path in paths:
        all_rows.extend(_parse_one(path))
    return all_rows


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No timekeeper hours rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "timekeeper_hours.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    print(f"{len(rows)} timekeeper/entity rows across {len({r['entity'] for r in rows})} entities")
