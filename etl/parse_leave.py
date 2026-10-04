"""
Load (or, on first run, generate an empty starter for) the hand-maintained
approved-leave list -- reference/leave.csv -- used to prorate measuring-
period hour targets.

Like employee_targets.csv, this is firm policy rather than a Vantagepoint
export: Vantagepoint records PTO and holiday hours as labor codes, but an
approved leave of absence (parental, medical, sabbatical, reduced
schedule) that reduces someone's annual target isn't a field in any
report. One row per leave:

    full_name,employee_number,leave_start,leave_end,percent_away,leave_type,note
    Jane Example,051,1/5/2026,3/27/2026,100,Parental,
    Sam Sample,,6/1/2026,8/28/2026,50,Reduced schedule,3-day weeks

`percent_away` is optional and defaults to 100 (fully out); 50 means a
half-time schedule for that span. `leave_end` may be blank for a leave
that's still open (treated as running through the end of the measuring
period). Ordinary PTO and holidays do NOT belong here -- the annual
target already assumes them. `employee_number` is optional; rows match
to employee_targets.csv by number when present, otherwise by name
(format-independent, see etl.common.name_key).

The file is created with just its header row if missing, and never
overwritten once it exists.
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import name_key, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.leave")

_FIELDNAMES = ["full_name", "employee_number", "leave_start", "leave_end", "percent_away", "leave_type", "note"]


def generate_starter(path: Path | None = None) -> Path:
    path = path or config.LEAVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_FIELDNAMES).writeheader()
    logger.info(
        "Generated empty reference/leave.csv -- add one row per approved leave of absence "
        "(full_name, leave_start, leave_end, optional percent_away) to prorate that person's target."
    )
    return path


def parse(path: Path | None = None) -> list[dict]:
    path = path or config.LEAVE_PATH
    if not path.exists():
        generate_starter(path)
        return []

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            full_name = (row.get("full_name") or "").strip()
            leave_start = parse_vp_date(row.get("leave_start"))
            if not full_name or leave_start is None:
                if any((v or "").strip() for v in row.values()):
                    logger.warning("Skipping %s line %d: needs at least full_name and leave_start", path.name, i)
                continue
            leave_end = parse_vp_date(row.get("leave_end"))
            if leave_end is not None and leave_end < leave_start:
                logger.warning("Skipping %s line %d (%s): leave_end is before leave_start", path.name, i, full_name)
                continue
            pct = parse_money(row.get("percent_away"))
            pct = 100.0 if pct is None else min(max(pct, 0.0), 100.0)
            rows.append(
                {
                    "full_name": full_name,
                    "name_key": name_key(full_name),
                    "employee_number": (row.get("employee_number") or "").strip(),
                    "leave_start": leave_start,
                    "leave_end": leave_end,
                    "percent_away": pct,
                    "leave_type": (row.get("leave_type") or "").strip(),
                    "note": (row.get("note") or "").strip(),
                }
            )
    logger.info("Loaded %d approved leave row(s) from %s", len(rows), path.name)
    return rows


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No leave rows to write (none recorded)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "employee_leave.csv")
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
    print(f"{len(rows)} approved leave row(s)")
