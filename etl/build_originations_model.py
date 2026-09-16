"""
Originations model: three deliverables built from tables the existing
parsers already produce --

  1. Project list by entity   -- matter_list, grouped/sorted by entity
                                  (LLC / LLP; Somos Group Mexico exists
                                  as an entity but has no origination
                                  process yet -- see ORIGINATABLE_ENTITIES
                                  in config.py).
  2. Origination % by matter  -- the origination credit matrix, pivoted
                                  to one row per matter with each
                                  attorney's credit fraction as its own
                                  column.
  3. Originations by matter,
     originator and year      -- dollarized origination credit, per the
                                  formula below, computed on both a
                                  billed and a collected revenue basis.

Origination formula
--------------------
This reproduces the firm's own per-matter waterfall (the "Originations
Model" workbook) exactly -- compute_matter_takehome() below is verified
against that workbook's own worked example (Steerpoint / Escondido Mall)
to the penny, see the __main__ smoke check.

    Cost Basis(matter)       = Billed Amount(matter, year)
    Adjusted Revenue         = Revenue Basis(matter, year) - Reimbursements
    Direct Costs             = Cost Basis x config.ORIGINATION_DIRECT_COST_PCT
    Indirect Costs           = Cost Basis x config.ORIGINATION_INDIRECT_COST_PCT
    Gross Profit to Somos    = Adjusted Revenue - Direct Costs
                                - Originator Costs - Indirect Costs
    Capital Expense Adj.     = Gross Profit to Somos x config.ORIGINATION_CAPITAL_EXPENSE_PCT
    Total Take Home(matter)  = Gross Profit to Somos - Capital Expense Adj.

    Origination_$(attorney, matter, year)
        = credit_fraction(attorney, matter) x Total Take Home(matter, year)

    Attorney_Originations(attorney, year)
        = SUM over matter of Origination_$(attorney, matter, year)

Revenue Basis is run twice per matter, once as Billed Amount and once as
Collected (cash receipts) Amount -- the workbook itself uses collected
("Total Amount Paid by Client") for revenue while using billed ("Initial
Billed Amount") as the Cost Basis for the Direct/Indirect Cost
percentages; this module keeps that same Cost Basis but reports take-home
under both revenue bases side by side, since the firm hasn't picked one
(see OUTSTANDING_DATA_NEEDS item 3).

Eligibility
-----------
A (matter, attorney) pair is run through the formula at all only if
is_eligible() below says yes: origination-matrix status is "OK" (not a
GAP/INCOMPLETE/Pro-Bono/duplicate row), credit_fraction > 0, and the
matter's entity is in config.ORIGINATABLE_ENTITIES. Ineligible rows are
still listed in the output with a reason -- never silently dropped.

Data bridges
------------
The origination matrix carries no matter code, only free-text client/
matter names, so bridging it to the matter master (matter_code), to
matter_earnings (billed amount, keyed by matter_code) and to cash
receipts (collected amount, keyed by client_name/matter_name) is done by
a normalized (client_name, matter_name) key
(etl/common.py::normalize_join_key). This is an approximate join; a real
matter-code column on the origination export would replace it outright
-- see OUTSTANDING_DATA_NEEDS item 1. Originator Costs (100% of the
originating attorney's own paid time on the matter, per the workbook) has
no real source at all yet -- see item 4 -- so it defaults to $0 with that
assumption stated in every row's data_status rather than silently
dropped.
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import normalize_join_key

logger = logging.getLogger("somos.etl.originations_model")


def build_project_list_by_entity(matter_rows: list[dict]) -> list[dict]:
    """One row per matter -- matter_list re-sorted (entity, client,
    matter_code) so it reads as a project list per entity rather than
    raw export order."""
    return sorted(
        matter_rows,
        key=lambda r: (r.get("entity") or "", r.get("client_name") or "", r.get("matter_code") or ""),
    )


def build_origination_pct_by_matter(origination_rows: list[dict]) -> list[dict]:
    """Pivots the long-form origination credits (one row per matter x
    attorney) to one row per matter, with each attorney's credit
    fraction as its own column plus a total (~1.0 when fully assigned)
    -- the "% origination by matter" list."""
    by_matter: dict[tuple, dict] = {}
    attorneys: set[str] = set()
    for r in origination_rows:
        key = (r["entity"], r["client_name"], r["matter_name"])
        row = by_matter.setdefault(
            key,
            {
                "entity": r["entity"],
                "client_name": r["client_name"],
                "matter_name": r["matter_name"],
                "status": r["status"],
            },
        )
        row[r["attorney"]] = row.get(r["attorney"], 0.0) + r["credit_fraction"]
        attorneys.add(r["attorney"])

    out = []
    for row in by_matter.values():
        row["total_credit_fraction"] = round(sum(row.get(a, 0.0) for a in attorneys), 4)
        out.append(row)
    return sorted(out, key=lambda r: (r["entity"] or "", r["client_name"] or "", r["matter_name"] or ""))


def is_eligible(entity: str | None, credit_fraction: float | None, status: str | None) -> tuple[bool, str]:
    """A (matter, attorney) origination-credit row must clear all three
    of these before the take-home formula runs at all. Ineligible rows
    are still surfaced downstream with the reason, never dropped."""
    if status and status != "OK":
        return False, f"Not eligible -- origination matrix status '{status}'"
    if not credit_fraction or credit_fraction <= 0:
        return False, "Not eligible -- no origination credit fraction assigned"
    if entity not in config.ORIGINATABLE_ENTITIES:
        return False, f"Not eligible -- {entity} is not yet an originatable entity (see config.ORIGINATABLE_ENTITIES)"
    return True, "Eligible"


def compute_matter_takehome(
    revenue: float,
    cost_basis: float,
    reimbursements: float,
    originator_costs: float,
    direct_cost_pct: float = config.ORIGINATION_DIRECT_COST_PCT,
    indirect_cost_pct: float = config.ORIGINATION_INDIRECT_COST_PCT,
    capital_expense_pct: float = config.ORIGINATION_CAPITAL_EXPENSE_PCT,
) -> dict:
    """The per-matter waterfall in this module's docstring, as pure
    arithmetic over already-resolved dollar inputs -- see the __main__
    block for the worked-example check against the source workbook."""
    adjusted_revenue = revenue - reimbursements
    direct_costs = cost_basis * direct_cost_pct
    indirect_costs = cost_basis * indirect_cost_pct
    gross_profit_to_somos = adjusted_revenue - direct_costs - originator_costs - indirect_costs
    capital_expense_adjustment = gross_profit_to_somos * capital_expense_pct
    total_take_home = gross_profit_to_somos - capital_expense_adjustment
    return {
        "adjusted_revenue": round(adjusted_revenue, 2),
        "direct_costs": round(direct_costs, 2),
        "originator_costs": round(originator_costs, 2),
        "indirect_costs": round(indirect_costs, 2),
        "gross_profit_to_somos": round(gross_profit_to_somos, 2),
        "capital_expense_adjustment": round(capital_expense_adjustment, 2),
        "total_take_home": round(total_take_home, 2),
    }


def build_originations_by_matter_originator_year(
    origination_rows: list[dict],
    matter_rows: list[dict],
    matter_earnings_rows: list[dict],
    cash_receipt_rows: list[dict],
    year: int,
) -> list[dict]:
    """Applies is_eligible() and then compute_matter_takehome() (twice --
    billed basis and collected basis) to every (attorney, matter)
    origination-credit row. Reimbursements and Originator Costs have no
    real source yet, so both default to $0 (stated in data_status, not
    hidden) -- see OUTSTANDING_DATA_NEEDS. A row only gets a dollar
    figure when its Cost Basis (billed amount, via matter_earnings) and
    the relevant Revenue Basis are both resolved; otherwise the take-home
    columns are None with a data_status explaining exactly what's
    missing."""
    matter_key_to_code = {
        normalize_join_key(r.get("client_name"), r.get("matter_name")): r.get("matter_code") for r in matter_rows
    }
    billed_by_code = {r["matter_code"]: r["invoiced_to_date"] for r in matter_earnings_rows}

    collected_by_key: dict[str, float] = defaultdict(float)
    for r in cash_receipt_rows:
        if r.get("receipt_date") and r["receipt_date"].year != year:
            continue
        key = normalize_join_key(r.get("client_name"), r.get("matter_name"))
        collected_by_key[key] += r.get("amount") or 0.0

    out = []
    for r in origination_rows:
        key = normalize_join_key(r["client_name"], r["matter_name"])
        matter_code = matter_key_to_code.get(key)
        billed = billed_by_code.get(matter_code) if matter_code else None
        collected = collected_by_key.get(key)

        row = {
            "year": year,
            "entity": r["entity"],
            "client_name": r["client_name"],
            "matter_name": r["matter_name"],
            "matched_matter_code": matter_code,
            "attorney": r["attorney"],
            "credit_fraction": r["credit_fraction"],
            "billed_amount": billed,
            "collected_amount": collected,
            "reimbursements": 0.0,
            "originator_costs": 0.0,
            "origination_credit_billed": None,
            "origination_credit_collected": None,
        }

        eligible, reason = is_eligible(r["entity"], r["credit_fraction"], r["status"])
        if not eligible:
            row["data_status"] = reason
            out.append(row)
            continue
        if matter_code is None:
            row["data_status"] = "NEEDS MATTER CODE -- origination matter name didn't bridge to the matter list"
            out.append(row)
            continue
        if billed is None:
            row["data_status"] = (
                "NEEDS BILLED $ -- matter has a code but no matter_earnings (NTE-tracked) invoiced-to-date figure "
                "to use as Cost Basis"
            )
            out.append(row)
            continue

        statuses = []
        billed_result = compute_matter_takehome(billed, billed, 0.0, 0.0)
        row["origination_credit_billed"] = round(r["credit_fraction"] * billed_result["total_take_home"], 2)

        if collected is None:
            statuses.append(
                "NEEDS COLLECTED $ -- no cash receipts bridged to this matter for this year "
                "(collected-basis take-home not computed)"
            )
        else:
            collected_result = compute_matter_takehome(collected, billed, 0.0, 0.0)
            row["origination_credit_collected"] = round(r["credit_fraction"] * collected_result["total_take_home"], 2)

        statuses.append(
            "Reimbursements and Originator Costs assumed $0 (no source yet); billed amount is "
            "matter_earnings life-to-date, not a true annual figure -- see outstanding data needs"
        )
        row["data_status"] = "; ".join(statuses)
        out.append(row)

    return sorted(out, key=lambda r: (r["attorney"] or "", r["entity"] or "", r["client_name"] or ""))


OUTSTANDING_DATA_NEEDS = """\
Outstanding data needs -- originations model
==============================================

