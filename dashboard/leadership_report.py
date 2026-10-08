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
from dashboard.charts.theme import fmt_num, fmt_pct_smart

_ROLE_LABELS = config.ROLE_LABELS
_STATUS_CLASS = {"Met": "good", "Eligible": "good", "Meets 90% test": "good", "On Track": "ok", "On pace": "ok",
                 "Watch": "warn", "Behind": "bad", "Not Met": "bad", "Not met": "bad", "Not on pace": "bad",
                 "Below 90%": "bad"}


def _fmt(v, kind: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if kind == "pct":
        return fmt_pct_smart(v)
    if kind == "hrs":
        return f"{fmt_num(v)}"
    s = html.escape(str(v))
    cls = _STATUS_CLASS.get(str(v))
    return f'<span class="pill {cls}">{s}</span>' if cls else s


def table_html(df: pd.DataFrame, cols: list[tuple[str, str]]) -> str:
    """Public wrapper for callers building extra_html sections."""
    return _table(df, cols)


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


def build_html(sc: pd.DataFrame, fy_start, fy_end, as_of, source_label: str, notes: list[str] | None = None,
               chart_fig=None, chart_title: str = "Credited hours vs. prorated Hours Expectation",
               extra_html: str = "", appendix_html: str = "", provisional: set | None = None,
               show_pro_bono: bool = True, departed_fig=None, insights: list[str] | None = None,
               client_html: str = "") -> str:
    """chart_fig replaces the default progress chart (e.g. the evaluation-
    window chart); extra_html is inserted between the chart and the
    scorecard (e.g. a table of timekeepers in the window). Rows whose
    Employment isn't "Current" are reported as a separate Departed group
    (departed_fig is its chart). insights are listed near the top;
    client_html is the client service hours section."""
    closed = as_of >= fy_end
    provisional = provisional or set()
    departed = sc.iloc[0:0]
    if "Employment" in sc:
        departed = sc[sc["Employment"] != "Current"]
        sc = sc[sc["Employment"] == "Current"]
    full = sc
    sc = sc[~sc["Timekeeper"].isin(provisional)]  # headline counts exclude provisional results
    n = len(full)
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
    if not departed.empty:
        kpis.append(("Departed (reported separately)", f"{len(departed)}"))
    if provisional:
        kpis.append(("Provisional †", f"{len(provisional)}"))
    elif has_total and show_pro_bono:
        kpis.append(("Pro bono hours", f"{sc['Pro Bono'].sum():,.0f}"))
    else:
        promo = int((sc.get("Promotion Lookback", pd.Series(dtype=str)) == "Meets 90% test").sum())
        kpis.append(("Meet 2-yr promotion test", f"{promo}"))
    kpi_html = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{html.escape(l)}</div></div>' for l, v in kpis)

    if chart_fig is None:
        expected_pct = full["Expected to Date"] / full["Expectation"].where(full["Expectation"] > 0) * 100
        chart_fig = target_progress(full, expected_pct)
    chart = chart_fig.to_html(full_html=False, include_plotlyjs=True, config={"displayModeBar": False})

    departed_html = ""
    if not departed.empty:
        d = departed.sort_values("% of Expectation", ascending=False).assign(
            **{"Last Day": departed["Employment"].str.replace("Left ", "", regex=False),
               "Group": departed["Role"].map(lambda r: _ROLE_LABELS.get(r, r).split(" — ")[0])})
        departed_html = (
            f"<h2>Departed timekeepers ({len(d)})</h2>"
            "<p class='method'>Left during the measuring period. Each is measured against requirements prorated "
            "to their last day (workdays employed ÷ workdays in the period), and none are counted in the headline "
            "figures above.</p>"
            + (departed_fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})
               if departed_fig is not None else "")
            + "<div class='scroll'>" + _table(d, [
                ("Timekeeper", "txt"), ("Group", "txt"), ("Last Day", "txt"), ("Annual Expectation", "hrs"),
                ("Expectation", "hrs"), ("Client", "hrs"), ("Pro Bono", "hrs"), ("Creditable NB (counted)", "hrs"),
                ("Credited Hours", "hrs"), ("% of Expectation", "pct"), ("Expectation Status", "txt"),
                ("Bonus Status", "txt")], drop_empty={"Pro Bono", "Creditable NB (counted)"}) + "</div>")
    insights_html = ("<h2>Key insights</h2><ul class='insights'>"
                     + "".join(f"<li>{html.escape(i)}</li>" for i in insights) + "</ul>") if insights else ""

    sections = []
    full = full.assign(Timekeeper=full["Timekeeper"].map(lambda t: f"{t} †" if t in provisional else t))
    for role in [*config.BILLABLE_HOUR_TARGETS, "Custom"]:
        sub = full[full["Role"] == role].sort_values("Timekeeper")
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
.good {{ background:#e3edf9; color:#184f95; }} .ok {{ background:#e8f1ee; color:#2f5f4f; }}
.warn {{ background:#f6f0e2; color:#6b5418; }} .bad {{ background:#f2ecea; color:#7a4038; }}
.insights {{ font-size: 14px; line-height: 1.55; padding-left: 20px; }} .insights li {{ margin-bottom: 6px; }}
.method {{ color: var(--ink2); font-size: 12px; line-height: 1.5; }}
@media print {{ body {{ max-width: none; }} .kpi {{ break-inside: avoid; }} }}
</style></head><body>
<h1>Measuring Period Hours — {fy_start:%b %-d, %Y} to {fy_end:%b %-d, %Y}</h1>
<div class="sub">Hours through {as_of:%b %-d, %Y}{' (period closed)' if closed else ''} · generated {datetime.date.today():%b %-d, %Y}</div>
<div class="kpis">{kpi_html}</div>
{insights_html}
<h2>{html.escape(chart_title)}</h2>
{chart}
{extra_html}
<h2>Scorecard{' — current timekeepers' if not departed.empty else ''}</h2>
<div class="scroll">{''.join(sections)}</div>
{departed_html}
{client_html}
{appendix_html}
<h2>Method</h2>
<p class="method">{html.escape(method)}</p>
{f'<h2>Data notes</h2><ul class="method">{notes_html}</ul>' if notes_html else ''}
</body></html>"""


def person_profile_html(row: pd.Series, figs: list, fy_start, fy_end, role_label: str,
                        notes: list[str] | None = None, extra_kpis: list | None = None,
                        extra_detail: list | None = None) -> str:
    """One-page, self-contained breakdown for a single timekeeper."""
    def kv(label, value):
        return f'<div class="kpi"><div class="v">{value}</div><div class="l">{html.escape(label)}</div></div>'

    def pct(v):
        return "—" if v is None or pd.isna(v) else f"{fmt_pct_smart(v)}"

    kpis = "".join([
        kv("Credited hours", f"{fmt_num(row['Credited Hours'])}"),
        kv("Prorated Hours Expectation", f"{fmt_num(row['Expectation'])}"),
        kv("% of Expectation", pct(row["% of Expectation"])),
        kv("Total activity", "—" if pd.isna(row.get("Total Hours")) else f"{fmt_num(row['Total Hours'])}"),
        kv("Bonus status", html.escape(str(row.get("Bonus Status") or "—"))),
        kv("2-yr average", pct(row.get("2-yr Avg %"))),
        *[kv(label, value) for label, value in (extra_kpis or [])],
    ])
    charts = ""
    for i, f in enumerate(figs):
        # Size each chart to its grid cell (fixed widths overflow and overlap).
        h = int(f.layout.height or 380)
        f.update_layout(autosize=True, width=None)
        charts += ('<div class="chart">' + f.to_html(
            full_html=False, include_plotlyjs=(i == 0), default_width="100%", default_height=f"{h}px",
            config={"displayModeBar": False, "responsive": True}) + "</div>")
    detail_rows = [
        ("Annual Hours Expectation", row.get("Annual Expectation")), ("Leave days (approved)", row.get("Leave Days")),
        ("Prorated Hours Expectation", row.get("Expectation")),
        ("Billable needed (with full creditable allowance)", row.get("Billable Needed")),
        ("Client hours", row.get("Client")),
        ("Firm's Own Account", row.get("FOA")), ("Pro bono", row.get("Pro Bono")),
        ("Creditable non-billable logged", row.get("Creditable NB (logged)")),
        ("Creditable counted (cap)", row.get("Creditable NB (counted)")),
        ("Creditable cap (prorated)", row.get("Creditable Cap")),
        ("Other non-billable", row.get("Other NB")), ("PTO / holiday", row.get("Time Off")),
        *(extra_detail or []),
        ("Bonus hours / threshold", f"{fmt_num(row.get('Bonus Hours', 0))} / {fmt_num(row.get('Bonus Threshold', float('nan')))}"),
        ("Prior period % of expectation", pct(row.get("Prior Period %"))),
        ("Promotion lookback", row.get("Promotion Lookback")),
    ]
    detail = "".join(
        f"<tr><td class='txt'>{html.escape(k)}</td><td>{v if isinstance(v, str) else ('—' if v is None or pd.isna(v) else f'{fmt_num(v)}')}</td></tr>"
        for k, v in detail_rows)
    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in (notes or []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hours Breakdown</title>
<style>
body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; color:#0b0b0b; background:#fcfcfb; margin:0 auto; max-width:1100px; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:28px 0 8px; }} .sub {{ color:#52514e; font-size:13px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:18px 0; }}
.kpi {{ border:1px solid #e1e0d9; border-radius:8px; padding:10px 12px; background:#fff; }}
.kpi .v {{ font-size:22px; font-weight:600; }} .kpi .l {{ color:#52514e; font-size:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(460px,1fr)); gap:12px; }}
.chart {{ background:#fff; border:1px solid #e1e0d9; border-radius:8px; padding:6px; min-width:0; overflow:hidden; }}
table {{ border-collapse:collapse; width:100%; max-width:560px; font-size:13px; background:#fff; }}
td {{ border-bottom:1px solid #e1e0d9; padding:6px 8px; text-align:right; }} td.txt {{ text-align:left; color:#52514e; }}
ul {{ color:#52514e; font-size:12px; }}
@media print {{ .chart {{ break-inside:avoid; }} }}
</style></head><body>
<h1>{html.escape(str(row['Timekeeper']))} — Hours Breakdown</h1>
<div class="sub">{html.escape(role_label)} · Measuring period {fy_start:%b %-d, %Y} – {fy_end:%b %-d, %Y} · generated {datetime.date.today():%b %-d, %Y}</div>
<div class="kpis">{kpis}</div>
<div class="grid">{charts}</div>
<h2>Detail</h2><table>{detail}</table>
{f'<h2>Notes</h2><ul>{notes_html}</ul>' if notes_html else ''}
<script>
// Charts can size themselves before the grid settles; re-measure once loaded.
window.addEventListener("load", function () {{
  document.querySelectorAll(".js-plotly-plot").forEach(function (p) {{ Plotly.Plots.resize(p); }});
}});
</script>
</body></html>"""
