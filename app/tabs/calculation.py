"""Calculation tab: solver diagnostics and inspectable engine output for the last run.

The model is run from the **Run model** button on the Configuration tab (which shows the
progress bar and jumps to Output on completion); this tab inspects what that run produced.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from medigap_engine.models.assumptions import PROJECTION_YEARS
from medigap_engine.models.config import RunConfig
from medigap_engine.models.sensitivities import SensitivitySet


def render() -> None:
    st.header("Calculation")

    config: RunConfig = st.session_state.get("run_config") or RunConfig(
        states=["All"], sensitivities=SensitivitySet())
    st.write(f"States to run: **{', '.join(config.states)}**  |  "
             f"Solve rerates: **{config.solve_rerates}**")
    st.caption("Run the model from the **Run model** button on the Configuration tab. "
               "This tab shows solver diagnostics and the full projection for the last run.")

    if not st.session_state.get("run_result"):
        st.info("No results yet — run the model from the Configuration tab.")

    diag = st.session_state.get("diagnostics")
    if diag:
        st.subheader("Solver diagnostics")
        rows = []
        for state, info in diag.items():
            rows.append({
                "State": state,
                "Status": info.get("status"),
                "Front-load yrs (K)": round(info.get("K", 0), 2) if info.get("K") else None,
                "Achieved lifetime LR": round(info.get("achieved_lifetime_lr", 0), 4)
                if "achieved_lifetime_lr" in info else None,
                "In-year LR below floor (durations)": ", ".join(
                    str(d) for d in info.get("in_year_lr_floor_breaches", [])) or "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    result = st.session_state.get("run_result")
    if result:
        st.subheader("Inspect engine output")
        state = st.selectbox("State", list(result.by_state.keys()), key="calc_state")
        st.caption("Full 30-year projection (aggregated, distribution-weighted).")
        series = result.by_state[state].series
        df = pd.DataFrame(series)
        df.insert(0, "Duration", range(1, PROJECTION_YEARS + 1))
        st.dataframe(df, hide_index=True, use_container_width=True, height=400)
