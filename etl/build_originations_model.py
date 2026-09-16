"""
Originations model: three deliverables built from tables the existing
parsers already produce --

  1. Project list by entity   -- matter_list, grouped/sorted by entity
                                  (LLC / LLP / Somos Group Mexico).
  2. Origination % by matter  -- the origination credit matrix, pivoted
                                  to one row per matter with each
                                  attorney's credit fraction as its own
                                  column.
  3. Originations by matter,
     originator and year      -- dollarized origination credit, per the
                                  formula below.

Origination formula
--------------------
    Origination_$(attorney, matter, year)
        = credit_fraction(attorney, matter) x Matter_Revenue(matter, year)

    Attorney_Originations(attorney, year)
        = SUM over matter of Origination_$(attorney, matter, year)

credit_fraction comes straight from the origination credit matrix
(etl/parse_originations.py): the attorney's assigned share of a
matter's origination credit, 0-1, summing to ~1.0 per matter once fully
assigned.

Matter_Revenue(matter, year) is the piece this repo does not yet have a
reliable source for -- see OUTSTANDING_DATA_NEEDS below. This module
dollarizes what it can from matter_earnings (real revenue, but
life-to-date rather than split by year, and only for the subset of
matters with an NTE cap set) and leaves every other row's dollar figure
None with a `data_status` explaining exactly what's missing, rather
than fabricating or silently dropping a number.

Bridging the origination matrix (free-text client/matter names) to the
matter master (matter_code) and to matter_earnings (also keyed by
matter_code) is done by a normalized (client_name, matter_name) key
(etl/common.py::normalize_join_key), since the origination export
carries no matter code of its own. This is an approximate join; a real
matter-code column on the origination export would replace it outright
-- see item 1 of OUTSTANDING_DATA_NEEDS.
"""
from __future__ import annotations

import logging
import sys
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


def build_originations_by_matter_originator_year(
    origination_rows: list[dict],
    matter_rows: list[dict],
    matter_earnings_rows: list[dict],
    year: int,
) -> list[dict]:
    """Applies the formula in this module's docstring to every
    (attorney, matter) origination-credit row. Dollarizes only where a
    normalized-name bridge to a real matter_code and a matter_earnings
    revenue figure both exist; every other row comes back with
    origination_credit_dollars=None and a data_status explaining why,
    rather than a guessed number."""
    matter_key_to_code = {
        normalize_join_key(r.get("client_name"), r.get("matter_name")): r.get("matter_code") for r in matter_rows
    }
    revenue_by_code = {r["matter_code"]: r["jtd_revenue"] for r in matter_earnings_rows}

    out = []
    for r in origination_rows:
        matter_code = matter_key_to_code.get(normalize_join_key(r["client_name"], r["matter_name"]))
        revenue = revenue_by_code.get(matter_code) if matter_code else None

        if r["status"] and r["status"] != "OK":
            dollars, data_status = None, f"Excluded -- origination matrix status '{r['status']}'"
        elif matter_code is None:
            dollars, data_status = None, "NEEDS MATTER CODE -- origination matter name didn't bridge to the matter list"
        elif revenue is None:
            dollars, data_status = None, "NEEDS REVENUE -- matter has a code but no matter_earnings (NTE-tracked) revenue"
        else:
            dollars = round(r["credit_fraction"] * revenue, 2)
            data_status = "JTD proxy -- matter_earnings has no annual breakdown, see outstanding data needs"

        out.append(
            {
                "year": year,
                "entity": r["entity"],
                "client_name": r["client_name"],
                "matter_name": r["matter_name"],
                "matched_matter_code": matter_code,
                "attorney": r["attorney"],
                "credit_fraction": r["credit_fraction"],
                "matter_revenue_jtd": revenue,
                "origination_credit_dollars": dollars,
                "data_status": data_status,
            }
        )
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

2. Revenue by matter BY YEAR. No current source has this. What exists:
     - matter_earnings (NTE Tracking Report): real life-to-date revenue
       per matter, but only for matters with a not-to-exceed cap set
       (~42 of ~315 matters firm-wide), and not split by year.
     - ar_summary_monthly: real $ by client and month, but by CLIENT,
       not matter -- can't isolate one matter's revenue when a client
       has several.
     - wip_by_matter: current-period billing value only (a snapshot,
       not a historical annual series), and billed-at-standard-rate
       WIP, not recognized or collected revenue.
   Need: an export (or GL revenue account structure) that reports $ by
   matter by fiscal year -- e.g. a "Billing History by Matter" or
   "Revenue by Matter by Period" report, or WIP/AR snapshots retained
   and summed at each fiscal year-end.

3. A firm decision on which revenue this model should recognize --
   billed, collected (cash receipts), or GL revenue account. The
   formula multiplies credit_fraction by "Matter_Revenue" but which of
   billed/collected/recognized that means hasn't been specified, and
   they will diverge, especially for slow-pay clients.

4. Sign-off / cleanup of the origination matrix's flagged rows (see
   originations_flagged.csv, the "Matters needing attention" table) --
   "GAP -- No Origination Assigned" and "INCOMPLETE -- Sums to X%" rows
   can't be dollarized until an attorney is actually assigned or the
   fractions are corrected to sum to 100%.

5. Historical origination-matrix snapshots. The matrix is parsed as a
   single current snapshot with no year of its own -- "originations by
   year" requires either one matrix file per fiscal year (origination
   can shift year to year, e.g. a matter reassigned to a new
   originating attorney) or a year/effective_date column on the export.

6. Somos Group Mexico coverage. matter_list/config.py already carry
   this entity (MATTER_CODE_ENTITY_PREFIXES["MEX"]), but no sample
   origination, matter_earnings, or AR export for it has been seen yet
   -- confirm whether MX matters run through the same origination
   matrix or a separate one.

7. config.ORIGINATION_TARGETS is still empty -- needed for any
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

    from etl import parse_matter_earnings, parse_matter_list, parse_originations

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    matter_rows = parse_matter_list.parse()
    origination_rows, origination_flagged = parse_originations.parse()
    matter_earnings_rows = parse_matter_earnings.parse()

    project_list = build_project_list_by_entity(matter_rows)
    origination_pct = build_origination_pct_by_matter(origination_rows)
    year = datetime.date.today().year
    origination_by_year = build_originations_by_matter_originator_year(
        origination_rows, matter_rows, matter_earnings_rows, year
    )

    paths = write_processed(project_list, origination_pct, origination_by_year)
    for name, path in paths.items():
        print(f"{name}: {path}")

    if origination_rows:
        matched = sum(1 for r in origination_by_year if r["matched_matter_code"])
        dollarized = sum(1 for r in origination_by_year if r["origination_credit_dollars"] is not None)
        print(
            f"\n{len(origination_rows)} origination-credit rows: "
            f"{matched} matter-code-matched ({matched / len(origination_rows):.0%}), "
            f"{dollarized} dollarized ({dollarized / len(origination_rows):.0%})"
        )

    print("\n" + OUTSTANDING_DATA_NEEDS)
