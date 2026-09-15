"""
Parse the origination credit matrix (.xlsx) into a tidy table.

Source shape: already flat -- one row per (client, matter), with one
column per originating attorney holding that attorney's credit fraction
on the matter (fractions across a row sum to ~1.0 when fully assigned).
A "Status" column flags data-quality issues the bookkeeping team already
identified (OK, GAP -- No Origination Assigned, INCOMPLETE -- Sums to
X%, Pro Bono -- No Origination Needed, duplicate rows).

This unblocks origination-credit math (attorney credit x matter revenue)
for the Measuring Period page, but doesn't by itself give dollar
originations -- that still needs to be joined against a revenue source
(WIP or GL) by matter name, which is an approximate join (matter naming
isn't guaranteed identical across exports) done at query time in
dashboard/pages/measuring_period.py, not here. This parser's only job is
to turn the wide credit-fraction matrix into a tidy long form.

Output grain: one row per (client, matter, entity, attorney) with a
nonzero credit fraction:
    client_name, matter_name, entity, attorney, credit_fraction,
    status, source_file

A second table, unassigned matters (status != "OK"), is kept as-is for
a "needs attention" exceptions view:
    client_name, matter_name, entity, status, source_file
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

import config
from etl.common import find_latest_file

logger = logging.getLogger("somos.etl.originations")

_HEADER_ROW = 4
_FIRST_DATA_ROW = 5
_CLIENT_COL, _MATTER_COL, _ENTITY_COL, _STATUS_COL = 1, 2, 3, 13


def parse(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["originations"])
    if path is None:
        logger.warning(
            "No origination matrix found in %s -- skipping. Originations "
            "tracking will be unavailable until one is added.",
            config.RAW_DATA_DIR,
        )
        return [], []
    logger.info("Parsing origination matrix: %s", path)
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    attorney_cols = {}
    for c in range(_ENTITY_COL + 1, _STATUS_COL - 1):
        name = ws.cell(_HEADER_ROW, c).value
        if isinstance(name, str) and name.strip():
            attorney_cols[c] = name.strip()

    credits_ = []
    flagged = []
    entity_map = {"LLC": "Somos Group LLC", "LLP": "Somos Law Group LLP"}
    for r in range(_FIRST_DATA_ROW, ws.max_row + 1):
        client = ws.cell(r, _CLIENT_COL).value
        matter = ws.cell(r, _MATTER_COL).value
        if not client or not matter:
            continue
        entity_code = ws.cell(r, _ENTITY_COL).value
        entity = entity_map.get((entity_code or "").strip(), entity_code)
        status = (ws.cell(r, _STATUS_COL).value or "").strip()

        row_had_credit = False
        for c, attorney in attorney_cols.items():
            frac = ws.cell(r, c).value
            if frac is None or float(frac) == 0:
                continue
            row_had_credit = True
            credits_.append(
                {
                    "client_name": str(client).strip(),
                    "matter_name": str(matter).strip(),
                    "entity": entity,
                    "attorney": attorney,
                    "credit_fraction": float(frac),
                    "status": status or "OK",
                    "source_file": path.name,
                }
            )

        if status and status != "OK" or not row_had_credit:
            flagged.append(
                {
                    "client_name": str(client).strip(),
                    "matter_name": str(matter).strip(),
                    "entity": entity,
                    "status": status or "GAP -- No Origination Assigned",
                    "source_file": path.name,
                }
            )

    logger.info(
        "Parsed %d origination credit lines (%d matters flagged for attention)",
        len(credits_),
        len(flagged),
    )
    return credits_, flagged


def write_processed(credits_: list[dict], flagged: list[dict]) -> tuple[Path | None, Path | None]:
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    import csv

    credits_path = None
    if credits_:
        credits_path = config.PROCESSED_DATA_DIR / "originations.csv"
        with open(credits_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(credits_[0].keys()))
            w.writeheader()
            w.writerows(credits_)
        logger.info("Wrote %d rows -> %s", len(credits_), credits_path)

    flagged_path = None
    if flagged:
        flagged_path = config.PROCESSED_DATA_DIR / "originations_flagged.csv"
        with open(flagged_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(flagged[0].keys()))
            w.writeheader()
            w.writerows(flagged)
        logger.info("Wrote %d rows -> %s", len(flagged), flagged_path)

    return credits_path, flagged_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    credits_, flagged = parse()
    write_processed(credits_, flagged)
    print(f"{len(credits_)} credit lines, {len(flagged)} flagged matters")
    if credits_:
        by_attorney = {}
        for c in credits_:
            by_attorney.setdefault(c["attorney"], 0.0)
            by_attorney[c["attorney"]] += c["credit_fraction"]
        for a, v in sorted(by_attorney.items(), key=lambda kv: -kv[1]):
            print(f"  {a}: {v:.2f} matter-credits")
