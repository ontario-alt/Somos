"""Variance table -- current period vs. prior period by entity (or any
grouping), since there's no budget data to compare against (per the
brief, this is a prior-year variance, not budget-vs-actual)."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def variance_table(
    df: pd.DataFrame,
    *,
    label_col: str,
    current_col: str,
    prior_col: str,
    label_header: str = "Entity",
    current_header: str = "Current",
    prior_header: str = "Prior",
):
    """Renders directly (st.dataframe) rather than returning a figure --
    a variance table is inherently tabular, not a chart."""
    out = df[[label_col, current_col, prior_col]].copy()
    out["Variance ($)"] = out[current_col] - out[prior_col]
    out["Variance (%)"] = ((out[current_col] - out[prior_col]) / out[prior_col].replace(0, pd.NA)) * 100
    out = out.rename(columns={label_col: label_header, current_col: current_header, prior_col: prior_header})
    st.dataframe(
        out,
        use_container_width=True,
        hide_index=True,
        column_config={
            current_header: st.column_config.NumberColumn(format="$%.0f"),
            prior_header: st.column_config.NumberColumn(format="$%.0f"),
            "Variance ($)": st.column_config.NumberColumn(format="$%.0f"),
            "Variance (%)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
