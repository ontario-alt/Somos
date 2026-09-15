"""
Multi-line (or single-line) trend chart -- AR trend by entity, WIP aging
trend, realization rate trend, client concentration over time, FY
revenue with a shaded fiscal-year band.

All of these read one or more snapshot_date-partitioned points; with a
single snapshot in the warehouse today they render as one point per
series, which is honest (not a fabricated trend) and starts looking like
a real line the moment build_warehouse.py has run across a few periods.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, apply_layout


def trend_line(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    series_col: str | None = None,
    title: str | None = None,
    y_is_currency: bool = True,
    shaded_band: tuple | None = None,
    shaded_band_label: str | None = None,
    show_values: bool = False,
) -> go.Figure:
    """One line per series_col value (or a single unnamed line if
    series_col is None). shaded_band: (x0, x1) to highlight a fiscal-year
    window with a translucent rect behind the lines. show_values prints
    each point's own value above its marker -- useful once there are only
    a handful of points, where a data label reads faster than a hover."""
    fig = go.Figure()
    hover_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.1f}"
    text_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.1f}"
    mode = "lines+markers+text" if show_values else "lines+markers"

    if series_col:
        series_values = list(dict.fromkeys(df[series_col]))
        for i, series in enumerate(series_values):
            sub = df[df[series_col] == series].sort_values(x_col)
            fig.add_trace(
                go.Scatter(
                    name=str(series),
                    x=sub[x_col],
                    y=sub[y_col],
                    mode=mode,
                    line=dict(color=CATEGORICAL[i % len(CATEGORICAL)], width=2),
                    marker=dict(size=8),
                    texttemplate=text_fmt if show_values else None,
                    textposition="top center",
                    textfont=dict(size=10, color=CATEGORICAL[i % len(CATEGORICAL)]),
                    hovertemplate=f"{series}: {hover_fmt}<extra></extra>",
                )
            )
    else:
        sub = df.sort_values(x_col)
        fig.add_trace(
            go.Scatter(
                x=sub[x_col],
                y=sub[y_col],
                mode=mode,
                line=dict(color=CATEGORICAL[0], width=2),
                marker=dict(size=8),
                texttemplate=text_fmt if show_values else None,
                textposition="top center",
                textfont=dict(size=10, color=CATEGORICAL[0]),
                hovertemplate=hover_fmt + "<extra></extra>",
            )
        )

    if shaded_band:
        fig.add_vrect(
            x0=shaded_band[0],
            x1=shaded_band[1],
            fillcolor=CATEGORICAL[0],
            opacity=0.08,
            line_width=0,
            annotation_text=shaded_band_label,
            annotation_position="top left",
            annotation_font=dict(size=11, color="#52514e"),
        )

    apply_layout(fig, title=title, legend=bool(series_col))
    if not shaded_band:
        # Category axis reads cleanly for period labels. Skipped when a
        # shaded_band is given -- that needs a real continuous date axis
        # for the highlighted range to mean anything.
        fig.update_xaxes(type="category")
    return fig
