"""
Parse the company AMEX "Transaction Details" exports (the card shared by
execs -- Alfred Fraijo Jr and Ramneek Saini in the sample) into one tidy
`card_transactions` table.

AMEX exports charges and credits/refunds as two separate files sharing the
same "Transaction Details" sheet layout (a "Prepared for" / "Account
Number" header block, then a real header row, then one row per
transaction) -- both are read here and combined; the source's own Amount
sign is kept as-is (positive = charge, negative = credit/refund), so
summing `amount` across both nets spend against refunds correctly.

The export is a single sheet covering every card member on the account
(distinguished by the "Card Member" column), not one file per person --
so a "for Alfred" / "for Ramneek" filter on the dashboard is just a filter
on that column, not a separate parse.

Output grain: one row per transaction line:
  txn_date, description, card_member, account_last4, amount,
  transaction_type ('charge'/'credit'), category, expense_type, vendor,
  merchant_city, merchant_state, merchant_country, location_bucket,
  location_low_confidence, shared_candidate, personal_review,
  personal_review_reason, reference, source_file
"""
from __future__ import annotations

import datetime
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

import config
from etl.common import find_all_files

logger = logging.getLogger("somos.etl.amex")

# AMEX's Description column is "merchant name" and "city/state" run
# together with no separator and truncated to ~20 characters (e.g.
# "AplPay GRUMPY BEAN  Seattle             WA"), so a clean vendor name
# needs the city/state stripped back off using the row's own City/State
# column (parsed separately, not truncated) plus a few known point-of-sale
# processor prefixes (Apple Pay, Square, Toast, Instacart's aggregator
# code, PayPal) stripped from the front. This is a best-effort cleanup for
# grouping/reporting, not a merchant-ID match -- two spellings of the same
# vendor (e.g. a hotel chain's city-specific property name) still count as
# different vendors below; treat "By Vendor" as a starting point for BD/
# overhead review, not an authoritative merchant roster.
_POS_PREFIX_RE = re.compile(r"^(AplPay|TST\*|IC\*|SQ\s*\*|PY\s*\*|BT\*|GTC/)\s*", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"\s+\d{3,}$")


def _normalize_vendor(description: str, city: str, state: str) -> str:
    v = description
    for token in filter(None, [city, state]):
        # Case-insensitive strip of the city/state substring wherever it
        # falls (usually the tail, since Description = name + city + state
        # concatenated) -- a plain .replace keeps this simple and safe
        # since these tokens rarely appear as part of a real merchant name.
        v = re.sub(re.escape(token), "", v, flags=re.IGNORECASE)
    v = _POS_PREFIX_RE.sub("", v)
    v = _TRAILING_NUMBER_RE.sub("", v)
    v = re.sub(r"\s{2,}", " ", v).strip(" -*")
    return v or description.strip()

_COLS = [
    "txn_date",
    "description",
    "card_member",
    "account_number",
    "amount",
    "extended_details",
    "statement_description",
    "address",
    "city_state",
    "zip_code",
    "country",
    "reference",
    "category",
]


def _find_header_row(ws) -> int | None:
    for r in range(1, min(ws.max_row, 20) + 1):
        if ws.cell(r, 1).value == "Date" and ws.cell(r, 2).value == "Description":
            return r
    return None


