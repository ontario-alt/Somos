"""
Shared Plotly theme + formatting helpers, applied by every chart in
dashboard/charts/ so the app reads as one consistent system rather than
each page inventing its own colors.

Palette values come from the design system's validated default (fixed
categorical hue order, CVD-safe adjacent pairs; a single sequential hue
for magnitude; blue<->red for diverging; reserved status colors). Swap
these hexes for Somos's brand palette later -- keep the *roles* the same.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Fixed categorical order -- never cycle/reassign by rank. A page with
# more series than this should fold extras into "Other" rather than
# generating new hues.
CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]

# Single-hue sequential ramp (blue), light -> dark, for magnitude
# encodings (treemap, heatmap).
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]

# Diverging: blue <-> red around a neutral gray midpoint, for
# variance/prior-year-comparison charts.
DIVERGING = ["#0d366b", "#2a78d6", "#9ec5f4", "#f0efec", "#f3b3b2", "#e34948", "#7a1f1f"]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"

FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# Aging buckets, oldest-last color-mapped so "over_120" always reads as
# the most severe (status red), not just the last categorical slot.
AGING_COLORS = {
    "current_0_30": "#1baf7a",
    "days_31_60": "#eda100",
    "days_61_90": "#eb6834",
    "days_91_120": STATUS["serious"],
    "over_120": STATUS["critical"],
}
AGING_LABELS = {
    "current_0_30": "Current (0-30)",
    "days_31_60": "31-60 days",
    "days_61_90": "61-90 days",
    "days_91_120": "91-120 days",
    "over_120": "Over 120 days",
}


def apply_layout(fig: go.Figure, *, title: str | None = None, height: int = 380, legend: bool = True) -> go.Figure:
    """Apply the shared chrome (fonts, gridlines, background, legend
    placement) to any figure. Call this last, after adding traces."""
    layout_kwargs = dict(
        font=dict(family=FONT_FAMILY, color=INK_SECONDARY, size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=10, r=10, t=48 if title else 16, b=10),
        showlegend=legend,
        hoverlabel=dict(bgcolor=SURFACE, font=dict(family=FONT_FAMILY, color=INK_PRIMARY)),
    )
    if title:
        layout_kwargs["title"] = dict(text=title, font=dict(size=15, color=INK_PRIMARY))
    if legend:
        layout_kwargs["legend"] = dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, color=INK_SECONDARY),
        )
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BASELINE, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(showgrid=True, gridcolor=GRIDLINE, zeroline=False, tickfont=dict(color=INK_MUTED))
    return fig


def fmt_currency(value: float | None, *, short: bool = False) -> str:
    if value is None:
        return "--"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if short:
        if v >= 1_000_000:
            return f"{sign}${v/1_000_000:,.1f}M"
        if v >= 1_000:
            return f"{sign}${v/1_000:,.0f}K"
    return f"{sign}${v:,.0f}"


def fmt_pct(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "--"
    return f"{value:.{decimals}f}%"
