"""
Self-contained HTML snapshot of the measuring-period hours scorecard,
for leadership. One file -- charts embedded (plotly.js inlined, so it
opens offline), no app or database needed -- that can be emailed,
posted to SharePoint/Teams, or printed to PDF from the browser.

Built from the same scorecard DataFrame the page shows, so the numbers
always match the dashboard at the moment it was downloaded.
"""
from __future__ import annotations

import datetime
import html

import pandas as pd

import config
from dashboard.charts.target_progress import target_progress

_ROLE_LABELS = {"Attorney": "Associates (attorneys)", "Planner": "Planners & Project Specialists", "Custom": "Individual terms"}
_STATUS_CLASS = {"Met": "good", "Eligible": "good", "Meets 90% test": "good", "On Track": "ok", "On pace": "ok",
                 "Watch": "warn", "Behind": "bad", "Not Met": "bad", "Not met": "bad", "Not on pace": "bad",
                 "Below 90%": "bad"}


def _fmt(v, kind: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if kind == "pct":
        return f"{v:.0f}%"
    if kind == "hrs":
        return f"{v:,.1f}"
    s = html.escape(str(v))
    cls = _STATUS_CLASS.get(str(v))
    return f'<span class="pill {cls}">{s}</span>' if cls else s


def _table(df: pd.DataFrame, cols: list[tuple[str, str]], drop_empty: set[str] = frozenset()) -> str:
    # Columns with nothing to say for this period (all zero / blank, e.g.
    # FOA and pro bono in billable-only history) are left out.
    cols = [(c, k) for c, k in cols if not (c in drop_empty and (df[c].isna() | (df[c] == 0) | (df[c] == "")).all())]
    head = "".join(f"<th>{html.escape(c)}</th>" for c, _ in cols)
    rows = "".join(
        "<tr>" + "".join(f'<td class="{k}">{_fmt(r[c], k)}</td>' for c, k in cols) + "</tr>"
        for _, r in df.iterrows()
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def build_html(sc: pd.DataFrame, fy_start, fy_end, as_of, source_label: str, notes: list[str] | None = None) -> str:
    closed = as_of >= fy_end
    n = len(sc)
    has_total = bool(sc["Has Breakdown"].any()) if "Has Breakdown" in sc else True
    met = int((sc["Status"] == "Met").sum())
    bonus = int((sc["Bonus Status"] == "Eligible").sum())
    short = int(sc["Status"].isin(["Not Met", "Behind", "Watch"]).sum())
    met_label = ("Met both requirements" if has_total else "Met Hours Expectation") if closed else "Met / on track"
    kpis = [
        ("Timekeepers", f"{n}"),
        (met_label, f"{met if closed else met + int((sc['Status'] == 'On Track').sum())}"),
        ("Short" if closed else "Watch / behind", f"{short}"),
        ("Bonus eligible", f"{bonus}"),
    ]
    if has_total:
        kpis.append(("Pro bono hours", f"{sc['Pro Bono'].sum():,.0f}"))
    else:
        promo = int((sc.get("Promotion Lookback", pd.Series(dtype=str)) == "Meets 90% test").sum())
        kpis.append(("Meet 2-yr promotion test", f"{promo}"))
    kpi_html = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{html.escape(l)}</div></div>' for l, v in kpis)

    expected_pct = sc["Expected to Date"] / sc["Expectation"].where(sc["Expectation"] > 0) * 100
    chart = target_progress(sc, expected_pct).to_html(full_html=False, include_plotlyjs=True, config={"displayModeBar": False})

    sections = []
    for role in [*config.BILLABLE_HOUR_TARGETS, "Custom"]:
        sub = sc[sc["Role"] == role].sort_values("Timekeeper")
        if sub.empty:
            continue
        sections.append(f"<h3>{_ROLE_LABELS.get(role, role)}</h3>")
        sections.append(_table(sub, [
            ("Timekeeper", "txt"), ("Expectation", "hrs"), ("Client", "hrs"), ("FOA", "hrs"), ("Pro Bono", "hrs"),
            ("Creditable NB (counted)", "hrs"), ("Credited Hours", "hrs"), ("% of Expectation", "pct"),
            ("Projected", "hrs"), ("Expectation Status", "txt"), ("Total Hours", "hrs"), ("Total Expectation", "hrs"),
            ("Total Status", "txt"), ("Bonus Hours", "hrs"), ("Bonus Threshold", "hrs"), ("Bonus Status", "txt"),
            ("2-yr Avg %", "pct"), ("Promotion Lookback", "txt"),
        ], drop_empty={"FOA", "Pro Bono", "Creditable NB (counted)", "Total Hours", "Total Expectation",
                       "Total Status", "2-yr Avg %"}))

    reqs = "; ".join(
        f"{_ROLE_LABELS[k]}: {v:,} expectation / {config.TOTAL_HOUR_TARGETS.get(k, 0):,} total activity / "
        f"{config.BONUS_HOUR_THRESHOLDS.get(k, 0):,} bonus threshold"
        for k, v in config.BILLABLE_HOUR_TARGETS.items()
    )
    method = (
        f"Per the Promotion and Bonus Policy. {reqs}. Credited hours = client + Firm's Own Account + pro bono + "
        f"creditable non-billable (capped at {config.CREDITABLE_NB_CAP}). Bonus hours exclude pro bono; once the "
        f"threshold is met pro bono is added back. Requirements and the creditable cap are prorated for approved "
        f"leave and partial-year employment. Promotion lookback = average % of Hours Expectation over this and the "
        f"prior measuring period ({config.PROMOTION_LOOKBACK_PCT}% test). Bonus eligibility only — bonuses remain "
        f"discretionary. Source: {source_label}."
    )
    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in (notes or []))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Measuring Period Hours</title>
<style>
:root {{ --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --line:#e1e0d9; --bg:#fcfcfb; }}
body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; color: var(--ink); background: var(--bg);
        margin: 0 auto; max-width: 1200px; padding: 24px 16px 48px; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }} h2 {{ font-size: 18px; margin: 32px 0 8px; }} h3 {{ font-size: 15px; margin: 20px 0 6px; }}
.sub {{ color: var(--ink2); font-size: 13px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
.kpi {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fff; }}
.kpi .v {{ font-size: 26px; font-weight: 600; }} .kpi .l {{ color: var(--ink2); font-size: 12px; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; background: #fff; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: right; white-space: nowrap; }}
th {{ color: var(--ink2); font-weight: 600; position: sticky; top: 0; background: #f4f3ef; }}
td.txt, th:first-child {{ text-align: left; }}
.pill {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
.good {{ background:#dcf3dc; color:#0b6b0b; }} .ok {{ background:#d9f2ea; color:#0e6f4f; }}
.warn {{ background:#fdf0cf; color:#7a5600; }} .bad {{ background:#f9dcdc; color:#9b2222; }}
.method {{ color: var(--ink2); font-size: 12px; line-height: 1.5; }}
@media print {{ body {{ max-width: none; }} .kpi {{ break-inside: avoid; }} }}
</style></head><body>
<h1>Measuring Period Hours — {fy_start:%b %-d, %Y} to {fy_end:%b %-d, %Y}</h1>
<div class="sub">Hours through {as_of:%b %-d, %Y}{' (period closed)' if closed else ''} · generated {datetime.date.today():%b %-d, %Y}</div>
<div class="kpis">{kpi_html}</div>
<h2>Credited hours vs. prorated Hours Expectation</h2>
{chart}
<h2>Scorecard</h2>
<div class="scroll">{''.join(sections)}</div>
<h2>Method</h2>
<p class="method">{html.escape(method)}</p>
{f'<h2>Data notes</h2><ul class="method">{notes_html}</ul>' if notes_html else ''}
</body></html>"""
