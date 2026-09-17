"""
Executive Expenses -- company AMEX card shared by execs (see
etl/parse_amex.py for the source: AMEX's own charge/refund exports,
combined into one `card_transactions` table).

Filters (person, expense type, location, shared-only, vendor search) all
operate on the same underlying query, so every section below -- summary
KPIs, by-person, by-type, by-location, the location x type allocation
matrix, by-vendor, and the two review lists -- reflects the current filter
selection, not just the detail table at the bottom. The one exception is
Recurring Charges / Overhead Review, which deliberately looks across every
executive and location regardless of the filter bar, since the point is
to catch every vendor's full monthly pattern, not just what's currently
filtered in.

Two review lists are heuristics, not determinations, and are captioned as
such everywhere they appear:
  - Shared/group candidates: a Restaurant or Entertainment charge at or
    above config.SHARED_EXPENSE_THRESHOLD -- likely covers more than the
    cardholder alone, but the export has no attendee count to confirm it.
  - Potential personal expenses: config.PERSONAL_REVIEW_CATEGORIES or an
    unusually large one-off charge (config.PERSONAL_REVIEW_LARGE_AMOUNT).
    Each flagged row shows the specific rule that triggered it so it can
    be checked against the underlying receipt, not just trusted.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.placeholder import missing_source
from dashboard.charts.ranked_bar import ranked_bar
from dashboard.charts.theme import fmt_currency, fmt_pct
from dashboard.data import query, table_exists

_MONEY_COLS_HELP = "Charges are positive; refunds are negative. Statement autopay payment lines are excluded entirely -- they pay down the balance, they aren't an expense."


def render():
    st.title("Executive Expenses")
    st.caption("Company AMEX card, shared by execs -- charges and refunds combined, statement autopay lines excluded.")

    if not table_exists("card_transactions"):
        missing_source(
            "the AMEX charge/credit exports (config.SOURCE_FILE_PATTERNS['amex_debit'] / "
            "['amex_credit']) -- see etl/parse_amex.py"
        )
        return

    people = query(
        "SELECT DISTINCT card_member FROM card_transactions WHERE transaction_type != 'payment' ORDER BY 1"
    )["card_member"].tolist()
    types = query(
        "SELECT DISTINCT COALESCE(expense_type, 'Unknown') AS expense_type FROM card_transactions "
        "WHERE transaction_type != 'payment' ORDER BY 1"
    )["expense_type"].tolist()
    locations = query(
        "SELECT DISTINCT location_bucket FROM card_transactions WHERE transaction_type != 'payment' ORDER BY 1"
    )["location_bucket"].tolist()

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.4])
        sel_people = c1.multiselect("Executive", people, default=people)
        sel_types = c2.multiselect("Expense type", types, default=types)
        sel_locations = c3.multiselect("Location", locations, default=locations)
        allocation_filter = c4.selectbox(
            "Allocation",
            ["All", "Shared/group only", "Individual only"],
            help="Shared/group = flagged as a likely multi-person meal/entertainment charge (see caption below). Not a real cost-split -- the export has no attendee data.",
        )
        vendor_search = st.text_input(
            "Vendor / description contains",
            placeholder="e.g. Uber, Southwest, Amazon, Four Seasons...",
            help="Matches against the cleaned-up vendor name and the raw transaction description (see 'By Vendor' below for the full vendor-cleanup caveat).",
        )

    if not sel_people or not sel_types or not sel_locations:
        st.info("Select at least one executive, expense type, and location to see results.")
        return

    where = ["transaction_type != 'payment'", "card_member IN ?", "COALESCE(expense_type, 'Unknown') IN ?", "location_bucket IN ?"]
    params = [sel_people, sel_types, sel_locations]
    if allocation_filter == "Shared/group only":
        where.append("shared_candidate")
    elif allocation_filter == "Individual only":
        where.append("NOT shared_candidate")
    if vendor_search.strip():
        where.append("(vendor ILIKE ? OR description ILIKE ?)")
        needle = f"%{vendor_search.strip()}%"
        params += [needle, needle]

    df = query(
        f"""
        SELECT txn_date, description, vendor, card_member, amount, transaction_type, category,
               COALESCE(expense_type, 'Unknown') AS expense_type, merchant_city, merchant_state,
               merchant_country, location_bucket, location_low_confidence, shared_candidate,
               personal_review, personal_review_reason, reference
        FROM card_transactions
        WHERE {' AND '.join(where)}
        ORDER BY txn_date DESC
        """,
        params,
    )

    payments_excluded = query(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM card_transactions WHERE transaction_type = 'payment'"
    ).iloc[0]

    _section_summary(df, payments_excluded)
    st.divider()
    _section_by_person(df)
    st.divider()
    _section_by_type(df)
    st.divider()
    _section_by_location(df)
    st.divider()
    _section_allocation_matrix(df)
    st.divider()
    _section_by_vendor(df)
    st.divider()
    _section_recurring_overhead()
    st.divider()
    _section_shared(df)
    st.divider()
    _section_personal_review(df)
    st.divider()
    _section_detail(df)


def _section_summary(df: pd.DataFrame, payments_excluded):
    st.subheader("Summary")
    charges = df.loc[df["transaction_type"] == "charge", "amount"].sum()
    refunds = df.loc[df["transaction_type"] == "refund", "amount"].sum()
    net = charges + refunds
    shared_total = df.loc[df["shared_candidate"], "amount"].sum()
    review_total = df.loc[df["personal_review"], "amount"].sum()

    kpi_row(
        [
            {"label": "Gross Charges", "value": fmt_currency(charges, short=True), "help": fmt_currency(charges)},
            {"label": "Refunds", "value": fmt_currency(refunds, short=True), "help": fmt_currency(refunds)},
            {"label": "Net Expenses", "value": fmt_currency(net, short=True), "help": fmt_currency(net)},
            {"label": "Transactions", "value": f"{len(df):,}"},
            {"label": "Flagged Shared/Group $", "value": fmt_currency(shared_total, short=True), "help": fmt_currency(shared_total)},
            {"label": "Flagged for Personal Review $", "value": fmt_currency(review_total, short=True), "help": fmt_currency(review_total)},
        ]
    )
    st.caption(
        _MONEY_COLS_HELP
        + f" {int(payments_excluded['n'])} autopay payment line(s) totaling {fmt_currency(payments_excluded['total'])} "
        "excluded from every figure on this page (visible in the raw export, not in card_transactions' expense totals)."
    )


def _section_by_person(df: pd.DataFrame):
    st.subheader("By Executive")
    if df.empty:
        st.info("No transactions match the current filters.")
        return
    by_person = (
        df[df["transaction_type"].isin(["charge", "refund"])]
        .groupby("card_member")
        .agg(
            charges=("amount", lambda s: s[s > 0].sum()),
            refunds=("amount", lambda s: s[s < 0].sum()),
            net=("amount", "sum"),
            transactions=("amount", "count"),
            flagged_shared=("shared_candidate", "sum"),
            flagged_review=("personal_review", "sum"),
        )
        .reset_index()
        .sort_values("net", ascending=False)
    )
    st.dataframe(
        by_person.rename(
            columns={
                "card_member": "Executive", "charges": "Charges", "refunds": "Refunds", "net": "Net",
                "transactions": "Transactions", "flagged_shared": "Shared/Group Flags", "flagged_review": "Personal Review Flags",
            }
        ),
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in ["Charges", "Refunds", "Net"]},
    )


def _section_by_type(df: pd.DataFrame):
    st.subheader("By Expense Type")
    if df.empty:
        st.info("No transactions match the current filters.")
        return
    by_type = (
        df[df["transaction_type"].isin(["charge", "refund"])]
        .groupby("expense_type")
        .agg(net=("amount", "sum"), transactions=("amount", "count"))
        .reset_index()
    )
    total = by_type["net"].sum()
    by_type["pct_of_total"] = by_type["net"] / total * 100 if total else 0
    by_type = by_type.sort_values("net", ascending=False)

    col1, col2 = st.columns([1.3, 1])
    with col1:
        st.plotly_chart(
            ranked_bar(by_type, label_col="expense_type", value_col="net", top_n=len(by_type), title="Net Spend by Expense Type"),
            use_container_width=True,
        )
    with col2:
        st.dataframe(
            by_type.rename(columns={"expense_type": "Type", "net": "Net", "transactions": "Transactions", "pct_of_total": "% of Total"}),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Net": st.column_config.NumberColumn(format="$%,.0f"),
                "% of Total": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )


def _section_by_location(df: pd.DataFrame):
    st.subheader("By Location (Project / Office Allocation)")
    if df.empty:
        st.info("No transactions match the current filters.")
        return
    by_loc = (
        df[df["transaction_type"].isin(["charge", "refund"])]
        .groupby("location_bucket")
        .agg(
            net=("amount", "sum"),
            transactions=("amount", "count"),
            low_confidence_txns=("location_low_confidence", "sum"),
        )
        .reindex(list(config.EXPENSE_LOCATION_KEYWORDS.keys()) + ["Other"])
        .dropna(how="all")
        .fillna(0)
        .reset_index()
        .rename(columns={"index": "location_bucket"})
        .sort_values("net", ascending=False)
    )
    st.dataframe(
        by_loc.rename(
            columns={
                "location_bucket": "Location", "net": "Net", "transactions": "Transactions",
                "low_confidence_txns": "Low-Confidence Txns",
            }
        ),
        use_container_width=True,
        hide_index=True,
        column_config={"Net": st.column_config.NumberColumn(format="$%,.0f")},
    )
    st.caption(
        "Location is the merchant's own city/state/country from the export, matched against "
        f"{', '.join(config.EXPENSE_LOCATION_KEYWORDS.keys())} (config.EXPENSE_LOCATION_KEYWORDS); "
        "\"Other\" covers every merchant city that matched none of them. This is real merchant "
        "location, not a project code -- the export carries no matter/project field, so it "
        "cannot be tied to a specific engagement, only to a place. \"Low-Confidence Txns\" counts "
        "rows in a category (Merchandise & Supplies, Business Services, Communications -- "
        "config.EXPENSE_LOCATION_LOW_CONFIDENCE_TYPES) where the merchant city is more likely "
        "that merchant's own billing address/HQ (e.g. Amazon, AWS, Adobe show Seattle regardless "
        "of where the card was actually used) than a real trip -- worth a second look before "
        "treating a location total as travel to that office."
    )


def _section_allocation_matrix(df: pd.DataFrame):
    st.subheader("Cost Allocation Matrix -- Location x Expense Type")
    charges = df[df["transaction_type"].isin(["charge", "refund"])]
    if charges.empty:
        st.info("No transactions match the current filters.")
        return
    pivot = charges.pivot_table(index="location_bucket", columns="expense_type", values="amount", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(list(config.EXPENSE_LOCATION_KEYWORDS.keys()) + ["Other"]).dropna(how="all").fillna(0)
    pivot["Total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("Total", ascending=False)
    pivot.loc["TOTAL -- ALL LOCATIONS"] = pivot.sum(numeric_only=True)
    st.dataframe(
        pivot.reset_index().rename(columns={"location_bucket": "Location"}),
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in pivot.columns},
    )
    st.caption(
        "One cell per (location, expense type) combination -- the starting point for splitting "
        "shared-exec card spend across office/project cost centers. Same location caveat as "
        "above: a cell is real merchant-city spend, not a confirmed project charge, so treat this "
        "as an allocation proposal to sign off on, not a finished allocation."
    )


def _section_by_vendor(df: pd.DataFrame):
    st.subheader("By Vendor")
    charges = df[df["transaction_type"].isin(["charge", "refund"])]
    if charges.empty:
        st.info("No transactions match the current filters.")
        return
    by_vendor = (
        charges.groupby("vendor")
        .agg(
            net=("amount", "sum"),
            transactions=("amount", "count"),
            first_seen=("txn_date", "min"),
            last_seen=("txn_date", "max"),
            expense_type=("expense_type", lambda s: " / ".join(sorted(set(s)))),
        )
        .reset_index()
        .sort_values("net", ascending=False)
    )
    by_vendor["avg"] = by_vendor["net"] / by_vendor["transactions"]

    col1, col2 = st.columns([1.3, 1])
    with col1:
        st.plotly_chart(
            ranked_bar(by_vendor, label_col="vendor", value_col="net", top_n=15, title="Top 15 Vendors by Net Spend"),
            use_container_width=True,
        )
    with col2:
        st.dataframe(
            by_vendor.head(15).rename(
                columns={
                    "vendor": "Vendor", "net": "Net", "transactions": "Transactions", "avg": "Avg/Txn",
                    "expense_type": "Type(s)", "first_seen": "First", "last_seen": "Last",
                }
            )[["Vendor", "Net", "Transactions", "Avg/Txn", "Type(s)"]],
            use_container_width=True,
            hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in ["Net", "Avg/Txn"]},
        )
    with st.expander(f"All {len(by_vendor)} vendors in current filters"):
        st.dataframe(
            by_vendor.rename(
                columns={
                    "vendor": "Vendor", "net": "Net", "transactions": "Transactions", "avg": "Avg/Txn",
                    "expense_type": "Type(s)", "first_seen": "First", "last_seen": "Last",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in ["Net", "Avg/Txn"]},
        )
    st.caption(
        "Vendor is cleaned up from the export's own Description column (POS-processor prefixes "
        "like \"AplPay\"/\"TST*\" and the merchant city/state stripped off -- see "
        "etl/parse_amex.py:_normalize_vendor) -- a best-effort grouping for BD/overhead review, "
        "not a merchant-ID match. AMEX truncates Description to ~20 characters, so some vendor "
        "names below are cut short (e.g. a hotel property name) and a few spellings of the same "
        "vendor may still show as separate rows; use the vendor search box above to pull every "
        "transaction for one and confirm before treating a total as final."
    )


def _section_recurring_overhead():
    st.subheader("Recurring Charges -- Overhead Review")
    st.caption("Independent of the filters above -- this looks across every executive/location to find the full pattern for each vendor.")
    df = query(
        """
        SELECT vendor, card_member,
               COUNT(DISTINCT date_trunc('month', txn_date)) AS months_active,
               SUM(amount) AS net, COUNT(*) AS transactions,
               MIN(txn_date) AS first_seen, MAX(txn_date) AS last_seen
        FROM card_transactions
        WHERE transaction_type = 'charge'
        GROUP BY vendor, card_member
        HAVING COUNT(DISTINCT date_trunc('month', txn_date)) >= ?
        ORDER BY net DESC
        """,
        [config.RECURRING_VENDOR_MIN_MONTHS],
    )
    if df.empty:
        st.info(f"No vendor recurs in {config.RECURRING_VENDOR_MIN_MONTHS}+ distinct months yet.")
        return
    df["avg_per_month"] = df["net"] / df["months_active"]
    st.dataframe(
        df.rename(
            columns={
                "vendor": "Vendor", "card_member": "Executive", "months_active": "Months Active",
                "net": "Total Spend", "transactions": "Transactions", "avg_per_month": "Avg/Month",
                "first_seen": "First", "last_seen": "Last",
            }
        )[["Vendor", "Executive", "Months Active", "Total Spend", "Avg/Month", "Transactions", "First", "Last"]],
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in ["Total Spend", "Avg/Month"]},
    )
    st.caption(
        f"A vendor charging the same person in {config.RECURRING_VENDOR_MIN_MONTHS}+ distinct "
        "calendar months (config.RECURRING_VENDOR_MIN_MONTHS) -- typically a subscription/SaaS "
        "seat, a recurring service, or a habitual transit/parking spot -- rather than one-off BD "
        "or travel spend. This is the list to run a use-it-or-cut-it review against for overhead "
        "reduction; it isn't itself a recommendation to cancel anything."
    )


def _section_shared(df: pd.DataFrame):
    st.subheader("Shared / Group Expense Candidates")
    shared = df[df["shared_candidate"]].sort_values("amount", ascending=False)
    if shared.empty:
        st.info("No transactions in the current filters were flagged as likely shared/group expenses.")
    else:
        st.dataframe(
            shared[["txn_date", "card_member", "description", "category", "location_bucket", "amount"]].rename(
                columns={
                    "txn_date": "Date", "card_member": "Executive", "description": "Description",
                    "category": "Category", "location_bucket": "Location", "amount": "Amount",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="$%,.2f")},
        )
    st.caption(
        f"Flags a {'/'.join(config.SHARED_EXPENSE_CATEGORIES)} charge at or above "
        f"{fmt_currency(config.SHARED_EXPENSE_THRESHOLD)} (config.SHARED_EXPENSE_THRESHOLD) as "
        "likely covering more than one person. It's a size heuristic, not confirmed attendance -- "
        "the export has no guest count or matter/project reference to allocate it against, so "
        "splitting it between clients, offices, or individuals needs the underlying receipt."
    )


def _section_personal_review(df: pd.DataFrame):
    st.subheader("Potential Personal Expenses -- For Review")
    review = df[df["personal_review"]].sort_values("amount", ascending=False)
    if review.empty:
        st.info("No transactions in the current filters were flagged for personal-expense review.")
    else:
        st.dataframe(
            review[["txn_date", "card_member", "description", "category", "amount", "personal_review_reason"]].rename(
                columns={
                    "txn_date": "Date", "card_member": "Executive", "description": "Description",
                    "category": "Category", "amount": "Amount", "personal_review_reason": "Flagged Because",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="$%,.2f")},
        )
        st.caption(
            f"{len(review)} transaction(s) totaling {fmt_currency(review['amount'].sum())} flagged."
        )
    st.caption(
        "Flags a transaction in a personal-leaning category (Groceries, Department Stores, "
        "Florists, Mail Order, Theatrical/General Events, Charities -- "
        "config.PERSONAL_REVIEW_CATEGORIES) or any charge over "
        f"{fmt_currency(config.PERSONAL_REVIEW_LARGE_AMOUNT)} outside a typical business category "
        "(config.PERSONAL_REVIEW_LARGE_AMOUNT). This is a starting point for the firm to review "
        "against actual receipts/business purpose, not an accusation or a determination -- "
        "several likely have a legitimate business justification (e.g. a client gift, a "
        "sponsorship, or a bar-association due). Tune the category list and threshold in "
        "config.py as the firm's own policy becomes clearer; every flag above shows the specific "
        "rule that triggered it."
    )


def _section_detail(df: pd.DataFrame):
    with st.expander(f"Transaction detail ({len(df)} transactions matching current filters)"):
        st.dataframe(
            df[
                ["txn_date", "card_member", "vendor", "description", "expense_type", "category", "amount", "transaction_type",
                 "merchant_city", "merchant_state", "location_bucket", "shared_candidate", "personal_review", "reference"]
            ].rename(
                columns={
                    "txn_date": "Date", "card_member": "Executive", "vendor": "Vendor", "description": "Description",
                    "expense_type": "Type", "category": "Category", "amount": "Amount",
                    "transaction_type": "Txn Type", "merchant_city": "City", "merchant_state": "State",
                    "location_bucket": "Location", "shared_candidate": "Shared?", "personal_review": "Review?",
                    "reference": "Reference",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="$%,.2f")},
        )
