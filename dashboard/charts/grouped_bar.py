"""
Grouped bar (FY vs. prior FY, side by side) and bar-with-target-line
(originations pacing by attorney vs. annual target).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import CATEGORICAL, STATUS, apply_layout


def grouped_bar_by_series(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    series_col: str,
    title: str | None = None,
    y_is_currency: bool = True,
) -> go.Figure:
    """e.g. x=entity, series={'This FY', 'Prior FY'} -- side-by-side bars,
    not stacked, so the two periods are directly comparable per category."""
    fig = go.Figure()
    series_values = list(dict.fromkeys(df[series_col]))
    hover_fmt = "%{y:$,.0f}" if y_is_currency else "%{y:,.0f}"
    for i, series in enumerate(series_values):
        sub = df[df[series_col] == series]
        fig.add_trace(
            go.Bar(
                name=str(series),
                x=sub[x_col],
                y=sub[y_col],
                marker_color=CATEGORICAL[i % len(CATEGORICAL)],
                hovertemplate=f"{series}: {hover_fmt}<extra></extra>",
            )
        )
    fig.update_layout(barmode="group")
    apply_layout(fig, title=title)
    return fig


def bar_with_target(
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    target_col: str,
    title: str | None = None,
) -> go.Figure:
    """One bar per label (e.g. originating attorney) sized by actual
    value, with a target marker overlaid at the target value -- bar
    colored by status (met/under target) rather than a flat categorical
    hue, since this chart's whole point is over/under."""
    df = df.copy()
    df["_status_color"] = df.apply(
        lambda r: STATUS["good"] if r[value_col] >= r[target_col] else STATUS["warning"], axis=1
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df[label_col],
            y=df[value_col],
            marker_color=df["_status_color"],
            name="Actual",
            hovertemplate="%{x}: %{y:$,.0f} actual<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df[label_col],
            y=df[target_col],
            mode="markers",
            marker=dict(symbol="line-ew", size=22, line=dict(width=3, color="#0b0b0b")),
            name="Target",
            hovertemplate="%{x}: %{y:$,.0f} target<extra></extra>",
        )
    )
    apply_layout(fig, title=title)
    return fig
