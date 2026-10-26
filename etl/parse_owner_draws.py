"""
Load the hand-maintained owner draw list -- reference/owner_draws.csv --
so owners are costed at what they actually draw instead of their
Vantagepoint cost rate. Used by:

- Monthly page (Timekeeper Activity cost and margin),
- Measuring Period page (timekeeper profitability -- replaces both the
  cost rate and labor detail's cost extension, which Vantagepoint also
  builds from the cost rate),
- Budget page (starter owner-draw drivers, and each owner's contribution
  after their draw).

One row per owner per draw amount; add a new row with a start_date when
a draw changes, and end the old one the day before:

    full_name,monthly_draw,start_date,end_date,note
    Jane Partner,50000,1/1/2026,,
    Sam Partner,20000,1/1/2026,12/31/2026,
    Sam Partner,25000,1/1/2027,,raise

Blank start_date = since always; blank end_date = still current. Names
match other reports the same way as everywhere else (etl.common.name_key;
add reference/name_aliases.csv rows for spelling differences).

Gitignored: it's partner compensation. Created with just its header row
if missing, and never overwritten once it exists.

Output grain: one row per draw period:
    full_name, name_key, monthly_draw, start_date, end_date, note
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import name_key, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.owner_draws")

_FIELDNAMES = ["full_name", "monthly_draw", "start_date", "end_date", "note"]


def generate_starter(path: Path | None = None) -> Path:
    path = path or config.OWNER_DRAWS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_FIELDNAMES).writeheader()
    logger.info(
        "Generated empty reference/owner_draws.csv -- add one row per owner (full_name, monthly_draw, "
        "optional start_date/end_date) to cost owners at their actual draw instead of their cost rate."
    )
    return path


def parse(path: Path | None = None) -> list[dict]:
    path = path or config.OWNER_DRAWS_PATH
    if not path.exists():
        generate_starter(path)
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            full_name = (row.get("full_name") or "").strip()
            draw = parse_money(row.get("monthly_draw"))
            if not full_name and draw is None:
                continue
            if not full_name or draw is None:
                logger.warning("owner_draws.csv line %d: needs full_name and monthly_draw -- skipped", i)
                continue
            rows.append({
                "full_name": full_name,
                "name_key": name_key(full_name),
                "monthly_draw": draw,
                "start_date": parse_vp_date(row.get("start_date")),
                "end_date": parse_vp_date(row.get("end_date")),
                "note": (row.get("note") or "").strip() or None,
            })
    logger.info("Owner draws: %d row(s) for %d owner(s)", len(rows), len({r["name_key"] for r in rows}))
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for r in parse():
        print(r)
