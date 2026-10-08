"""Charts for client concentration, creditable sources, seasonality and LLP
economics (see dashboard/client_analysis.py)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.client_service import CLIENT_TYPE_COLORS
from dashboard.charts.theme import INK_SECONDARY, apply_layout

# Entity colors match the client-type colors used elsewhere (LLP blue, LLC orange).
ENTITY_COLORS = {"LLP": CLIENT_TYPE_COLORS["Law (LLP) clients"], "LLC": CLIENT_TYPE_COLORS["Advisory (LLC) clients"],
                 "Somos MX": CLIENT_TYPE_COLORS["Somos MX clients"], "Other": "#d6d4cc"}
# Ordinal blue ramp for fiscal years (oldest lightest), validated as an ordinal ramp.
YEAR_RAMP = ["#86b6ef", "#2a78d6", "#184f95", "#0d366b"]


def _hbar_layout(fig, title, n, x_title, x_max):
    fig = apply_layout(fig, title=title, height=140 + 34 * n)
    fig.update_layout(barmode="stack", bargap=0.3, margin=dict(t=80, b=60),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, traceorder="normal"))
    fig.update_xaxes(title_text=x_title, showgrid=True, range=[0, x_max])
    fig.update_yaxes(showgrid=False, automargin=True, autorange="reversed")
    return fig


def top_clients_chart(top: pd.DataFrame, label: str = "Client") -> go.Figure:
    """Top clients by client hours, colored by entity, labeled with share and cumulative share."""
    d = top.copy()
    d["_label"] = d["Rank"].astype(str) + ". " + d["Client"]
    fig = go.Figure()
    for ent, color in ENTITY_COLORS.items():
        sub = d[d["Entity"] == ent]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            y=sub["_label"], x=sub["Hours"], orientation="h", name=ent, marker=dict(color=color),
            customdata=sub[["Share of Hours %", "Cumulative %", "Value", "People"]].values,
            hovertemplate="<b>%{y}</b><br>%{x:,.0f} hrs · %{customdata[0]:.1f}% of client hours "
                          "(cumulative %{customdata[1]:.1f}%)<br>Billing value $%{customdata[2]:,.0f} · "
                          "%{customdata[3]} people<extra></extra>"))
    fig.add_trace(go.Scatter(
        y=d["_label"], x=d["Hours"], mode="text", showlegend=False, hoverinfo="skip",
        text=[f"{s:.1f}%  ·  cum. {c:.0f}%" for s, c in zip(d["Share of Hours %"], d["Cumulative %"])],
        textposition="middle right", textfont=dict(color=INK_SECONDARY, size=11)))
    fig = _hbar_layout(fig, f"Top {len(d)} {label.lower()}s by client hours", len(d), "Client hours",
                       float(d["Hours"].max()) * 1.35)
    fig.update_yaxes(categoryorder="array", categoryarray=d["_label"].tolist())
    return fig


def creditable_chart(by_activity: pd.DataFrame) -> go.Figure:
    """Creditable non-billable hours by activity, split by entity."""
    d = by_activity[by_activity["Total"] >= 1]
    fig = go.Figure()
    for ent in [c for c in ENTITY_COLORS if c in d.columns]:
        fig.add_trace(go.Bar(y=d["Activity"], x=d[ent], orientation="h", name=ent,
                             marker=dict(color=ENTITY_COLORS[ent], line=dict(color="#fcfcfb", width=1)),
                             hovertemplate="<b>%{y}</b><br>" + ent + ": %{x:,.0f} hrs<extra></extra>"))
    fig.add_trace(go.Scatter(y=d["Activity"], x=d["Total"], mode="text", text=d["Total"].map(lambda v: f"{v:,.0f}"),
                             textposition="middle right", textfont=dict(color=INK_SECONDARY, size=11),
                             showlegend=False, hoverinfo="skip"))
    fig = _hbar_layout(fig, "Creditable non-billable hours by activity and entity", len(d), "Hours",
                       float(d["Total"].max()) * 1.15)
    fig.update_yaxes(categoryorder="array", categoryarray=d["Activity"].tolist())
    return fig


def monthly_practice_chart(by_practice: pd.DataFrame, monthly: pd.DataFrame) -> go.Figure:
    """Client hours by month, stacked by entity, with workdays noted under each month."""
    fig = go.Figure()
    for ent in [c for c in ENTITY_COLORS if c in by_practice.columns]:
        fig.add_trace(go.Bar(x=by_practice["Month"], y=by_practice[ent], name=ent,
                             marker=dict(color=ENTITY_COLORS[ent], line=dict(color="#fcfcfb", width=1)),
                             hovertemplate="%{x|%b %Y} " + ent + ": %{y:,.0f} hrs<extra></extra>"))
    fig.add_trace(go.Scatter(x=monthly["Month"], y=monthly["Client Hours"], mode="text", showlegend=False,
                             text=monthly["Client Hours"].map(lambda v: f"{v:,.0f}"), textposition="top center",
                             textfont=dict(color=INK_SECONDARY, size=11), hoverinfo="skip"))
    fig = apply_layout(fig, title="Client hours by month and entity", height=380)
    fig.update_layout(barmode="stack", bargap=0.25, margin=dict(t=80, b=70),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, traceorder="normal"))
    fig.update_xaxes(dtick="M1", tickformat="%b<br>%Y", showgrid=False)
    fig.update_yaxes(title_text="Client hours", range=[0, float(monthly["Client Hours"].max()) * 1.15], automargin=True)
    fig.update_layout(margin=dict(l=80))
    return fig


def per_workday_chart(history: pd.DataFrame) -> go.Figure:
    """Billable hours per requirement holder per workday, by fiscal month, one line per FY."""
    fig = go.Figure()
    years = sorted(history["FY"].unique())
    ramp = YEAR_RAMP[-len(years):] if len(years) <= len(YEAR_RAMP) else YEAR_RAMP
    order = history.drop_duplicates("fm").sort_values("fm")["Fiscal Month"].tolist()
    for fy, color in zip(years, ramp):
        sub = history[history["FY"] == fy].sort_values("fm")
        fig.add_trace(go.Scatter(
            x=sub["Fiscal Month"], y=sub["Per Timekeeper per Workday"], mode="lines+markers", name=fy,
            line=dict(color=color, width=2.5 if fy == years[-1] else 2), marker=dict(size=8, color=color),
            customdata=sub[["n"]].values,
            hovertemplate=fy + " %{x}: %{y:.2f} hrs per timekeeper per workday (%{customdata[0]} timekeepers)<extra></extra>"))
    fig = apply_layout(fig, title="Billable hours per timekeeper per workday, by fiscal month", height=360)
    fig.update_layout(margin=dict(t=80, b=50), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0))
    fig.update_xaxes(categoryorder="array", categoryarray=order, showgrid=False)
    fig.update_yaxes(title_text="Hours / timekeeper / workday", rangemode="tozero", automargin=True)
    fig.update_layout(margin=dict(l=80))
    return fig


def pto_chart(monthly: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(x=monthly["Month"], y=monthly["PTO / Holiday"], marker=dict(color="#b9b7ae"),
                           hovertemplate="%{x|%b %Y}: %{y:,.0f} PTO / holiday hrs<extra></extra>", showlegend=False))
    fig = apply_layout(fig, title="PTO and holiday hours by month", height=260, legend=False)
    fig.update_layout(margin=dict(t=60, b=50))
    fig.update_xaxes(dtick="M1", tickformat="%b", showgrid=False)
    fig.update_yaxes(title_text="Hours", automargin=True)
    fig.update_layout(margin=dict(l=80))
    return fig


def llp_rate_chart(by_pool: pd.DataFrame) -> go.Figure:
    """LLP client hours by who delivered them, labeled with billing value per hour."""
    d = by_pool[by_pool["Hours"] >= 50]
    fig = go.Figure(go.Bar(
        y=d["Pool"], x=d["Hours"], orientation="h", marker=dict(color=ENTITY_COLORS["LLP"]), showlegend=False,
        text=[f"{h:,.0f} hrs · ${r:,.0f}/hr" for h, r in zip(d["Hours"], d["Value / Hour"])],
        textposition="outside", textfont=dict(color=INK_SECONDARY, size=11), cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} LLP client hrs<extra></extra>"))
    fig = apply_layout(fig, title="LLP client hours by who delivered them (billing value per hour)",
                       height=120 + 34 * len(d), legend=False)
    fig.update_layout(margin=dict(t=60, b=50))
    fig.update_xaxes(title_text="Hours", showgrid=True, range=[0, float(d["Hours"].max()) * 1.4])
    fig.update_yaxes(showgrid=False, automargin=True, autorange="reversed")
    return fig