def _load_rows(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    header_row = _find_header_row(ws)
    if header_row is None:
        logger.warning("No 'Date'/'Description' header row found in %s -- skipping", path)
        return []
    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        raw = [ws.cell(r, c).value for c in range(1, len(_COLS) + 1)]
        if raw[0] is None or raw[4] is None:
            continue
        rows.append(dict(zip(_COLS, raw)))
    return rows


def _expense_type(category: str | None) -> str | None:
    if not category:
        return None
    return category.split(config.EXPENSE_TYPE_FROM_CATEGORY_SEPARATOR, 1)[0].strip()


def _location_bucket(city: str, state: str, country: str) -> str:
    haystack = " ".join(filter(None, [city, state, country])).lower()
    for bucket, keywords in config.EXPENSE_LOCATION_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return bucket
    return "Other"


def _personal_review_reason(category: str | None, expense_type: str | None, amount: float, is_charge: bool) -> str | None:
    if not is_charge:
        return None
    if category in config.PERSONAL_REVIEW_CATEGORIES:
        return f"Category flagged for review: {category}"
    if amount >= config.PERSONAL_REVIEW_LARGE_AMOUNT:
        return f"Large one-off charge (>= {config.PERSONAL_REVIEW_LARGE_AMOUNT:,.0f}) outside a typical business category"
    return None


def _parse_one(path: Path) -> list[dict]:
    out = []
    for row in _load_rows(path):
        txn_date = row["txn_date"]
        if isinstance(txn_date, datetime.datetime):
            txn_date = txn_date.date()
        elif isinstance(txn_date, str):
            try:
                txn_date = datetime.datetime.strptime(txn_date.strip(), "%m/%d/%Y").date()
            except ValueError:
                logger.warning("Unparseable date %r in %s -- dropping row", txn_date, path)
                continue

        city_state = (row.get("city_state") or "").strip()
        city, _, state = city_state.partition("\n")
        city, state = city.strip(), state.strip()
        country = (row.get("country") or "").strip()
        category = (row.get("category") or "").strip() or None
        expense_type = _expense_type(category)
        amount = float(row["amount"])
        is_charge = amount > 0

        # AMEX's own export mixes actual refunds (negative amount, a real
        # merchant category -- e.g. an airline credit) in with the
        # statement's own "AUTOPAY PAYMENT" lines (negative amount, no
        # category, paying down the balance rather than reversing a
        # purchase). Those payment lines aren't an expense or a refund of
        # one, so they're kept (for reconciliation) but tagged separately
        # and excluded from expense totals on the dashboard.
        if is_charge:
            transaction_type = "charge"
        elif category:
            transaction_type = "refund"
        else:
            transaction_type = "payment"

        description = (row.get("description") or "").strip()
        out.append(
            {
                "txn_date": txn_date,
                "description": description,
                "vendor": _normalize_vendor(description, city, state),
                "card_member": (row.get("card_member") or "").strip().title(),
                "account_last4": (row.get("account_number") or "").strip().lstrip("-") or None,
                "amount": round(amount, 2),
                "transaction_type": transaction_type,
                "category": category,
                "expense_type": expense_type,
                "merchant_city": city or None,
                "merchant_state": state or None,
                "merchant_country": country or None,
                "location_bucket": _location_bucket(city, state, country),
                "location_low_confidence": expense_type in config.EXPENSE_LOCATION_LOW_CONFIDENCE_TYPES,
                "shared_candidate": bool(
                    is_charge and expense_type in config.SHARED_EXPENSE_CATEGORIES and amount >= config.SHARED_EXPENSE_THRESHOLD
                ),
                "personal_review": _personal_review_reason(category, expense_type, amount, is_charge) is not None,
                "personal_review_reason": _personal_review_reason(category, expense_type, amount, is_charge),
                "reference": (row.get("reference") or "").strip() or None,
                "source_file": path.name,
            }
        )
    return out


def parse() -> list[dict]:
    rows: list[dict] = []
    for pattern_key, label in (("amex_debit", "charges"), ("amex_credit", "credits")):
        files = find_all_files(config.RAW_DATA_DIR, config.SOURCE_FILE_PATTERNS[pattern_key])
        if not files:
            logger.warning(
                "No AMEX %s export found in %s matching %r -- skipping.",
                label,
                config.RAW_DATA_DIR,
                config.SOURCE_FILE_PATTERNS[pattern_key],
            )
            continue
        for path in files:
            logger.info("Parsing AMEX %s export: %s", label, path)
            rows.extend(_parse_one(path))
    logger.info("Parsed %d card transactions", len(rows))
    return rows


def write_processed(rows: list[dict]) -> Path | None:
    if not rows:
        return None
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    import csv

    path = config.PROCESSED_DATA_DIR / "card_transactions.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), path)
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = parse()
    write_processed(rows)
    charges = sum(r["amount"] for r in rows if r["transaction_type"] == "charge")
    refunds = sum(r["amount"] for r in rows if r["transaction_type"] == "refund")
    payment_rows = [r["amount"] for r in rows if r["transaction_type"] == "payment"]
    print(
        f"{len(rows)} card transactions -- charges {charges:,.2f}, refunds {refunds:,.2f}, "
        f"net expenses {charges + refunds:,.2f} (excludes {len(payment_rows)} statement "
        f"autopay lines totaling {sum(payment_rows):,.2f})"
    )