1. Matter code on the origination credit matrix export. It currently
   carries only free-text client/matter names, which bridge to the
   matter master (matter_list, matter_code) for only a minority of rows
   by normalized name (see this run's match-rate line). Ask whoever
   maintains the origination workbook to add the same matter code
   AR/WIP/matter_earnings already use (e.g. "LLC25-002") as its own
   column. This single fix unblocks everything else on this list.

2. Billed amount by matter BY YEAR. The formula's Cost Basis and
   billed-basis Revenue currently use matter_earnings' invoiced_to_date,
   which is life-to-date and only covers matters with a not-to-exceed
   cap set (~42 of ~315 matters firm-wide). Need an export (or GL
   revenue account structure) that reports billed $ by matter by fiscal
   year -- e.g. a "Billing History by Matter" report.

3. A firm decision on which Revenue Basis is the one that actually pays
   out -- billed or collected -- rather than showing both. This module
   computes both (origination_credit_billed / origination_credit_collected)
   because the firm hasn't picked one; they will diverge, especially for
   slow-pay clients.

4. Real Reimbursements and Originator Costs data. Both currently default
   to $0 in every calculated row:
     - Reimbursements (pass-through/third-party expenses to deduct from
       revenue) -- no export currently carries this at the matter level.
     - Originator Costs (100% of the originating attorney's own paid
       time on the matter, per the workbook's Adjustment #3) -- needs
       payroll/draw data tied to the attorney's own billed hours on that
       specific matter; wip_transactions has employee-level billing
       amounts per matter but isn't confirmed to represent "time paid",
       so it isn't used here without sign-off.
   Until both are sourced, every take-home figure understates the firm's
   actual deductions.

5. Sign-off / cleanup of the origination matrix's flagged rows (see
   originations_flagged.csv, the "Matters needing attention" table) --
   "GAP -- No Origination Assigned" and "INCOMPLETE -- Sums to X%" rows
   are correctly excluded as not eligible, but can't be dollarized until
   an attorney is actually assigned or the fractions are corrected to
   sum to 100%.

6. Historical origination-matrix snapshots. The matrix is parsed as a
   single current snapshot with no year of its own -- "originations by
   year" requires either one matrix file per fiscal year (origination
   can shift year to year, e.g. a matter reassigned to a new
   originating attorney) or a year/effective_date column on the export.

