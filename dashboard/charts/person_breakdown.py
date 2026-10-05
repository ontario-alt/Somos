"""Charts for one timekeeper's hours breakdown (Period Review page and the
per-person HTML profile)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, INK_MUTED, INK_PRIMARY, STATUS, apply_layout, fmt_num, fmt_pct_smart

# Fixed color per hour category so every chart reads the same way.
CATEGORY_COLORS = {
    "Client": CATEGORICAL[0],
    "Firm's Own Account": CATEGORICAL[6],
    "Pro Bono": CATEGORICAL[2],
    "Creditable (counted)": CATEGORICAL[3],
    "Creditable (over cap)": "#f3d48a",
    "Other Non-billable": "#b9b7ae",
    "PTO / Holiday": "#e1e0d9",
}


def category_hours(row: pd.Series) -> pd.Series:
    """Hours by category from a scorecard row (hours_credit.build_scorecard)."""
    return pd.Series({
        "Client": row.get("Client", 0.0),
        "Firm's Own Account": row.get("FOA", 0.0),
        "Pro Bono": row.get("Pro Bono", 0.0),
        "Creditable (counted)": row.get("Creditable NB (counted)", 0.0),
        "Creditable (over cap)": row.get("Creditable NB (over cap)", 0.0),
        "Other Non-billable": row.get("Other NB", 0.0),
        "PTO / Holiday": row.get("Time Off", 0.0),
    }).fillna(0.0)


def hours_donut(row: pd.Series, include_time_off: bool = True) -> go.Figure:
    """Where the person's hours went, by policy category."""
    cats = category_hours(row)
    if not include_time_off:
        cats = cats.drop("PTO / Holiday")
    cats = cats[cats > 0.05]
    total = cats.sum()
    fig = go.Figure(go.Pie(
        labels=cats.index, values=cats.values, hole=0.55, sort=False, direction="clockwise",
        marker=dict(colors=[CATEGORY_COLORS[c] for c in cats.index], line=dict(color="#ffffff", width=2)),
        textinfo="percent", textposition="inside", insidetextorientation="horizontal",
        hovertemplate="%{label}: %{value:,.1f} hrs (%{percent})<extra></extra>",
    ))
    fig.add_annotation(text=f"<b>{total:,.0f}</b><br>hours", showarrow=False, font=dict(size=15, color=INK_PRIMARY))
    fig = apply_layout(fig, title="Where the hours went", height=360)
    fig.update_layout(legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02))
    return fig


def credited_donut(row: pd.Series) -> go.Figure:
    """What made up the credited hours that count toward the Hours Expectation."""
    parts = pd.Series({
        "Client": row.get("Client", 0.0), "Firm's Own Account": row.get("FOA", 0.0),
        "Pro Bono": row.get("Pro Bono", 0.0), "Creditable (counted)": row.get("Creditable NB (counted)", 0.0),
    }).fillna(0.0)
    parts = parts[parts > 0.05]
    fig = go.Figure(go.Pie(
        labels=parts.index, values=parts.values, hole=0.55, sort=False,
        marker=dict(colors=[CATEGORY_COLORS[c] for c in parts.index], line=dict(color="#ffffff", width=2)),
        textinfo="percent", textposition="inside",
        hovertemplate="%{label}: %{value:,.1f} hrs (%{percent})<extra></extra>",
    ))
    fig.add_annotation(text=f"<b>{parts.sum():,.0f}</b><br>credited", showarrow=False, font=dict(size=15, color=INK_PRIMARY))
    fig = apply_layout(fig, title="Credited hours mix", height=360)
    fig.update_layout(legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02))
    return fig


