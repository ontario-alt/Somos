"""
Shared parsing helpers for the Vantagepoint export parsers.

Vantagepoint's "detail" exports (AR aging, WIP, likely AP aging and
earnings too) are a collapsed tree -- Matter > Invoice > payment line,
or Company > Client > Matter > timekeeper transaction -- flattened to CSV
with no indentation and no explicit level markers. The only way to tell
which level a row belongs to is that header rows carry a subtotal that
is exactly the sum of the leaf rows beneath them, and leaf rows are the
only rows with certain columns populated (an invoice date, a timekeeper
name, ...). reconstruct_hierarchy() below walks the rows once, maintains
a stack of "open" header rows, and closes a header off the stack as soon
as its accumulated children match its stated subtotal. This is reused by
parse_ar.py and parse_wip.py, and should work unchanged for AP aging and
earnings exports that follow the same pattern.
"""
from __future__ import annotations

import glob
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger("somos.etl")

_MONEY_RE = re.compile(r"[^0-9.\-]")


def parse_money(raw: str | None) -> float | None:
    """'3667873.59 USD' / \"' -5880.00 USD\" / '' -> float or None."""
    if raw is None:
        return None
    s = raw.strip().strip("'").strip()
    if s == "":
        return None
    s = _MONEY_RE.sub("", s)
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_vp_date(raw: str | None):
    """Vantagepoint dates are M/D/YYYY. Returns a date or None."""
    if raw is None:
        return None
    s = raw.strip()
    if s == "":
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.warning("Unparseable date %r", raw)
    return None


def parse_bool_checkbox(raw: str | None) -> bool:
    """Vantagepoint checkbox columns export as 'Checked' / 'Unchecked'."""
    return (raw or "").strip().lower() == "checked"


def find_all_files(directory: Path, pattern: str | list[str]) -> list[Path]:
    """All files in `directory` matching one or more glob patterns
    (a source may show up as .csv or .xlsx depending on how it was
    exported), sorted oldest-to-newest by mtime, de-duplicated."""
    patterns = [pattern] if isinstance(pattern, str) else pattern
    seen: dict[Path, None] = {}
    for pat in patterns:
        for p in glob.glob(str(Path(directory) / pat)):
            seen[Path(p)] = None
    return sorted(seen.keys(), key=lambda p: p.stat().st_mtime)


def find_latest_file(directory: Path, pattern: str | list[str]) -> Path | None:
    """Newest file (by mtime) in `directory` matching glob `pattern`(s)."""
    matches = find_all_files(directory, pattern)
    return matches[-1] if matches else None


class _StackEntry:
    __slots__ = ("name", "totals", "accum", "extra")

    def __init__(self, name: str, totals: dict[str, float], extra: dict):
        self.name = name
        self.totals = totals
        self.accum = {f: 0.0 for f in totals}
        self.extra = extra

    def is_complete(self, tolerance: float) -> bool:
        return all(
            self.totals[f] is None or abs(self.accum[f] - self.totals[f]) <= tolerance
            for f in self.totals
        )


def reconstruct_hierarchy(
    rows: Iterable[dict],
    level_names: list[str],
    name_field: str,
    total_fields: list[str],
    leaf_predicate: Callable[[dict], bool],
    money_fields: Iterable[str] = (),
    tolerance: float = 0.02,
    header_extra: Callable[[dict], dict] | None = None,
    on_header_close: Callable[[int, list[str], str, dict], None] | None = None,
) -> list[dict]:
    """
    Flatten a Vantagepoint nested-tree export into one dict per leaf row,
    annotated with its ancestor names at each level.

    rows: dict rows in file order (header/total row already excluded).
    level_names: ancestor level names outermost-first, e.g.
        ["company", "client", "matter"] for the WIP export.
    name_field: source column holding the row's label whether it's a
        header or a leaf (Vantagepoint reuses one column for both).
    total_fields: source columns that hold a running subtotal on header
        rows and the leaf's own value on leaf rows -- used to detect
        when a header's children are fully accounted for.
    leaf_predicate: returns True if a row is a leaf (transaction/line),
        False if it's a header (grouping) row.
    money_fields: subset of total_fields (or others) to run through
        parse_money before comparing/accumulating.
    header_extra: optional fn(row) -> dict of extra fields to stash on
        a header's stack entry (unused today, hook for future sources).
    on_header_close: optional fn(depth, ancestor_names, closed_name, totals)
        called every time a header row's children are fully accounted
        for and it's popped off the stack -- lets a caller capture
        rollups at any level (e.g. matter-level WIP subtotals) without
        re-walking the tree a second time.
    """
    money_fields = set(money_fields)
    stack: list[_StackEntry] = []
    output: list[dict] = []

    def _val(row: dict, field: str) -> float:
        raw = row.get(field)
        return parse_money(raw) if field in money_fields else float(raw or 0)

    for row in rows:
        if leaf_predicate(row):
            rec = dict(row)
            for i, lvl in enumerate(level_names):
                rec[lvl] = stack[i].name if i < len(stack) else None
            output.append(rec)
            for entry in stack:
                for f in total_fields:
                    entry.accum[f] += _val(row, f)
            continue

        # Header row: close out any already-satisfied levels on top of
        # the stack before pushing this one, so it attaches as a child
        # of the correct still-open ancestor.
        while stack and stack[-1].is_complete(tolerance):
            closed = stack.pop()
            if on_header_close:
                ancestors = [e.name for e in stack]
                on_header_close(len(stack), ancestors, closed.name, closed.totals)

        if len(stack) >= len(level_names):
            # Shouldn't happen if the export is well-formed; guard
            # against runaway growth rather than crashing the whole run.
            logger.warning(
                "Hierarchy deeper than expected levels=%s at row %r; forcing pop",
                level_names,
                row,
            )
            closed = stack.pop()
            if on_header_close:
                ancestors = [e.name for e in stack]
                on_header_close(len(stack), ancestors, closed.name, closed.totals)

        totals = {f: _val(row, f) for f in total_fields}
        extra = header_extra(row) if header_extra else {}
        stack.append(_StackEntry(row.get(name_field, "").strip(), totals, extra))

    # Flush any headers still open at EOF (the last matter/invoice in the
    # file has no following header row to trigger its own close).
    while stack:
        closed = stack.pop()
        if on_header_close:
            ancestors = [e.name for e in stack]
            on_header_close(len(stack), ancestors, closed.name, closed.totals)

    return output