7. Somos Group Mexico's origination process. MX is a real entity already
   in the matter list (config.ENTITIES, MATTER_CODE_ENTITY_PREFIXES["MEX"])
   with matters on the books, so it's flagged here as a future
   originatable entity -- but it has no origination matrix, matter
   earnings, or revenue data yet, so it's deliberately excluded from
   config.ORIGINATABLE_ENTITIES (rows for it are marked "not eligible")
   until the firm builds out an origination process for it.

8. config.ORIGINATION_TARGETS is still empty -- needed for any
   actual-vs-target view once dollars are available.
"""


def write_processed(
    project_list: list[dict],
    origination_pct: list[dict],
    origination_by_year: list[dict],
) -> dict[str, Path | None]:
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    import csv

    paths: dict[str, Path | None] = {}

    def _write(name: str, rows: list[dict]):
        if not rows:
            logger.info("No rows for %s (source not available)", name)
            paths[name] = None
            return
        out_path = config.PROCESSED_DATA_DIR / f"{name}.csv"
        fieldnames = sorted({k for row in rows for k in row})
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        logger.info("Wrote %d rows -> %s", len(rows), out_path)
        paths[name] = out_path

    _write("project_list_by_entity", project_list)
    _write("originations_pct_by_matter", origination_pct)
    _write("originations_by_matter_originator_year", origination_by_year)

    needs_path = config.PROCESSED_DATA_DIR / "originations_outstanding_data_needs.txt"
    needs_path.write_text(OUTSTANDING_DATA_NEEDS, encoding="utf-8")
    paths["outstanding_data_needs"] = needs_path

    return paths


if __name__ == "__main__":
    import datetime

    from etl import parse_matter_earnings, parse_matter_list, parse_originations, parse_receipts

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Formula smoke check against the source workbook's own worked
    # example (Steerpoint / Escondido Mall) -- must match to the penny.
    check = compute_matter_takehome(revenue=50258.20, cost_basis=75175.11, reimbursements=0.0, originator_costs=8252.72)
    assert abs(check["total_take_home"] - (-5486.67)) < 0.01, check
    logger.info("Formula smoke check OK: %s", check)

    matter_rows = parse_matter_list.parse()
    origination_rows, origination_flagged = parse_originations.parse()
    matter_earnings_rows = parse_matter_earnings.parse()
    try:
        cash_receipt_rows = parse_receipts.parse()
    except FileNotFoundError:
        cash_receipt_rows = []

    project_list = build_project_list_by_entity(matter_rows)
    origination_pct = build_origination_pct_by_matter(origination_rows)
    year = datetime.date.today().year
    origination_by_year = build_originations_by_matter_originator_year(
        origination_rows, matter_rows, matter_earnings_rows, cash_receipt_rows, year
    )

    paths = write_processed(project_list, origination_pct, origination_by_year)
    for name, path in paths.items():
        print(f"{name}: {path}")

    if origination_rows:
        eligible = sum(1 for r in origination_by_year if r["data_status"] and not r["data_status"].startswith("Not eligible"))
        billed_dollarized = sum(1 for r in origination_by_year if r["origination_credit_billed"] is not None)
        collected_dollarized = sum(1 for r in origination_by_year if r["origination_credit_collected"] is not None)
        print(
            f"\n{len(origination_rows)} origination-credit rows: {eligible} eligible, "
            f"{billed_dollarized} billed-basis dollarized, {collected_dollarized} collected-basis dollarized"
        )

    print("\n" + OUTSTANDING_DATA_NEEDS)
