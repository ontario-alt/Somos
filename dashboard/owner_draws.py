"""
Owner draws (reference/owner_draws.csv) as a cost: owners are costed at
what they actually draw, not their Vantagepoint cost rate. Plain pandas,
no Streamlit, shared by the Monthly, Measuring Period and Budget pages.
"""
from __future__ import annotations

import pandas as pd

DAYS_PER_MONTH = 365.0 / 12.0
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "esq"}


def base_key(key: str | None) -> str | None:
    """A name_key without suffixes, so "Alfred Fraijo" in owner_draws.csv
    matches "Alfred Fraijo Jr." in Vantagepoint."""
    if not key:
        return None
    return " ".join(t for t in str(key).split() if t not in _SUFFIXES) or None


def owner_keys(draws: pd.DataFrame | None) -> set[str]:
    """Base keys of every owner in the draw list (compare with base_key())."""
    if draws is None or draws.empty:
        return set()
    return {base_key(k) for k in draws["name_key"].dropna()}


def _rows(draws: pd.DataFrame | None, key: str | None) -> pd.DataFrame:
    if draws is None or draws.empty or not key:
        return pd.DataFrame()
    return draws[draws["name_key"].map(base_key) == base_key(key)]


def draw_cost(draws: pd.DataFrame | None, key: str | None, start, end) -> float | None:
    """An owner's draws over [start, end]: each draw row's monthly amount x
    the months it overlaps (calendar days / (365/12), the same proration as
    salaried cost). None if `key` isn't an owner."""
    rows = _rows(draws, key)
    if rows.empty:
        return None
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    total = 0.0
    for r in rows.itertuples(index=False):
        rs = pd.Timestamp(r.start_date) if pd.notna(r.start_date) else s
        re_ = pd.Timestamp(r.end_date) if pd.notna(r.end_date) else e
        lo, hi = max(s, rs), min(e, re_)
        if hi >= lo:
            total += float(r.monthly_draw) * ((hi - lo).days + 1) / DAYS_PER_MONTH
    return total


def monthly_draw_on(draws: pd.DataFrame | None, key: str | None, on) -> float | None:
    """The monthly draw in effect on a date (None if not an owner, 0 if the
    owner has no draw row covering that date)."""
    rows = _rows(draws, key)
    if rows.empty:
        return None
    d = pd.Timestamp(on)
    for r in rows.itertuples(index=False):
        if (pd.isna(r.start_date) or pd.Timestamp(r.start_date) <= d) and (pd.isna(r.end_date) or d <= pd.Timestamp(r.end_date)):
            return float(r.monthly_draw)
    return 0.0
