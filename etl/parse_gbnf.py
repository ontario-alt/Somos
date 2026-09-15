"""
Parse the "GBNF AR Aged" export -- Gone But Not Forgotten: old, stale
collectibles the firm tracks separately from the regular AR aging book
rather than folding into it. Same "Total for <Client> - <Matter>" /
"Total for <Client>" rollup shape as parse_ar_detail.py's xlsx export,
but a distinct report scanned into its own table (gbnf_ar_aging) --
deliberately never merged into ar_aging_detail, so a GBNF matter's very
old balance never lands in the main aging report's "Over 120" bucket
or "oldest" totals. It shows up only in its own GBNF panel.

Only one entity has been provided a sample for so far (Somos Group LLC,
named in the report header, no "Company: LLC/LLP" break rows inside like
the All AR Report has) -- entity is read from the header line rather than
assumed, so a future LLP GBNF export works without a code change.

Output grain: one row per (client, matter):
    entity, client_name, matter_name, current_0_30, days_31_60,
    days_61_90, days_91_120, over_120, balance, as_of_date, source_file
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_all_files, parse_vp_date

logger = logging.getLogger("somos.etl.gbnf")

_AS_OF_RE = re.compile(r"Aged as of\s+(\d{1,2}/\d{1,2}/\d{4})")
_ENTITY_RE = re.compile(r"Somos (Group LLC|Law Group LLP)")
_HEADER_MAP = {
    "Balance": "balance",
    "Current": "current_0_30",
    "31-60": "days_31_60",
    "61-90": "days_61_90",
    "91-120": "days_91_120",
    "Over 120": "over_120",
}


def _norm(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def _parse_one(path: Path) -> list[dict]:
    logger.info("Parsing GBNF AR Aged export: %s", path)
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    as_of = None
    entity = None
    col_idx: dict[str, int] = {}
    for r in range(1, min(ws.max_row, 15) + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if not isinstance(v, str):
                continue
            if as_of is None:
                m = _AS_OF_RE.search(v)
                if m:
                    as_of = parse_vp_date(m.group(1))
            if entity is None:
                m = _ENTITY_RE.search(v)
                if m:
                    entity = f"Somos {m.group(1)}"
            label = _norm(v)
            if label in _HEADER_MAP:
                col_idx[_HEADER_MAP[label]] = c

    if not {"balance", "current_0_30", "over_120"} <= col_idx.keys():
        logger.warning("Couldn't find the aging-bucket header row in %s -- skipping", path.name)
        return []

    rows: list[dict] = []
    current_client = None
    for r in range(1, ws.max_row + 1):
        label = ws.cell(r, 1).value
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip()

        if label.startswith("Billing Client Name:"):
            current_client = label.replace("Billing Client Name:", "").strip()
            continue

        if not label.startswith("Total for") or current_client is None:
            continue

        name = re.sub(r"^Total for\s*", "", label).strip().strip('"')
        # Only the client-level rollup row -- matter-level "Total for
        # <Client> - <Matter>" rows are skipped so a client with more
        # than one matter isn't double-counted; matter_name is instead
        # recovered from the "Matter Reporting Name:" line just above.
        if name != current_client:
            continue

        matter_name = current_client
        # Look back a few rows for the matter name recorded just before
        # this client's rollup (handles the common one-matter-per-client
        # case seen in the sample; a client with several matters still
        # gets one combined row here rather than being silently dropped).
        for back in range(1, 6):
            v = ws.cell(r - back, 1).value
            if isinstance(v, str) and v.strip().startswith("Matter Reporting Name:"):
                matter_name = v.strip().replace("Matter Reporting Name:", "").strip().strip('"')
                break

        rows.append(
            {
                "entity": entity,
                "client_name": current_client,
                "matter_name": matter_name,
                "as_of_date": as_of,
                "source_file": path.name,
                "current_0_30": round(ws.cell(r, col_idx["current_0_30"]).value or 0.0, 2),
                "days_31_60": round(ws.cell(r, col_idx["days_31_60"]).value or 0.0, 2),
                "days_61_90": round(ws.cell(r, col_idx["days_61_90"]).value or 0.0, 2),
                "days_91_120": round(ws.cell(r, col_idx["days_91_120"]).value or 0.0, 2),
                "over_120": round(ws.cell(r, col_idx["over_120"]).value or 0.0, 2),
                "balance": round(ws.cell(r, col_idx["balance"]).value or 0.0, 2),
            }
        )

    total = round(sum(r["balance"] for r in rows), 2)
    logger.info("Parsed %d GBNF client rows from %s (as of %s, total %.2f)", len(rows), path.name, as_of, total)
    return rows


def parse(paths: list[Path] | None = None) -> list[dict]:
    paths = paths if paths is not None else find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["gbnf"])
    if not paths:
        return []
    all_rows: list[dict] = []
    for path in paths:
        all_rows.extend(_parse_one(path))
    return all_rows


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No GBNF rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "gbnf_ar_aging.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import csv

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
    print(f"{len(rows)} GBNF client/matter rows, total {sum(r['balance'] for r in rows):,.2f}")
