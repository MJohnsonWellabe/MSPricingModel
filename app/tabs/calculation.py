"""Calculation tab: execute the run and expose inspectable engine output."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import get_assumptions, get_cells
from medigap_engine.engine.aggregate import aggregate_states
from medigap_engine.engine.run import normalize_weights, run_state
from medigap_engine.models.assumptions import PROJECTION_YEARS
from medigap_engine.models.config import RunConfig
from medigap_engine.models.results import RunResult
from medigap_engine.models.sensitivities import SensitivitySet


def render() -> None:
    st.header("Calculation")

    config: RunConfig = st.session_state.get("run_config") or RunConfig(
        states=["All"], sensitivities=SensitivitySet())

    st.write(f"States to run: **{', '.join(config.states)}**  |  "
             f"Solve rerates: **{config.solve_rerates}**")

    if st.button("Compute now", type="primary") or st.session_state.get("run_requested"):
        st.session_state.run_requested = False
        st.session_state.calc_job = {
            "states": list(config.states), "i": 0, "by_state": {}, "diag": {},
            "config": config,
        }
        st.session_state.run_result = None
        st.rerun()

    # Process one state per rerun so the progress bar repaints between states
    # (a single synchronous loop never repaints under stlite).
    job = st.session_state.get("calc_job")
    if job:
        states = job["states"]
        total = len(states)
        i = job["i"]
        st.progress(i / total, text=f"Pricing {states[i]} ({i + 1}/{total})…")
        asm = get_assumptions()
        cells = normalize_weights(get_cells())
        st_res, info = run_state(states[i], cells, asm, job["config"])
        job["by_state"][states[i]] = st_res
        job["diag"][states[i]] = info
        job["i"] = i + 1
        if job["i"] < total:
            st.rerun()
        combined = (aggregate_states(job["by_state"], asm) if total > 1
                    else next(iter(job["by_state"].values()), None))
        st.session_state.run_result = RunResult(by_state=job["by_state"], all_states=combined)
        st.session_state.diagnostics = job["diag"]
        st.session_state.calc_job = None
        st.success("Run complete — see the Output tab for results.")

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
        state = st.selectbox("State", list(result.by_state.keys()))
        st.caption("Full 30-year projection (aggregated, distribution-weighted).")
        series = result.by_state[state].series
        df = pd.DataFrame(series)
        df.insert(0, "Duration", range(1, PROJECTION_YEARS + 1))
        st.dataframe(df, hide_index=True, use_container_width=True, height=400)
