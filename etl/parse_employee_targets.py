"""
Load (or, on first run, generate a starter for) the hand-maintained
employee billable-hour target assignment -- reference/employee_targets.csv.

Unlike everything else in etl/, this isn't parsed from a Vantagepoint
export: who is an attorney, who is a planner, and who has no target at
all (executives, admin, consultants) is firm policy, not something in
any report. So this is a plain CSV the user edits by hand:

    employee_number,full_name,labor_type,target_type,start_date,end_date
    048,Ramneek Saini,Employee,Planner,,
    051,Jane Example,Employee,Attorney,2/16/2026,
    003,Alfred Fraijo Jr.,Principal,,,

`target_type` is one of config.BILLABLE_HOUR_TARGETS' keys
("Attorney"/"Planner"; legacy "LLP"/"LLC" still accepted, see
config.TARGET_TYPE_ALIASES) or blank for no target. `start_date` /
`end_date` are optional (M/D/YYYY) and only needed for someone who
joined or left during the measuring period -- the target is prorated to
the part of the period they were employed. Both columns may be missing
entirely from an older file. `labor_type` is carried over from the
Employee Cost Rate Details export purely as a hint while filling the
file in (e.g. every "Contractor" is probably blank) -- it isn't used for
anything once target_type is set.

Optional per-person overrides for individual terms (e.g. an offer letter
setting a 1,500 chargeable / 1,600 total guideline with no creditable
allowance): `billable_target` (Hours Expectation), `credit_cap` (creditable
non-billable allowance), `total_target` (Total Activity),
`bonus_threshold`. Blank = the role default from config. A row with a billable_target but no
target_type is still tracked (shown under its own "Custom" role).

If the file doesn't exist yet, generate_starter() creates it from
whatever's in employee_cost_rates (every employee, target_type blank)
so there's something to fill in rather than nothing. It is never
regenerated/overwritten once it exists -- edits are yours to keep.
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import name_key, parse_money, parse_vp_date

logger = logging.getLogger("somos.etl.employee_targets")

_FIELDNAMES = [
    "employee_number", "full_name", "labor_type", "target_type", "start_date", "end_date",
    "billable_target", "credit_cap", "total_target", "bonus_threshold", "staff_group", "designation",
]


def generate_starter(cost_rows: list[dict], path: Path | None = None) -> Path:
    path = path or config.EMPLOYEE_TARGETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for r in cost_rows:
            writer.writerow(
                {
                    "employee_number": r["employee_number"],
                    "full_name": r["full_name"],
                    "labor_type": r.get("labor_type") or "",
                    "target_type": "",
                    "start_date": "",
                    "end_date": "",
                    "billable_target": "",
                    "credit_cap": "",
                    "total_target": "",
                    "bonus_threshold": "",
                    "staff_group": "",
                    "designation": "",
                }
            )
    logger.info(
        "Generated starter reference/employee_targets.csv with %d employees, all target_type "
        "blank -- fill it in (target_type = one of %s, or leave blank for no target) and "
        "re-run build_warehouse.py. Add start_date/end_date only for anyone who joined or "
        "left mid-period.",
        len(cost_rows),
        list(config.BILLABLE_HOUR_TARGETS.keys()),
    )
    return path


def parse(cost_rows: list[dict] | None = None, path: Path | None = None) -> list[dict]:
    path = path or config.EMPLOYEE_TARGETS_PATH
    if not path.exists():
        if not cost_rows:
            logger.warning(
                "No %s and no employee cost rows to seed a starter from -- skipping. "
                "Utilization will be unavailable until this file exists.",
                path,
            )
            return []
        generate_starter(cost_rows, path)

    rows = []
    valid_types = set(config.BILLABLE_HOUR_TARGETS.keys())
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw_type = (row.get("target_type") or "").strip() or None
            target_type = config.resolve_role(raw_type)
            if raw_type and not target_type and not (row.get("billable_target") or "").strip():
                logger.warning(
                    "Unknown target_type %r for %s in %s (expected one of %s or blank) -- "
                    "treating as no target.",
                    raw_type,
                    row.get("full_name"),
                    path,
                    sorted(valid_types),
                )
            full_name = (row.get("full_name") or "").strip()
            rows.append(
                {
                    "employee_number": (row.get("employee_number") or "").strip(),
                    "full_name": full_name,
                    "name_key": name_key(full_name),
                    "target_type": target_type,
                    "start_date": parse_vp_date(row.get("start_date")),
                    "end_date": parse_vp_date(row.get("end_date")),
                    "billable_target": parse_money(row.get("billable_target")),
                    "credit_cap": parse_money(row.get("credit_cap")),
                    "total_target": parse_money(row.get("total_target")),
                    "bonus_threshold": parse_money(row.get("bonus_threshold")),
                    # Free text for people without a requirement (Administrative,
                    # Advisory, Owner, Contractor...) -- groups listed in
                    # config.REVIEW_EXCLUDED_STAFF_GROUPS get their own summary.
                    "staff_group": (row.get("staff_group") or "").strip() or None,
                    # A title that sets the person apart on the hours chart (shaded
                    # differently, own legend entry) -- e.g. "General Counsel".
                    "designation": (row.get("designation") or "").strip() or None,
                }
            )
    n_assigned = sum(1 for r in rows if r["target_type"])
    logger.info("Loaded %d employee target assignments (%d with a target set)", len(rows), n_assigned)
    return rows


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No employee target rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "employee_targets.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from etl import parse_employee_cost

    cost_rows = parse_employee_cost.parse()
    rows = parse(cost_rows)
    write_processed(rows)
    print(f"{len(rows)} employees, {sum(1 for r in rows if r['target_type'])} with a target assigned")
