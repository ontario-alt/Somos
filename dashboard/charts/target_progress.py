"""Horizontal bar of each timekeeper's creditable hours as % of their
prorated target, colored by pace status, with a tick at where they
should be by now (expected-to-date %)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import INK_PRIMARY, INK_MUTED, STATUS, apply_layout

STATUS_COLORS = {
    "Met": STATUS["good"],
    "On Track": "#1baf7a",
    "Watch": STATUS["warning"],
    "Behind": STATUS["serious"],
    "Not Met": STATUS["critical"],
}


def target_progress(df: pd.DataFrame, expected_pct: pd.Series | None = None) -> go.Figure:
    """df needs Timekeeper, % of Expectation, Credited Hours, Expectation and a
    status column -- colored by Expectation Status (what the bar measures)
    when present, else Status."""
    d = df.copy()
    d["_status"] = d["Expectation Status"] if "Expectation Status" in d else d["Status"]
    d["_pct"] = d["% of Expectation"].fillna(0).clip(upper=150)
    d = d.sort_values("_pct")
    fig = go.Figure()
    for status, color in STATUS_COLORS.items():
        sub = d[d["_status"] == status]
        if sub.empty:
            continue
        fig.add_trace(
            go.Bar(
                y=sub["Timekeeper"], x=sub["_pct"], orientation="h", name=status, marker_color=color,
                customdata=sub[["Credited Hours", "Expectation", "% of Expectation"]].values,
                hovertemplate="<b>%{y}</b><br>%{customdata[0]:,.1f} of %{customdata[1]:,.1f} hrs "
                "(%{customdata[2]:.1f}%)<extra>" + status + "</extra>",
            )
        )
    if expected_pct is not None:
        exp = expected_pct.reindex(d.index)
        fig.add_trace(
            go.Scatter(
                y=d["Timekeeper"], x=exp, mode="markers", name="Expected by now",
                marker=dict(symbol="line-ns", size=16, line=dict(width=3, color=INK_PRIMARY)),
                hovertemplate="Expected by now: %{x:.1f}%<extra></extra>",
            )
        )
    fig.add_vline(x=100, line_dash="dot", line_color=INK_MUTED)
    fig = apply_layout(fig, height=max(260, 26 * len(d) + 90))
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.update_xaxes(title_text="Credited hours, % of prorated Hours Expectation", ticksuffix="%", showgrid=True, automargin=True)
    fig.update_yaxes(showgrid=False, automargin=True, categoryorder="array", categoryarray=d["Timekeeper"].tolist())
    return fig


def cumulative_vs_target(pace: pd.DataFrame, name: str) -> go.Figure:
    """pace: month, creditable_cum, expected_cum (from hours_credit.cumulative_pace)."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=pace["month"], y=pace["expected_cum"], name="Expected (Hours Expectation path)",
                   mode="lines", line=dict(color=INK_MUTED, dash="dash"))
    )
    fig.add_trace(
        go.Scatter(x=pace["month"], y=pace["creditable_cum"], name="Credited hours (cumulative)",
                   mode="lines+markers", line=dict(color="#2a78d6", width=3))
    )
    if "total_cum" in pace:
        fig.add_trace(
            go.Scatter(x=pace["month"], y=pace["total_expected_cum"], name="Expected (Total Activity path)",
                       mode="lines", line=dict(color="#eb6834", dash="dash", width=1.5))
        )
        fig.add_trace(
            go.Scatter(x=pace["month"], y=pace["total_cum"], name="Total activity hours (cumulative)",
                       mode="lines+markers", line=dict(color="#eb6834", width=2))
        )
    fig = apply_layout(fig, title=f"{name}: cumulative hours vs. target paths", height=380)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="left", x=0))
    fig.update_yaxes(title_text="Hours")
    return fig


WINDOW_COLORS = {
    "Met (100%+)": STATUS["good"],
    "90–100% window": "#2a78d6",
    "Below 90%": "#d9a3a3",
}


def window_zone(pct: float, lo: float, hi: float) -> str:
    if pd.isna(pct):
        return "Below 90%"
    if pct >= hi:
        return "Met (100%+)"
    if pct >= lo:
        return "90–100% window"
    return "Below 90%"


def evaluation_window_chart(df: pd.DataFrame, lo: float = 90, hi: float = 100,
                            value_col: str = "% of Expectation", title: str | None = None) -> go.Figure:
    """Horizontal bar per timekeeper (highest at top) of `value_col`, with the
    lo-hi band drawn as a shaded, outlined region and the timekeepers inside
    it colored and labeled distinctly -- the group that may be evaluated
    further. df needs Timekeeper, value_col, Credited Hours, Expectation."""
    d = df.copy()
    d["_pct"] = d[value_col].astype(float)
    d["_zone"] = d["_pct"].map(lambda v: window_zone(v, lo, hi))
    d = d.sort_values("_pct", ascending=True)  # plotly draws bottom-up -> highest on top
    x_max = max(110.0, float(d["_pct"].max() or 0) + 8)

    fig = go.Figure()
    # The window: shaded band with solid edges, labeled at the top.
    fig.add_vrect(x0=lo, x1=hi, fillcolor="#2a78d6", opacity=0.10, layer="below", line_width=0)
    for x in (lo, hi):
        fig.add_vline(x=x, line_color="#184f95", line_width=2, layer="below")
    fig.add_annotation(x=(lo + hi) / 2, y=1.0, yref="paper", yanchor="bottom", showarrow=False,
                       text=f"<b>{lo:.0f}–{hi:.0f}% window</b>", font=dict(color="#184f95", size=12))

    for zone, color in WINDOW_COLORS.items():
        sub = d[d["_zone"] == zone]
        if sub.empty:
            continue
        in_window = zone == "90–100% window"
        fig.add_trace(
            go.Bar(
                y=sub["Timekeeper"], x=sub["_pct"], orientation="h", name=f"{zone} ({len(sub)})",
                marker=dict(color=color, line=dict(color="#0d366b" if in_window else color, width=2 if in_window else 0)),
                text=sub["_pct"].map(lambda v: f"{v:.1f}%"), textposition="outside",
                textfont=dict(color="#0d366b" if in_window else INK_MUTED, size=12 if in_window else 11),
                cliponaxis=False,
                customdata=sub[["Credited Hours", "Expectation"]].values,
                hovertemplate="<b>%{y}</b><br>%{customdata[0]:,.1f} of %{customdata[1]:,.1f} hrs "
                              "(%{x:.1f}%)<extra>" + zone + "</extra>",
            )
        )
    fig = apply_layout(fig, title=title, height=max(300, 28 * len(d) + 120))
    fig.update_layout(barmode="overlay", bargap=0.3, margin=dict(t=70 if title else 50))
    fig.update_xaxes(range=[0, x_max], ticksuffix="%", dtick=10, showgrid=True, automargin=True,
                     title_text="Credited hours, % of prorated Hours Expectation")
    # Order by value, not by which color group's trace came first.
    fig.update_yaxes(showgrid=False, automargin=True, categoryorder="array", categoryarray=d["Timekeeper"].tolist())
    return fig
