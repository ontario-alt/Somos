"""Stacked area -- revenue by matter type/practice area trend."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, apply_layout


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def stacked_area_by_series(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    series_col: str,
    title: str | None = None,
    y_is_currency: bool = True,
) -> go.Figure:
    """Long-form df: one row per (x, series) pair."""
    fig = go.Figure()
    series_values = list(dict.fromkeys(df[series_col]))
    hover_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.0f}"
    for i, series in enumerate(series_values):
        sub = df[df[series_col] == series].sort_values(x_col)
        color = CATEGORICAL[i % len(CATEGORICAL)]
        fig.add_trace(
            go.Scatter(
                name=str(series),
                x=sub[x_col],
                y=sub[y_col],
                mode="lines",
                stackgroup="one",
                line=dict(width=1.5, color=color),
                fillcolor=_hex_to_rgba(color, 0.75),
                hovertemplate=f"{series}: {hover_fmt}<extra></extra>",
            )
        )
    apply_layout(fig, title=title)
    return fig
