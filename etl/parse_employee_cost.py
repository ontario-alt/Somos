"""
Parse the Vantagepoint "Employee Cost Rate Details" export (.xlsx) into
a tidy per-employee cost-rate table -- the piece needed to turn WIP
billing value (value at standard rate) into real cost and margin.

Source shape: this report can be run once per "active company" in
Vantagepoint (the file's own header shows "Somos Group LLC" or "Somos
Law Group LLP"), but checked directly against both sample files: all 62
overlapping employees have byte-identical rates in both -- it's one
firm-wide roster, not per-entity cost data; the entity in the header is
just whichever company happened to be active in the UI when the report
ran, not a real filter. So this parser de-duplicates by employee number
across every file rather than treating "entity" as meaningful, and
`entity` is dropped from the output -- keeping it would wrongly imply
Alfred Fraijo Jr. costs $200k/month to *each* of two entities ($400k
total) when the data only supports one real $200k rate for him firm-
wide. If a future export turns out to genuinely differ by entity,
this will need revisiting (and should show up as a mismatch warning
below, not silently).

Columns: Employee Number, Full Name, Status, Labor Type (Employee/
Principal/Contractor), Job Cost Type (Hourly/Salary), Job Cost Rate.

For "Hourly" employees, Job Cost Rate is a $/hour cost rate -- cost for
a period = hours worked x rate. For "Salary" employees, Job Cost Rate is
a *monthly* figure (confirmed: several rows' rate x 12 lands on a clean
annual salary, e.g. 9166.6667 x 12 = 110,000.00) -- cost for a month is
that rate regardless of hours logged, not hours x rate. This parser
just carries both fields through as-is; that period-vs-hourly split is
applied wherever cost actually gets computed (dashboard), not here.

Full Name here is "First [Nickname] Last[ Suffix]" (e.g. "Younsook
\"Audrey\" Jang", "Alfred Fraijo Jr."), while WIP's employee_name is
"Last[ Suffix], First [Nickname]" (e.g. "Jang, Younsook \"Audrey\"",
"Fraijo Jr., Alfred"). `wip_name` reformats to that convention so this
table can be joined to wip_transactions directly; see __main__ for the
actual match rate against the WIP sample rather than assuming it works.

Output grain: one row per employee (deduplicated across files by
employee_number):
    employee_number, full_name, wip_name, status, labor_type,
    job_cost_type, job_cost_rate, source_file
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_all_files

logger = logging.getLogger("somos.etl.employee_cost")

_SUFFIXES = {"Jr.", "Sr.", "II", "III", "IV"}


def _to_wip_name(full_name: str) -> str:
    """'Alfred Fraijo Jr.' -> 'Fraijo Jr., Alfred'; 'Younsook "Audrey" Jang' -> 'Jang, Younsook "Audrey"'."""
    tokens = full_name.strip().split(" ")
    if not tokens:
        return full_name
    if tokens[-1] in _SUFFIXES and len(tokens) >= 2:
        last = f"{tokens[-2]} {tokens[-1]}"
        first = " ".join(tokens[:-2])
    else:
        last = tokens[-1]
        first = " ".join(tokens[:-1])
    return f"{last}, {first}" if first else last


def _parse_one(path: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    entity = None
    header_row = None
    for r in range(1, min(ws.max_row, 15) + 1):
        b_val = ws.cell(r, 2).value
        if entity is None and isinstance(b_val, str) and b_val.strip():
            entity = b_val.strip()
        c_val = ws.cell(r, 3).value
        if isinstance(c_val, str) and "Employee" in c_val and "Number" in c_val:
            header_row = r

    if header_row is None or entity is None:
        raise ValueError(f"Couldn't find header row / entity in {path}")

    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        emp_number = ws.cell(r, 3).value
        full_name = ws.cell(r, 4).value
        if not emp_number or not full_name:
            continue
        full_name = full_name.strip()
        rows.append(
            {
                "employee_number": str(emp_number).strip(),
                "full_name": full_name,
                "wip_name": _to_wip_name(full_name),
                "status": (ws.cell(r, 5).value or "").strip() or None,
                "labor_type": (ws.cell(r, 6).value or "").strip() or None,
                "job_cost_type": (ws.cell(r, 8).value or "").strip() or None,
                "job_cost_rate": float(ws.cell(r, 9).value or 0),
                "source_file": path.name,
            }
        )
    logger.info("Parsed %d employees for %s from %s", len(rows), entity, path.name)
    return rows


def parse(paths: list[Path] | None = None) -> list[dict]:
    paths = paths or find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["employee_cost"])
    if not paths:
        logger.warning(
            "No Employee Cost Rate Details export found in %s -- skipping. Real "
            "timekeeper cost/margin will be unavailable until one is added.",
            config.RAW_DATA_DIR,
        )
        return []
    by_employee: dict[str, dict] = {}
    conflicts: list[str] = []
    n_overlap = 0
    for path in paths:
        for row in _parse_one(path):
            key = row["employee_number"]
            existing = by_employee.get(key)
            if existing:
                n_overlap += 1
                if existing["job_cost_rate"] != row["job_cost_rate"] or existing["job_cost_type"] != row["job_cost_type"]:
                    conflicts.append(f"{row['full_name']} ({key}): {existing['source_file']} vs {row['source_file']}")
            by_employee[key] = row  # last file wins if it does genuinely differ
    if conflicts:
        logger.warning(
            "%d employee(s) have different rates across cost-rate export files -- "
            "these may genuinely be entity-specific after all; verify before trusting "
            "cost/margin for them: %s",
            len(conflicts),
            conflicts,
        )
    elif n_overlap:
        logger.info(
            "%d employee(s) appeared in more than one export file, all with matching rates "
            "-- treated as one firm-wide roster, not per-entity duplicates.",
            n_overlap,
        )
    return list(by_employee.values())


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No employee cost rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "employee_cost_rates.csv")
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
    print(f"{len(rows)} employees")
    by_type = {}
    for r in rows:
        by_type.setdefault(r["job_cost_type"], 0)
        by_type[r["job_cost_type"]] += 1
    print("by job_cost_type:", by_type)
