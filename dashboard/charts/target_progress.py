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
    fig.update_yaxes(showgrid=False, automargin=True)
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
