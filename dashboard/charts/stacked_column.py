"""Stacked column by entity (AR by entity, revenue by matter type, etc)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, apply_layout


def stacked_column_by_series(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    series_col: str,
    title: str | None = None,
    y_is_currency: bool = True,
    show_values: bool = False,
    color_map: dict | None = None,
) -> go.Figure:
    """One stacked column per x_col value, one series per series_col value.
    df must be long-form: one row per (x, series) pair. show_values prints
    each segment's own value inside the bar. color_map pins specific
    series values to specific colors (e.g. always color one entity the
    same way on every chart) instead of coloring by first-seen order."""
    fig = go.Figure()
    series_values = list(dict.fromkeys(df[series_col]))  # stable order, first-seen
    hover_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.0f}"
    text_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.0f}"
    for i, series in enumerate(series_values):
        sub = df[df[series_col] == series]
        fig.add_trace(
            go.Bar(
                name=str(series),
                x=sub[x_col],
                y=sub[y_col],
                marker_color=(color_map or {}).get(series, CATEGORICAL[i % len(CATEGORICAL)]),
                texttemplate=text_fmt if show_values else None,
                textposition="inside" if show_values else None,
                textfont=dict(size=10, color="#fcfcfb"),
                hovertemplate=f"{series}: {hover_fmt}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    apply_layout(fig, title=title)
    fig.update_xaxes(type="category")  # x values are month/period labels, not a continuous time axis
    return fig
