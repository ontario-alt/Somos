"""
Parse the Vantagepoint WIP / unbilled report into tidy tables.

Source shape (nested tree, flattened to CSV, no indentation), 3 header
levels deep before the leaf transaction:
    Company row    -> "Somos Group LLC", "", "", "", hours_total, amount_total
      Client row   -> "A Step to Freedom", ...
        Matter row -> "HUD Grant Implementation", ...
          Txn row  -> "", "B", date, employee, hours, amount

Leaf rows are the only ones with a Billing Status ("B" etc.) and
Employee Name populated. Header rows share the same name/hours/amount
columns at every level, which reconstruct_hierarchy() uses to walk the
company -> client -> matter tree via running-subtotal reconciliation.

This file currently doubles as both the WIP/unbilled source and (until a
dedicated "Project earnings & labor" export is available) the labor
transaction detail source -- see the note in build_warehouse.py.

Outputs two tidy tables:
  - wip_transactions: one row per timekeeper transaction (grain used by
    the timekeeper/utilization views)
  - wip_by_matter: one row per matter, with rolled-up hours/amount taken
    directly from the file's own matter-level subtotal (not re-summed
    from leaves, since that's the authoritative WIP balance)
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import find_latest_file, parse_bool_checkbox, parse_money, parse_vp_date, reconstruct_hierarchy

logger = logging.getLogger("somos.etl.wip")

RAW_COLUMNS = [
    "name",
    "billing_status",
    "transaction_date",
    "employee_name",
    "hours",
    "amount",
    "unposted",
]


def _load_rows(path: Path) -> tuple[list[dict], str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        period_label = header[4] if len(header) > 4 else ""  # "Total Hours 8/1/2026 - 8/31/2026"
        rows = []
        for raw in reader:
            if not raw or all(c == "" for c in raw):
                continue
            rows.append(dict(zip(RAW_COLUMNS, raw)))
    if rows and rows[0]["name"].strip().upper() == "TOTALS":
        rows = rows[1:]
    return rows, period_label


def _is_leaf(row: dict) -> bool:
    return row["billing_status"].strip() != "" or row["employee_name"].strip() != ""


def parse(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    path = path or find_latest_file(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["wip"])
    if path is None:
        raise FileNotFoundError(
            f"No WIP export found in {config.RAW_DATA_DIR} matching {config.SOURCE_FILE_PATTERNS['wip']!r}"
        )
    logger.info("Parsing WIP export: %s", path)
    rows, period_label = _load_rows(path)

    by_matter: list[dict] = []

    def _on_close(depth: int, ancestors: list[str], name: str, totals: dict):
        # depth == 2 means this header's parents on the stack are
        # [company, client] -- i.e. the header just closed is the matter.
        if depth == 2:
            by_matter.append(
                {
                    "company": ancestors[0],
                    "client_name": ancestors[1],
                    "matter_name": name,
                    "wip_hours": totals["hours"],
                    "wip_amount": totals["amount"],
                    "period_label": period_label,
                    "source_file": path.name,
                }
            )

    leaves = reconstruct_hierarchy(
        rows,
        level_names=["company", "client_name", "matter_name"],
        name_field="name",
        total_fields=["hours", "amount"],
        leaf_predicate=_is_leaf,
        money_fields=["amount"],
        on_header_close=_on_close,
    )

    transactions = []
    for r in leaves:
        transactions.append(
            {
                "company": r.get("company"),
                "client_name": r.get("client_name"),
                "matter_name": r.get("matter_name"),
                "billing_status": (r.get("billing_status") or "").strip() or None,
                "transaction_date": parse_vp_date(r.get("transaction_date")),
                "employee_name": (r.get("employee_name") or "").strip() or None,
                "hours": float(r.get("hours") or 0),
                "billing_amount": parse_money(r.get("amount")),
                "unposted": parse_bool_checkbox(r.get("unposted")),
                "period_label": period_label,
                "source_file": path.name,
            }
        )

    logger.info("Parsed %d WIP transactions across %d matters", len(transactions), len(by_matter))
    return transactions, by_matter


def write_processed(transactions: list[dict], by_matter: list[dict]) -> tuple[Path, Path]:
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    txn_path = config.PROCESSED_DATA_DIR / "wip_transactions.csv"
    matter_path = config.PROCESSED_DATA_DIR / "wip_by_matter.csv"

    with open(txn_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(transactions[0].keys()) if transactions else [])
        w.writeheader()
        w.writerows(transactions)

    with open(matter_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(by_matter[0].keys()) if by_matter else [])
        w.writeheader()
        w.writerows(by_matter)

    logger.info("Wrote %d transactions -> %s", len(transactions), txn_path)
    logger.info("Wrote %d matter rollups -> %s", len(by_matter), matter_path)
    return txn_path, matter_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    transactions, by_matter = parse()
    write_processed(transactions, by_matter)
    print(f"{len(transactions)} transactions, {len(by_matter)} matters")
    print(f"Total WIP amount (matter rollup): {sum(m['wip_amount'] for m in by_matter):,.2f}")
    print(f"Total billing amount (transactions): {sum(t['billing_amount'] or 0 for t in transactions):,.2f}")
