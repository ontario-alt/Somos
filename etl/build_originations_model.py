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
                                  formula below, run on the collected
                                  revenue basis only (see "Revenue basis"
                                  below).

Origination formula
--------------------
This reproduces the firm's own per-matter waterfall (the "Originations
Model" workbook) exactly -- compute_matter_takehome() below is verified
against that workbook's own worked example (Steerpoint / Escondido Mall)
to the penny, see the __main__ smoke check.

    Cost Basis(matter)       = Billed Amount(matter, year)
    Adjusted Revenue         = Collected Amount(matter, year) - Reimbursements
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

Revenue basis: collected only. The firm has decided originations run on
money actually collected from the client, not billed -- so Revenue Basis
above is always Collected (cash receipts) Amount. Billed Amount is still
used, unchanged, as the Cost Basis that sets the Direct/Indirect Cost
percentages (that's a firm-overhead assumption tied to what was invoiced,
not a revenue figure). An earlier version of this module also computed a
billed-basis take-home for comparison; that's been removed now that the
firm has picked collected as the one that pays out.

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
bridge_matter() below: an exact normalized (client_name, matter_name) key
match first (etl/common.py::normalize_join_key), falling back to an exact
client match plus a fuzzy matter-name match (difflib) within that
client's matters when the exact key misses. This recovers some real
matches a strict key would miss (e.g. minor punctuation/wording
differences) but most misses turn out to be matters that simply aren't in
the matter list export at all, not a fuzzy-matchable naming difference --
see OUTSTANDING_DATA_NEEDS item 1 and find_unassigned_matters() below. A
real matter-code column on the origination export would replace this
bridge outright. Originator Costs (100% of the originating attorney's own
paid time on the matter, per the workbook) has no real source at all yet
-- see item 4 -- so it defaults to $0 with that assumption stated in
every row's data_status rather than silently dropped.
"""
from __future__ import annotations

import difflib
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.common import normalize_join_key

logger = logging.getLogger("somos.etl.originations_model")

# A single credit_fraction value at or above this is almost certainly a
# data-entry unit error (e.g. "100" typed meaning 100% instead of the
# fraction 1.0) rather than a real 100x-plus origination share -- flagged
# separately from a genuine multi-attorney over-allocation in
# check_percentage_conflicts() below.
_LIKELY_UNIT_ERROR_THRESHOLD = 1.5


def build_project_list_by_entity(matter_rows: list[dict]) -> list[dict]:
    """One row per real client matter -- matter_list re-sorted (entity,
    client, matter_code) so it reads as a project list per entity rather
    than raw export order. Internal/admin matters (client_name is None
    in matter_list -- office admin, PTO, holiday, pro bono buckets not
    tied to a real client, per parse_matter_list.py) are excluded: they
    aren't client projects and can't carry origination credit, so they
    don't belong on a project list built for that purpose."""
    return sorted(
        (r for r in matter_rows if r.get("client_name")),
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


def build_matter_bridge(matter_rows: list[dict]) -> tuple[dict[str, str], dict[str, list[dict]]]:
    """Two lookup structures used by bridge_matter(): an exact normalized
    (client, matter) key -> matter_code map, and a normalized-client-name
    -> that client's matter rows map for the fuzzy fallback."""
    exact = {
        normalize_join_key(r.get("client_name"), r.get("matter_name")): r.get("matter_code") for r in matter_rows
    }
    by_client: dict[str, list[dict]] = defaultdict(list)
    for r in matter_rows:
        by_client[normalize_join_key(r.get("client_name"))].append(r)
    return exact, by_client


def bridge_matter(
    client_name: str | None,
    matter_name: str | None,
    exact_index: dict[str, str],
    client_index: dict[str, list[dict]],
) -> tuple[str | None, str]:
    """Resolves a free-text (client, matter) pair from the origination
    matrix to a real matter_code, trying an exact normalized-key match
    first and falling back to an exact client match + fuzzy matter-name
    match (difflib, cutoff 0.6) within that client's own matters. Returns
    (matter_code_or_None, match_type), match_type one of "exact",
    "fuzzy", "client_only" (client matched, no matter name came close
    enough), or "no_client_match" (client isn't in the matter list at
    all -- the dominant reason for a miss, see OUTSTANDING_DATA_NEEDS)."""
    key = normalize_join_key(client_name, matter_name)
    if key in exact_index:
        return exact_index[key], "exact"
    candidates = client_index.get(normalize_join_key(client_name))
    if not candidates:
        return None, "no_client_match"
    names = [c["matter_name"] for c in candidates]
    best = difflib.get_close_matches(matter_name or "", names, n=1, cutoff=0.6)
    if not best:
        return None, "client_only"
    match = next(c for c in candidates if c["matter_name"] == best[0])
    return match.get("matter_code"), "fuzzy"


def check_percentage_conflicts(origination_rows: list[dict]) -> list[dict]:
    """Sums every attorney's credit_fraction per matter, across ALL
    origination-matrix rows regardless of the matrix's own Status label
    (a status of "OK" is set per-row by whoever built the matrix and
    isn't itself a guarantee the row's own fraction is sane), and flags
    any matter whose total exceeds 100% -- what the user asked to be
    checked directly rather than trusted from the source label. Returns
    only the matters with a conflict; a clean run returns []."""
    totals: dict[tuple, float] = defaultdict(float)
    max_single: dict[tuple, float] = defaultdict(float)
    for r in origination_rows:
        key = (r["entity"], r["client_name"], r["matter_name"])
        totals[key] += r["credit_fraction"]
        max_single[key] = max(max_single[key], r["credit_fraction"])

    conflicts = []
    for key, total in totals.items():
        if total <= 1.001:
            continue
        entity, client, matter = key
        likely_unit_error = max_single[key] >= _LIKELY_UNIT_ERROR_THRESHOLD
        conflicts.append(
            {
                "entity": entity,
                "client_name": client,
                "matter_name": matter,
                "total_credit_fraction": round(total, 4),
                "likely_cause": (
                    f"Likely a data-entry unit error -- one attorney's fraction is {max_single[key]:g}, "
                    "probably entered as a whole-number percentage (e.g. 100) instead of a fraction (1.0)"
                    if likely_unit_error
                    else "Multiple attorneys' fractions genuinely sum past 100% -- needs correction to the matrix"
                ),
            }
        )
    return sorted(conflicts, key=lambda r: -r["total_credit_fraction"])


def find_unassigned_matters(
    project_list: list[dict],
    origination_rows: list[dict],
    flagged_rows: list[dict],
) -> dict[str, list[dict]]:
    """Two distinct "no origination assigned" views, since they mean
    different things:

    - explicit_gap: matters the origination matrix itself flags as
      unassigned (status "GAP -- No Origination Assigned", including
      duplicate-row GAPs) -- these are in the matrix, just empty.
    - not_in_matrix: real client matters (project_list, i.e. matter_list
      minus internal/admin rows) that don't appear anywhere in the
      origination matrix at all, by bridge_matter()'s exact+fuzzy match
      -- nobody has even considered these for origination yet, which is
      a bigger gap than an explicit GAP row. In practice this is most of
      the miss: see OUTSTANDING_DATA_NEEDS item 1."""
    explicit_gap = [f for f in flagged_rows if (f.get("status") or "").startswith("GAP")]

    matrix_pairs: dict[str, list[str]] = defaultdict(list)
    for r in origination_rows + flagged_rows:
        matrix_pairs[normalize_join_key(r.get("client_name"))].append(r.get("matter_name") or "")

    not_in_matrix = []
    for m in project_list:
        ck = normalize_join_key(m.get("client_name"))
        candidates = matrix_pairs.get(ck)
        if candidates and (
            m["matter_name"] in candidates or difflib.get_close_matches(m["matter_name"], candidates, n=1, cutoff=0.6)
        ):
            continue
        if not candidates:
            not_in_matrix.append({**m, "reason": "Client not present in the origination matrix at all"})
        else:
            not_in_matrix.append({**m, "reason": "Client is in the matrix, but this matter isn't"})

    return {"explicit_gap": explicit_gap, "not_in_matrix": not_in_matrix}


# Cutoffs for flag_similar_assigned_matters() below: tighter when
# comparing across different clients (a same-name coincidence between
# two unrelated clients is far more likely than within one client), so a
# cross-client hit is still worth a human look without flooding the
# report with loose matches.
_SIMILAR_SAME_CLIENT_CUTOFF = 0.6
_SIMILAR_ANY_CLIENT_CUTOFF = 0.85

# A matter name used by this many or more DISTINCT clients among the
# assigned matters is a generic/boilerplate bucket (seen in practice:
# "General Real Estate", "Misc. Corporate Services", "General Advisory
# Services") rather than a real project name -- cross-client fuzzy
# matching against these produces pure noise (every unrelated client
# with a same-named catch-all matter "matches"), so they're excluded
# from the cross-client check entirely. Data-driven rather than a
# hand-maintained denylist, since the exact boilerplate names vary by
# firm and by practice group.
_GENERIC_NAME_CLIENT_THRESHOLD = 3


def flag_similar_assigned_matters(unassigned: list[dict], origination_rows: list[dict]) -> list[dict]:
    """For every unassigned project (no origination credit, whether an
    explicit GAP row or missing from the matrix entirely), looks for a
    similarly-named project that DOES have origination assigned (status
    "OK", credit_fraction > 0) -- catching the case where the same
    project was entered twice under slightly different names/spellings,
    with origination recorded against only one of them. Checks the same
    client first (looser name cutoff, since a near-duplicate under one
    client is the likely real case), then falls back to any client
    (tighter cutoff, and excluding generic/boilerplate matter names --
    see _GENERIC_NAME_CLIENT_THRESHOLD -- since a name coincidence across
    two different clients needs stronger evidence before it's worth a
    human look). Returns the unassigned rows augmented with a
    `similar_assigned_matters` list (empty when nothing similar was
    found) and a `flag` summary string for display."""
    assigned_by_client: dict[str, list[dict]] = defaultdict(list)
    assigned_all: list[dict] = []
    clients_by_name: dict[str, set[str]] = defaultdict(set)
    seen = set()
    for r in origination_rows:
        if r["status"] != "OK" or not r["credit_fraction"]:
            continue
        ck = normalize_join_key(r["client_name"])
        key = (ck, r["matter_name"])
        if key in seen:
            continue
        seen.add(key)
        entry = {"client_name": r["client_name"], "matter_name": r["matter_name"], "entity": r["entity"]}
        assigned_by_client[ck].append(entry)
        assigned_all.append(entry)
        clients_by_name[r["matter_name"]].add(ck)

    generic_names = {name for name, clients in clients_by_name.items() if len(clients) >= _GENERIC_NAME_CLIENT_THRESHOLD}
    specific_assigned_all = [a for a in assigned_all if a["matter_name"] not in generic_names]

    out = []
    for u in unassigned:
        client_name = u.get("client_name")
        matter_name = u.get("matter_name") or ""
        ck = normalize_join_key(client_name)

        same_client_names = [a["matter_name"] for a in assigned_by_client.get(ck, [])]
        same_client_hits = difflib.get_close_matches(matter_name, same_client_names, n=3, cutoff=_SIMILAR_SAME_CLIENT_CUTOFF)

        similar = []
        if same_client_hits:
            similar = [
                {**a, "match_scope": "same client"}
                for a in assigned_by_client[ck]
                if a["matter_name"] in same_client_hits
            ]
        elif matter_name not in generic_names:
            all_names = [a["matter_name"] for a in specific_assigned_all]
            cross_hits = difflib.get_close_matches(matter_name, all_names, n=3, cutoff=_SIMILAR_ANY_CLIENT_CUTOFF)
            if cross_hits:
                similar = [
                    {**a, "match_scope": "different client -- verify this isn't the same project"}
                    for a in specific_assigned_all
                    if a["matter_name"] in cross_hits
                ]

        row = dict(u)
        row["similar_assigned_matters"] = similar
        row["flag"] = (
            "; ".join(f"{s['client_name']} / {s['matter_name']} ({s['match_scope']})" for s in similar)
            if similar
            else ""
        )
        out.append(row)
    return out


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
    """Applies is_eligible() and then compute_matter_takehome() (collected
    revenue basis only -- see this module's docstring) to every
    (attorney, matter) origination-credit row, bridging to a matter_code
    via bridge_matter()'s exact+fuzzy match. Reimbursements and
    Originator Costs have no real source yet, so both default to $0
    (stated in data_status, not hidden) -- see OUTSTANDING_DATA_NEEDS. A
    row only gets a dollar figure when its Cost Basis (billed amount, via
    matter_earnings) and Collected Amount (via cash_receipts) are both
    resolved; otherwise total_take_home/origination_credit are None with
    a data_status explaining exactly what's missing."""
    exact_index, client_index = build_matter_bridge(matter_rows)
    billed_by_code = {r["matter_code"]: r["invoiced_to_date"] for r in matter_earnings_rows}

    collected_by_key: dict[str, float] = defaultdict(float)
    for r in cash_receipt_rows:
        if r.get("receipt_date") and r["receipt_date"].year != year:
            continue
        key = normalize_join_key(r.get("client_name"), r.get("matter_name"))
        collected_by_key[key] += r.get("amount") or 0.0

    out = []
    for r in origination_rows:
        matter_code, match_type = bridge_matter(r["client_name"], r["matter_name"], exact_index, client_index)
        billed = billed_by_code.get(matter_code) if matter_code else None
        collected = collected_by_key.get(normalize_join_key(r["client_name"], r["matter_name"]))

        row = {
            "year": year,
            "entity": r["entity"],
            "client_name": r["client_name"],
            "matter_name": r["matter_name"],
            "matched_matter_code": matter_code,
            "match_type": match_type,
            "attorney": r["attorney"],
            "credit_fraction": r["credit_fraction"],
            "billed_amount": billed,
            "collected_amount": collected,
            "reimbursements": 0.0,
            "originator_costs": 0.0,
            "total_take_home": None,
            "origination_credit_collected": None,
        }

        eligible, reason = is_eligible(r["entity"], r["credit_fraction"], r["status"])
        if not eligible:
            row["data_status"] = reason
            out.append(row)
            continue
        if matter_code is None:
            row["data_status"] = (
                f"NEEDS MATTER CODE -- origination matter name didn't bridge to the matter list ({match_type})"
            )
            out.append(row)
            continue
        if billed is None:
            row["data_status"] = (
                "NEEDS BILLED $ -- matter has a code but no matter_earnings (NTE-tracked) invoiced-to-date figure "
                "to use as Cost Basis"
            )
            out.append(row)
            continue
        if collected is None:
            row["data_status"] = "NEEDS COLLECTED $ -- no cash receipts bridged to this matter for this year"
            out.append(row)
            continue

        result = compute_matter_takehome(collected, billed, 0.0, 0.0)
        row["total_take_home"] = result["total_take_home"]
        row["origination_credit_collected"] = round(r["credit_fraction"] * result["total_take_home"], 2)
        row["data_status"] = (
            f"Dollarized (collected basis, {match_type} match); Reimbursements and Originator Costs assumed $0 "
            "(no source yet); billed amount is matter_earnings life-to-date, not a true annual figure -- see "
            "outstanding data needs"
        )
        out.append(row)

    return sorted(out, key=lambda r: (r["attorney"] or "", r["entity"] or "", r["client_name"] or ""))


OUTSTANDING_DATA_NEEDS = """\
Outstanding data needs -- originations model
==============================================

1. Matter code on the origination credit matrix export. It currently
   carries only free-text client/matter names. bridge_matter() tries an
   exact normalized-name match, then a fuzzy fallback (exact client +
   closest matter name), which recovers a modest number of extra
   matches -- but measured directly against the real files provided,
   most misses are NOT a fuzzy-matchable naming difference: the client
   itself isn't in the current Matter List export at all (see this run's
   "not_in_matrix" count from find_unassigned_matters(), and this run's
   match-rate line). That means the bigger fix isn't smarter string
   matching, it's either (a) a real matter-code column on the
   origination export, or (b) a fuller Matter List export that includes
   closed/historical matters, if these are legacy matters that have
   dropped off the active list. Do (a) regardless -- it unblocks
   everything else on this list and removes the guesswork in (b).

2. Collected amount by matter, at scale (billed amount coverage just
   improved a lot). Cost Basis uses matter_earnings' invoiced_to_date,
   now merged from two reports: the NTE Tracking Report (cap-set matters
   only) and the plain Matter Earnings report (every matter with JTD
   activity -- 163 matters in the file provided, a real jump from ~42).
   Collected Amount still uses cash_receipts, which is matter-level and
   real but only pulled for the current weekly/monthly snapshot -- a
   full fiscal year of history is needed before the matched-and-billed
   rows can actually dollarize. Both billed and collected are still JTD
   (life-to-date) rather than split by year, which "originations by
   year" ultimately needs -- see a "Billing History by Matter" report
   (by fiscal year) as the eventual fix for the billed side.

3. Real Reimbursements and Originator Costs data. Both currently default
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

4. Sign-off / cleanup of the origination matrix's flagged and
   unassigned rows -- see find_unassigned_matters()'s two lists:
     - explicit_gap: matters the matrix itself flags "GAP -- No
       Origination Assigned" (including duplicate-row GAPs).
     - not_in_matrix: real client matters that don't appear anywhere in
       the matrix at all, by exact+fuzzy match -- this is typically a
       larger number than explicit_gap and means nobody has even
       considered these matters for origination yet.
   flag_similar_assigned_matters() cross-checks both lists against
   matters that DO have origination assigned, for a similarly-named
   project (same client first, then any client excluding generic/
   boilerplate matter names) -- some unassigned rows are really a typo'd
   or renamed duplicate of an already-assigned matter, not a genuine gap;
   these should be corrected/merged at the source before anyone re-keys
   origination for what's actually the same project.
   Also see check_percentage_conflicts(): every matter's total assigned
   credit_fraction is checked against 100% directly (not trusted from
   the matrix's own Status label). A total over 100% with one attorney's
   single fraction far above 1.0 is almost always a data-entry unit
   error (e.g. "100" typed instead of "1.0" / 100%) -- correct at the
   source; the model does not guess a fix.

5. Historical origination-matrix snapshots. The matrix is parsed as a
   single current snapshot with no year of its own -- "originations by
   year" requires either one matrix file per fiscal year (origination
   can shift year to year, e.g. a matter reassigned to a new
   originating attorney) or a year/effective_date column on the export.

6. Somos Group Mexico's origination process. MX is a real entity already
   in the matter list (config.ENTITIES, MATTER_CODE_ENTITY_PREFIXES["MEX"])
   with matters on the books, so it's flagged here as a future
   originatable entity -- but it has no origination matrix, matter
   earnings, or revenue data yet, so it's deliberately excluded from
   config.ORIGINATABLE_ENTITIES (rows for it are marked "not eligible")
   until the firm builds out an origination process for it.

7. config.ORIGINATION_TARGETS is still empty -- needed for any
   actual-vs-target view once dollars are available.

Resolved: the firm has decided originations run on the COLLECTED
revenue basis only, not billed -- see this module's docstring. Billed
Amount is still used as the Cost Basis for the Direct/Indirect Cost
percentages, just not as an alternate payout basis.
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
        matched = sum(1 for r in origination_by_year if r["matched_matter_code"])
        dollarized = sum(1 for r in origination_by_year if r["origination_credit_collected"] is not None)
        print(
            f"\n{len(origination_rows)} origination-credit rows: {matched} matter-code-matched "
            f"({matched / len(origination_rows):.0%}), {dollarized} dollarized (collected basis)"
        )

        conflicts = check_percentage_conflicts(origination_rows)
        print(f"\n{len(conflicts)} matter(s) with total assigned credit_fraction over 100%:")
        for c in conflicts:
            print(f"  {c['client_name']} / {c['matter_name']}: {c['total_credit_fraction']:.0%} -- {c['likely_cause']}")

        unassigned = find_unassigned_matters(project_list, origination_rows, origination_flagged)
        gap_flagged = flag_similar_assigned_matters(unassigned["explicit_gap"], origination_rows)
        not_in_matrix_flagged = flag_similar_assigned_matters(unassigned["not_in_matrix"], origination_rows)
        n_gap_similar = sum(1 for r in gap_flagged if r["similar_assigned_matters"])
        n_nim_similar = sum(1 for r in not_in_matrix_flagged if r["similar_assigned_matters"])
        print(
            f"\n{len(unassigned['explicit_gap'])} matters explicitly flagged GAP in the matrix "
            f"({n_gap_similar} have a similarly-named project that DOES have origination assigned); "
            f"{len(unassigned['not_in_matrix'])} real client matters don't appear in the matrix at all "
            f"({n_nim_similar} have a similarly-named project that DOES have origination assigned)"
        )

    print("\n" + OUTSTANDING_DATA_NEEDS)
