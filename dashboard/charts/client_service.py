"""Client service hours charts: the firm's pool by who delivered it, and each
timekeeper's hours by client type (see dashboard/client_service.py)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, INK_SECONDARY, apply_layout

# First three categorical slots (validated all-pairs) for the three main
# client types; the minor types share neutrals so they never compete.
CLIENT_TYPE_COLORS = {
    "Law (LLP) clients": CATEGORICAL[0],
    "Advisory (LLC) clients": CATEGORICAL[1],
    "Pro bono": CATEGORICAL[2],
    "Somos MX clients": "#8f8d85",
    "Firm's Own Account": "#b9b7ae",
    "Other client work": "#d6d4cc",
}
_EXTRA = ["#6f6d66", "#a7a59c", "#cfcdc4"]


def _colors(types: list[str]) -> dict:
    out, extra = {}, iter(_EXTRA * 3)
    for t in types:
        out[t] = CLIENT_TYPE_COLORS.get(t) or next(extra)
    return out


def _stacked(rows: pd.DataFrame, label_col: str, types: list[str], title: str, height: int,
             total_col: str = "Client Service Hours", group_col: str | None = None) -> go.Figure:
    colors = _colors(types)
    # Grouped axis (group, label) when group_col is given.
    y = [rows[group_col].tolist(), rows[label_col].tolist()] if group_col else rows[label_col]
    fig = go.Figure()
    for t in types:
        if t not in rows or rows[t].sum() <= 0:
            continue
        fig.add_trace(go.Bar(
            y=y, x=rows[t], orientation="h", name=t,
            marker=dict(color=colors[t], line=dict(color="#fcfcfb", width=1)),
            hovertemplate="<b>%{y}</b><br>" + t + ": %{x:,.0f} hrs<extra></extra>"))
    # Total at the end of each bar (text in ink, not series color).
    fig.add_trace(go.Scatter(
        y=y, x=rows[total_col], mode="text", text=rows[total_col].map(lambda v: f"{v:,.0f}"),
        textposition="middle right", textfont=dict(color=INK_SECONDARY, size=11), showlegend=False, hoverinfo="skip"))
    fig = apply_layout(fig, title=title, height=height)
    fig.update_layout(barmode="stack", bargap=0.3,
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, traceorder="normal"),
                      margin=dict(t=80, b=60))
    fig.update_xaxes(title_text="Hours", showgrid=True, range=[0, float(rows[total_col].max() or 1) * 1.12])
    fig.update_yaxes(showgrid=False, automargin=True, autorange="reversed")
    if not group_col:
        fig.update_yaxes(categoryorder="array", categoryarray=rows[label_col].tolist())
    return fig


def pool_chart(summary: pd.DataFrame, types: list[str]) -> go.Figure:
    """Client service hours by who delivered them, split by client type."""
    return _stacked(summary, "Pool", types, "Client service hours by who delivered them",
                    height=140 + 38 * len(summary))


def timekeeper_chart(by_tk: pd.DataFrame, types: list[str]) -> go.Figure:
    """Each timekeeper's client service hours by client type, grouped by pool."""
    d = by_tk.copy()
    d["_group"] = d["Pool"].map(lambda p: p.split(" — ")[0])
    return _stacked(d, "Timekeeper", types, "Client service hours by timekeeper and client type",
                    height=160 + 24 * len(d), group_col="_group")