def requirement_bullets(row: pd.Series, lo: float = 90) -> go.Figure:
    """Actual vs. prorated requirement for each policy test, as bullet bars:
    the bar is the actual, the tick the requirement, the shaded segment the
    90-100% window."""
    tests = [("Hours Expectation", row.get("Credited Hours"), row.get("Expectation")),
             ("Total Activity", row.get("Total Hours"), row.get("Total Expectation")),
             ("Bonus Threshold", row.get("Bonus Hours"), row.get("Bonus Threshold"))]
    tests = [(n, a, t) for n, a, t in tests if pd.notna(a) and pd.notna(t) and t]
    fig = go.Figure()
    names = [n for n, _, _ in tests]
    for n, a, t in tests:
        fig.add_shape(type="rect", x0=t * lo / 100, x1=t, y0=names.index(n) - 0.38, y1=names.index(n) + 0.38,
                      fillcolor="#2a78d6", opacity=0.12, line_width=0, layer="below")
    colors = [STATUS["good"] if a >= t else ("#2a78d6" if a >= t * lo / 100 else STATUS["critical"]) for _, a, t in tests]
    fig.add_trace(go.Bar(
        y=names, x=[a for _, a, _ in tests], orientation="h", marker_color=colors, width=0.42,
        hovertemplate="%{y}: %{x:,.1f} hrs<extra></extra>", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        y=names, x=[t for _, _, t in tests], mode="markers", showlegend=False,
        marker=dict(symbol="line-ns", size=26, line=dict(width=3, color=INK_PRIMARY)),
        hovertemplate="Requirement: %{x:,.1f} hrs<extra></extra>",
    ))
    # Labels to the right of whichever is further out (bar or requirement tick).
    xmax = max([max(a, t) for _, a, t in tests] or [1]) * 1.55
    for n, a, t in tests:
        fig.add_annotation(x=max(a, t), y=n, xshift=10, xanchor="left", showarrow=False,
                           text=f"<b>{a:,.0f}</b> of {t:,.0f} ({a / t * 100:.0f}%)",
                           font=dict(size=12, color=INK_PRIMARY))
    fig = apply_layout(fig, title="Against each requirement (prorated; tick = requirement)",
                       height=120 + 70 * max(len(tests), 1), legend=False)
    fig.update_xaxes(range=[0, xmax], title_text="Hours", showgrid=True, automargin=True)
    fig.update_yaxes(autorange="reversed", showgrid=False, automargin=True)
    fig.update_layout(margin=dict(b=50))
    return fig


def monthly_stack(monthly: pd.DataFrame) -> go.Figure:
    """Stacked monthly hours by category. monthly: month + hours_credit.HOURS_COLS."""
    cols = [("client_hours", "Client"), ("foa_hours", "Firm's Own Account"), ("pro_bono_hours", "Pro Bono"),
            ("creditable_hours", "Creditable (counted)"), ("other_hours", "Other Non-billable"),
            ("time_off_hours", "PTO / Holiday")]
    fig = go.Figure()
    for col, label in cols:
        if col in monthly and monthly[col].abs().sum() > 0:
            fig.add_trace(go.Bar(x=monthly["month"], y=monthly[col], name=label,
                                 marker_color=CATEGORY_COLORS[label if label != "Creditable (counted)" else "Creditable (counted)"],
                                 hovertemplate=label + ": %{y:,.1f} hrs<extra></extra>"))
    fig = apply_layout(fig, title="Hours by month", height=360)
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_xaxes(dtick="M1", tickformat="%b %y")
    fig.update_yaxes(title_text="Hours")
    return fig


def peer_strip(scorecard: pd.DataFrame, name: str, role_label: str) -> go.Figure:
    """Where this person finished among their group, % of Hours Expectation."""
    d = scorecard.sort_values("% of Expectation")
    is_me = d["Timekeeper"] == name
    fig = go.Figure()
    fig.add_vrect(x0=90, x1=100, fillcolor="#2a78d6", opacity=0.10, line_width=0, layer="below")
    fig.add_trace(go.Scatter(
        x=d.loc[~is_me, "% of Expectation"], y=[0] * int((~is_me).sum()), mode="markers", name="Peers",
        marker=dict(size=12, color=INK_MUTED, opacity=0.55), text=d.loc[~is_me, "Timekeeper"],
        hovertemplate="%{text}: %{x:.1f}%<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=d.loc[is_me, "% of Expectation"], y=[0], mode="markers+text", name=name,
        marker=dict(size=18, color="#2a78d6", line=dict(color="#0d366b", width=2)),
        text=[f"{fmt_pct_smart(v)}" for v in d.loc[is_me, "% of Expectation"]], textposition="top center",
        hovertemplate=name + ": %{x:.1f}%<extra></extra>"))
    fig.add_vline(x=100, line_dash="dot", line_color=INK_MUTED)
    fig = apply_layout(fig, title=f"Among {role_label} (% of Hours Expectation)", height=230, legend=False)
    fig.update_yaxes(visible=False, range=[-1, 1.2])
    fig.update_layout(margin=dict(b=40))
    fig.update_xaxes(ticksuffix="%", range=[0, max(115, float(d["% of Expectation"].max() or 0) + 8)])
    return fig
