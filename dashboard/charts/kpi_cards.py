"""KPI card row -- st.metric styled with our ink/status tokens via delta_color."""
from __future__ import annotations

import streamlit as st


def kpi_row(cards: list[dict]):
    """cards: list of {label, value, delta (optional str), help (optional str)}."""
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.metric(
                label=card["label"],
                value=card["value"],
                delta=card.get("delta"),
                help=card.get("help"),
            )
