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
    title: str | None = None,
    top_n: int = 10,
    value_is_currency: bool = True,
) -> go.Figure:
    sub = df.nlargest(top_n, value_col).sort_values(value_col)  # ascending so largest ends up on top
    texttemplate = "%{x:$,.0f}" if value_is_currency else "%{x:,.1f}"
    fig = go.Figure(
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
    apply_layout(fig, title=title, legend=False, height=max(320, 28 * len(sub) + 80))
    fig.update_xaxes(showgrid=True)
    return fig
