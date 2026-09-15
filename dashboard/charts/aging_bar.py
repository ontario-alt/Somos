"""Stacked bar for AR/AP aging by bucket -- shared by weekly and monthly pages."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

import config
from dashboard.charts.theme import AGING_COLORS, AGING_LABELS, apply_layout, fmt_currency


def aging_stacked_bar(df: pd.DataFrame, *, group_col: str, title: str | None = None) -> go.Figure:
    """df must have `group_col` plus config.AGING_BUCKETS columns already
    summed at that grouping (e.g. one row per entity, or a single 'Total'
    row for a single-series view)."""
    fig = go.Figure()
    for bucket in config.AGING_BUCKETS:
        fig.add_trace(
            go.Bar(
                name=AGING_LABELS[bucket],
                x=df[group_col],
                y=df[bucket],
                marker_color=AGING_COLORS[bucket],
                hovertemplate=f"{AGING_LABELS[bucket]}: %{{y:$,.0f}}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    apply_layout(fig, title=title)
    return fig
