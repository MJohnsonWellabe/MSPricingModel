"""Calculation tab: execute the run and expose inspectable engine output."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import get_assumptions
from medigap_engine.engine.run import run
from medigap_engine.models.assumptions import PROJECTION_YEARS
from medigap_engine.models.config import RunConfig
from medigap_engine.models.sensitivities import SensitivitySet


def render() -> None:
    st.header("Calculation")

    config: RunConfig = st.session_state.get("run_config") or RunConfig(
        states=["All"], sensitivities=SensitivitySet())

    st.write(f"States to run: **{', '.join(config.states)}**  |  "
             f"Solve rerates: **{config.solve_rerates}**")

    if st.button("Compute now", type="primary") or st.session_state.get("run_requested"):
        st.session_state.run_requested = False
        asm = get_assumptions()
        cells = st.session_state.cells
        with st.status("Running projection…", expanded=False) as status:
            result, diag = run(cells, asm, config)
            status.update(label="Done", state="complete")
        st.session_state.run_result = result
        st.session_state.diagnostics = diag
        st.success("Run complete — see the Output tab for results.")

    diag = st.session_state.get("diagnostics")
    if diag:
        st.subheader("Solver diagnostics")
        rows = []
        for state, info in diag.items():
            rows.append({
                "State": state,
                "Status": info.get("status"),
                "Switchover x": round(info.get("x", 0), 2) if info.get("x") else None,
                "Achieved lifetime LR": round(info.get("achieved_lifetime_lr", 0), 4)
                if "achieved_lifetime_lr" in info else None,
                "LR-floor breaches (durations)": ", ".join(
                    str(d) for d in info.get("in_year_lr_floor_breaches", [])) or "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    result = st.session_state.get("run_result")
    if result:
        st.subheader("Inspect engine output")
        state = st.selectbox("State", list(result.by_state.keys()))
        st.caption("Full 30-year projection (aggregated, distribution-weighted).")
        series = result.by_state[state].series
        df = pd.DataFrame(series)
        df.insert(0, "Duration", range(1, PROJECTION_YEARS + 1))
        st.dataframe(df, hide_index=True, use_container_width=True, height=400)
