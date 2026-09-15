"""Horizontal ranked bar -- top-N matters/clients by WIP, AR, or hours."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, apply_layout


def ranked_bar(
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    series_col: str | None = None,
    color_map: dict | None = None,
    title: str | None = None,
    top_n: int = 10,
    value_is_currency: bool = True,
) -> go.Figure:
    """series_col (e.g. entity) colors each bar by that column and adds a
    legend -- pass color_map to pin specific values to specific colors
    (falls back to CATEGORICAL order otherwise)."""
    sub = df.nlargest(top_n, value_col).sort_values(value_col)  # ascending so largest ends up on top
    texttemplate = "%{x:$,.0f}" if value_is_currency else "%{x:,.1f}"
    fig = go.Figure()

    if series_col:
        y_order = sub[label_col].astype(str).tolist()
        series_values = list(dict.fromkeys(sub[series_col]))
        for i, series in enumerate(series_values):
            part = sub[sub[series_col] == series]
            color = (color_map or {}).get(series, CATEGORICAL[i % len(CATEGORICAL)])
            fig.add_trace(
                go.Bar(
                    name=str(series),
                    x=part[value_col],
                    y=part[label_col].astype(str),
                    orientation="h",
                    marker_color=color,
                    text=part[value_col],
                    texttemplate=texttemplate,
                    textposition="outside",
                    hovertemplate=f"{series} - %{{y}}: {texttemplate}<extra></extra>",
                )
            )
        fig.update_yaxes(categoryorder="array", categoryarray=y_order)
    else:
        fig.add_trace(
            go.Bar(
                x=sub[value_col],
                y=sub[label_col].astype(str),
                orientation="h",
                marker_color=CATEGORICAL[0],
                text=sub[value_col],
                texttemplate=texttemplate,
                textposition="outside",
                hovertemplate=f"%{{y}}: {texttemplate}<extra></extra>",
            )
        )

    apply_layout(fig, title=title, legend=bool(series_col), height=max(320, 28 * len(sub) + 80))
    # Outside-positioned text needs headroom past the longest bar, or the
    # largest value's label gets clipped off the right edge of the plot.
    max_val = sub[value_col].max() if not sub.empty else 0
    fig.update_xaxes(showgrid=True, range=[0, max_val * 1.2 if max_val else 1])
    return fig
