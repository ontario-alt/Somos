"""
Parse the Vantagepoint "Project earnings & labor" export into a tidy
table.

STUB -- no sample provided yet. The WIP export we do have (see
parse_wip.py) already gives hours + billing amount by timekeeper/matter,
but billing amount is value at standard billing rate, not actual cost --
there's no margin/profitability math possible without a real cost or
pay-rate figure per timekeeper, which this source is expected to supply.
Update this once a sample lands in data/raw/.

Expected output grain once implemented: one row per project/timekeeper
period, something like:
    entity, matter_name, employee_name, period, hours,
    revenue_amount, cost_amount, source_file
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file

logger = logging.getLogger("somos.etl.earnings")


def parse(path: Path | None = None) -> list[dict]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["earnings"])
    if path is None:
        logger.warning(
            "No project earnings & labor export found in %s matching %r -- skipping. "
            "P&L margin and timekeeper cost figures will be unavailable until a "
            "sample export is added and this parser is implemented.",
            config.RAW_DATA_DIR,
            config.SOURCE_FILE_PATTERNS["earnings"],
        )
        return []
    raise NotImplementedError(
        f"Found an earnings export at {path}, but parse_earnings.py hasn't been "
        "implemented against its real column layout yet."
    )


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No earnings rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "earnings.csv")
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
    print(f"{len(rows)} earnings rows")
