"""
Parse the Vantagepoint "All AR Report" export (PDF) into a tidy,
client-level AR aging table.

This is a *different* Vantagepoint report than the AR Aging export
parse_ar.py handles: that one is invoice/payment-line detail with no
client field (just a matter code + free-text description); this one is
matter-level with an explicit client name, grouped by entity
("Company: LLC ..." / "Company: LLP ..." break lines), one row per
matter reading "Total for <Client> - <Matter> <bucket amounts...>".
This is the source the target weekly AR report (Summary / Priority
Board / Client Rollup) is built from -- client-level rollups and
concentration need the client field this report has and the other one
doesn't.

Only a PDF sample has been provided. Vantagepoint can very likely export
this same report to CSV or Excel too, which would be far more reliable
than PDF layout parsing -- ask for that if this ever breaks on a new
export. Column values are recovered by matching each number's x-position
against the header's column x-positions (blank cells are simply absent
in the PDF, not "0.00", so this can't be done by column order alone).
Verified against the sample: computed bucket sums reconcile exactly to
the report's own "Final Totals" line.

Known limitation: a handful of rows (1 of 104 in the sample) lose their
client segment when the PDF's own line-wrap drops it before the parser
ever sees it (the row prints just the matter name, no "<client> - "
prefix) -- these come through with client_name == matter_name. Flagged
via the `client_name_confidence` column rather than silently guessed at.

Output grain: one row per (entity, client, matter):
    entity, client_name, matter_name, client_name_confidence,
    current_0_30, days_31_60, days_61_90, days_91_120, over_120,
    balance, as_of_date, source_file
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber

import config
from etl.common import find_all_files, parse_vp_date

logger = logging.getLogger("somos.etl.ar_detail")

_MONEY_RE = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?$")
_HEADER_LABELS = {
    "Current": "current_0_30",
    "31-60": "days_31_60",
    "61-90": "days_61_90",
    "91-120": "days_91_120",
    "Balance": "balance",
}
_AS_OF_RE = re.compile(r"Aged as of\s+(\d{1,2}/\d{1,2}/\d{4})")
_COMPANY_RE = re.compile(r"Company:\s*(LLC|LLP)")
_FOOTER_RE = re.compile(r"^-\s*Page")


def _parse_money(s: str) -> float:
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    v = float(s)
    return -v if neg else v


def _column_x1(page) -> dict[str, float]:
    """Map bucket column name -> right-edge x position, from this page's
    own header row (so it's re-derived per page rather than assumed
    constant, in case column widths shift)."""
    x1 = {}
    for w in page.extract_words():
        col = _HEADER_LABELS.get(w["text"])
        if col:
            x1[col] = w["x1"]
        if w["text"] == "Over" and w["top"] < 120:
            x1["over_120"] = w["x1"] + 0.6  # "120" wraps below "Over"; edge is close enough
    return x1


def _nearest_column(x1: float, columns: dict[str, float]) -> str:
    return min(columns.items(), key=lambda kv: abs(kv[1] - x1))[0]


def _parse_one(path: Path) -> tuple[list[dict], dict | None]:
    logger.info("Parsing All AR Report: %s", path)

    entity_map = {"LLC": "Somos Group LLC", "LLP": "Somos Law Group LLP"}
    rows: list[dict] = []
    final_totals: dict | None = None
    entity = None
    as_of = None

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            columns = _column_x1(page)
            words = page.extract_words()

            if as_of is None:
                page_text = page.extract_text() or ""
                m = _AS_OF_RE.search(page_text)
                if m:
                    as_of = parse_vp_date(m.group(1))

            lines: dict[int, list[dict]] = {}
            for w in words:
                lines.setdefault(round(w["top"]), []).append(w)
            tops = sorted(lines.keys())

            i = 0
            while i < len(tops):
                lwords = sorted(lines[tops[i]], key=lambda w: w["x0"])
                text_line = " ".join(w["text"] for w in lwords)

                m = _COMPANY_RE.search(text_line)
                if m:
                    entity = entity_map[m.group(1)]
                    i += 1
                    continue

                if text_line.startswith("Final Totals (Interest Included)"):
                    nums = [w for w in lwords if _MONEY_RE.match(w["text"])]
                    final_totals = {_nearest_column(w["x1"], columns): _parse_money(w["text"]) for w in nums}
                    i += 1
                    continue

                if not text_line.startswith("Total for"):
                    i += 1
                    continue

                nums = [w for w in lwords if _MONEY_RE.match(w["text"])]
                bucket_vals = {_nearest_column(w["x1"], columns): _parse_money(w["text"]) for w in nums}
                label_parts = [w["text"] for w in lwords if not _MONEY_RE.match(w["text"])]

                j = i + 1
                while j < len(tops):
                    nxt_words = sorted(lines[tops[j]], key=lambda w: w["x0"])
                    nxt_text = " ".join(w["text"] for w in nxt_words)
                    if (
                        nxt_text.startswith("Total for")
                        or nxt_text.startswith("Company:")
                        or nxt_text.startswith("Final Totals")
                        or nxt_text.startswith("Distribution")
                        or nxt_text.startswith("Interest")
                        or nxt_text.startswith("AR Aged")
                        or nxt_text.startswith("Invoice")
                        or _FOOTER_RE.match(nxt_text)
                    ):
                        break
                    if any(_MONEY_RE.match(w["text"]) for w in nxt_words):
                        break
                    label_parts.extend(w["text"] for w in nxt_words)
                    j += 1

                label = re.sub(r"^Total for\s*", "", " ".join(label_parts)).strip()
                if " - " in label:
                    client_name, matter_name = label.split(" - ", 1)
                    confidence = "ok"
                else:
                    client_name, matter_name = label, label
                    confidence = "matter_only"  # PDF dropped the client segment for this row

                rec = {
                    "entity": entity,
                    "client_name": client_name.strip(),
                    "matter_name": matter_name.strip(),
                    "client_name_confidence": confidence,
                    "as_of_date": as_of,
                    "source_file": path.name,
                }
                for col in config.AGING_BUCKETS + ["balance"]:
                    rec[col] = round(bucket_vals.get(col, 0.0), 2)
                rows.append(rec)
                i = j

    if final_totals:
        computed = {c: round(sum(r.get(c, 0.0) for r in rows), 2) for c in config.AGING_BUCKETS + ["balance"]}
        mismatches = {
            c: (computed[c], final_totals.get(c))
            for c in computed
            if c in final_totals and abs(computed[c] - final_totals[c]) > 0.02
        }
        if mismatches:
            logger.warning("Parsed totals don't reconcile to the report's Final Totals: %s", mismatches)
        else:
            logger.info("Parsed totals reconcile exactly to the report's Final Totals line.")

    logger.info("Parsed %d client/matter AR rows from %s", len(rows), path.name)
    return rows, final_totals


def parse(paths: list[Path] | None = None) -> tuple[list[dict], dict | None]:
    """Parses every matching "All AR Report" PDF in data/raw/, not just the
    newest -- each carries its own "Aged as of" date (the as_of_date
    column), so dropping several weeks' worth of exports in at once
    backfills real history rather than only ever holding one snapshot."""
    paths = paths or find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS["ar_detail"])
    if not paths:
        logger.warning(
            "No 'All AR Report' PDF found in %s -- skipping. Client-level AR "
            "rollups (weekly Summary/Priority Board/Client Rollup) will be "
            "unavailable until one is added.",
            config.RAW_DATA_DIR,
        )
        return [], None
    all_rows: list[dict] = []
    last_final_totals = None
    for path in paths:
        rows, final_totals = _parse_one(path)
        all_rows.extend(rows)
        last_final_totals = final_totals
    return all_rows, last_final_totals


def write_processed(rows: list[dict], out_path: Path | None = None) -> Path | None:
    if not rows:
        logger.info("No AR detail rows to write (source not available)")
        return None
    out_path = out_path or (config.PROCESSED_DATA_DIR / "ar_aging_detail.csv")
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
    rows, final_totals = parse()
    write_processed(rows)
    print(f"{len(rows)} client/matter AR rows, total {sum(r['balance'] for r in rows):,.2f}")
    if final_totals:
        print(f"Report's own Final Totals balance: {final_totals.get('balance'):,.2f}")
    low_confidence = [r for r in rows if r["client_name_confidence"] != "ok"]
    if low_confidence:
        print(f"{len(low_confidence)} row(s) with unresolved client name: {[r['matter_name'] for r in low_confidence]}")
