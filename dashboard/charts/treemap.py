"""Treemap for WIP composition by matter -- sequential (blue) magnitude encoding."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import SEQUENTIAL, apply_layout, fmt_currency


def wip_treemap(
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    parent_col: str | None = None,
    id_col: str | None = None,
    title: str | None = None,
) -> go.Figure:
    """df: one row per matter (or client > matter if parent_col given).
    Pass id_col when label_col values can repeat across different parents
    (e.g. two clients each with a matter literally named "General") --
    Plotly needs a unique id per node in that case even though the
    displayed label can still repeat."""
    labels = df[label_col].astype(str).tolist()
    values = df[value_col].tolist()
    parents = df[parent_col].astype(str).tolist() if parent_col else [""] * len(df)
    ids = df[id_col].astype(str).tolist() if id_col else None

    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=parents,
            values=values,
            ids=ids,
            branchvalues="total" if parent_col else "remainder",
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
