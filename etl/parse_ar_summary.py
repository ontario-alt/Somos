"""
Parse the Vantagepoint "AR Summary" export (monthly $ by client, Jan-Dec
plus a Year-to-Date column) into a tidy long-form table.

This is neither AR balance (a point-in-time snapshot) nor cash receipts
(money actually collected) -- it's monthly billed/invoiced activity by
client, which is its own useful thing: it's what gives this app several
months of real history in one shot instead of waiting for weekly/monthly
snapshots to accumulate.

Source shape: TOTALS row, then one row per entity ("Somos Group LLC" /
"Somos Law Group LLP", matched exactly against config.ENTITIES) followed
by that entity's client rows -- except an entity can have *no* client
rows under it (seen in the sample: Somos Law Group LLP has only its own
row, no client breakdown), in which case this parser falls back to
emitting the entity's own row as a single client_name=None record rather
than silently losing that entity's monthly figures.

Output grain: one row per (entity, client, month):
    entity, client_name, month, month_date, amount, source_file
Months with $0 are kept (not filtered) so a client's inactive months
are visible rather than absent -- including future months in the export
that just haven't happened yet (Oct-Dec read as $0, not missing).
`month_date` (the 1st of that month, in the year the export was parsed
for) is what the warehouse upserts by, so this single file's 9-12 months
land as 9-12 real historical snapshots, not one.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime

import config
from etl.common import find_latest_file, parse_money

logger = logging.getLogger("somos.etl.ar_summary")

_MONTH_COLS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def parse(path: Path | None = None, year: int | None = None) -> list[dict]:
    """`year` defaults to the current calendar year -- the export has no
    year column of its own (just month names), and a monthly-AR-summary
    report is realistically always run for the year in progress."""
    year = year or datetime.date.today().year
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["ar_summary"])
    if path is None:
        logger.warning(
            "No AR Summary export found in %s -- skipping. Multi-month billing "
            "history from this source will be unavailable.",
            config.RAW_DATA_DIR,
        )
        return []
    logger.info("Parsing AR Summary: %s", path)

    import csv

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        raw_rows = [r for r in reader if r and r[0].strip()]

    month_idx = {m: header.index(m) for m in _MONTH_COLS if m in header}
    month_date = {m: datetime.date(year, i + 1, 1) for i, m in enumerate(_MONTH_COLS)}

    entity_client_rows: dict[str, list] = {e: [] for e in config.ENTITIES}
    entity_own_row: dict[str, list] = {}
    current_entity = None

    for row in raw_rows:
        label = row[0].strip()
        if label == "TOTALS":
            continue
        if label in config.ENTITIES:
            current_entity = label
            entity_own_row[label] = row
            continue
        if current_entity is None:
            logger.warning("Client row %r seen before any entity row -- skipping", label)
            continue
        entity_client_rows[current_entity].append((label, row))

    tidy: list[dict] = []
    for entity in config.ENTITIES:
        client_rows = entity_client_rows.get(entity, [])
        if client_rows:
            for client_name, row in client_rows:
                for month, idx in month_idx.items():
                    tidy.append(
                        {
                            "entity": entity,
                            "client_name": client_name,
                            "month": month,
                            "month_date": month_date[month],
                            "amount": parse_money(row[idx]) or 0.0,
                            "source_file": path.name,
                        }
                    )
        elif entity in entity_own_row:
            # No client-level breakdown for this entity in the export --
            # fall back to its own row rather than losing the entity entirely.
            row = entity_own_row[entity]
            for month, idx in month_idx.items():
                tidy.append(
                    {
                        "entity": entity,
                        "client_name": None,
                        "month": month,
                        "month_date": month_date[month],
                        "amount": parse_money(row[idx]) or 0.0,
                        "source_file": path.name,
                    }
                )
            logger.info("%s has no client-level rows in this export -- using its own total instead", entity)

    logger.info("Parsed %d (entity, client, month) rows", len(tidy))
    return tidy


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No AR Summary rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "ar_summary_monthly.csv")
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
    print(f"{len(rows)} rows")
    by_entity = {}
    for r in rows:
        by_entity.setdefault(r["entity"], 0.0)
        by_entity[r["entity"]] += r["amount"]
    for e, v in by_entity.items():
        print(f"  {e}: {v:,.2f}")
