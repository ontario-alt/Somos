"""Treemap for WIP composition by matter -- sequential (blue) magnitude encoding."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import SEQUENTIAL, apply_layout, fmt_currency


def wip_treemap(df: pd.DataFrame, *, label_col: str, value_col: str, parent_col: str | None = None, title: str | None = None) -> go.Figure:
    """df: one row per matter (or client > matter if parent_col given)."""
    labels = df[label_col].astype(str).tolist()
    values = df[value_col].tolist()
    parents = df[parent_col].astype(str).tolist() if parent_col else [""] * len(df)

    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=parents,
            values=values,
            marker=dict(
                colors=values,
                colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
                showscale=False,
            ),
            textinfo="label+value",
            texttemplate="%{label}<br>%{value:$,.0f}",
            hovertemplate="%{label}: %{value:$,.0f}<extra></extra>",
        )
    )
    apply_layout(fig, title=title, legend=False, height=420)
    return fig
