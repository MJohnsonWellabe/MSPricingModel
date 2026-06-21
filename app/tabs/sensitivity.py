"""Sensitivity tab: stochastic IRR ranges per state.

Each simulation draws the 5 sensitivity factors from Normal(mean, std), re-solves
rerates (same lifetime target) and projects to an IRR. Processes one state per
Streamlit rerun so the progress bar repaints under stlite.
"""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.state import get_assumptions, get_cells, get_formulas
from medigap_engine.engine.run import normalize_weights
from medigap_engine.engine.sensitivity import FACTORS, simulate_state
from medigap_engine.io.defaults import available_states

_LABELS = {
    "morbidity_scale": "Morbidity (claim cost) ×",
    "termination_scale": "Termination (lapse) ×",
    "rerate_effectiveness": "Rerate effectiveness ×",
    "antiselective_lapse": "Antiselective lapse ×",
    "antiselective_claims": "Antiselective claims ×",
}
_DEFAULT_STD = {
    "morbidity_scale": 0.05, "termination_scale": 0.05, "rerate_effectiveness": 0.05,
    "antiselective_lapse": 0.10, "antiselective_claims": 0.10,
}


def render() -> None:
    st.header("Sensitivity (stochastic)")
    st.caption("Draw the sensitivity factors randomly each simulation, re-solving rerates to "
               "the same lifetime-LR target, and see the spread of IRRs per state.")

    st.subheader("Factor distributions — Normal(mean, std dev)")
    specs = {}
    cols = st.columns(5)
    for i, f in enumerate(FACTORS):
        with cols[i]:
            st.markdown(f"**{_LABELS[f]}**")
            mean = st.number_input("mean", value=1.00, step=0.01, format="%.2f", key=f"m_{f}")
            std = st.number_input("std", value=float(_DEFAULT_STD[f]), step=0.01,
                                  format="%.2f", key=f"s_{f}")
            specs[f] = (mean, std)

    c = st.columns(4)
    n_sims = int(c[0].number_input("Simulations", value=100, min_value=10, max_value=2000,
                                   step=10, key="sens_nsims"))
    ci_lo = c[1].number_input("CI low %", value=5.0, step=1.0, key="sens_ci_lo")
    ci_hi = c[2].number_input("CI high %", value=95.0, step=1.0, key="sens_ci_hi")
    seed = int(c[3].number_input("Seed", value=0, step=1, key="sens_seed"))

    states = available_states()
    scope = st.radio("State scope", ["All states (combined book)", "Select states"], index=0,
                     key="sens_scope")
    selected = ["All"] if scope.startswith("All") else st.multiselect(
        "States", states, default=[s for s in states if s != "All"][:3], key="sens_states")
    if not selected:
        selected = ["All"]

    st.caption(f"≈ {n_sims} sims × {len(selected)} state(s). Large N is heavier in-browser.")
    if st.button("Run stochastic analysis", type="primary", key="sens_run"):
        st.session_state.sens_job = {
            "states": list(selected), "i": 0, "results": {},
            "specs": specs, "n_sims": n_sims, "ci": (ci_lo, ci_hi), "seed": seed,
        }
        st.session_state.sens_results = None
        st.rerun()

    # one state per rerun so the bar repaints
    job = st.session_state.get("sens_job")
    if job:
        states_j = job["states"]
        total = len(states_j)
        i = job["i"]
        st.progress(i / total, text=f"Simulating {states_j[i]} ({i + 1}/{total})…")
        asm = get_assumptions()
        cells = normalize_weights(get_cells())
        rng = np.random.default_rng(job["seed"] + i)
        job["results"][states_j[i]] = simulate_state(
            cells, asm, states_j[i], job["specs"], job["n_sims"], job["ci"], rng,
            get_formulas())
        job["i"] = i + 1
        if job["i"] < total:
            st.rerun()
        st.session_state.sens_results = job["results"]
        st.session_state.sens_job = None
        st.success("Stochastic analysis complete.")

    results = st.session_state.get("sens_results")
    if results:
        _show_results(results)


def _show_results(results: dict) -> None:
    st.subheader("IRR distribution by state")
    rows = []
    for state, s in results.items():
        lo, hi = s["ci"]
        rows.append({
            "State": state,
            "IRR mean": round(s["irr_mean"], 4),
            "IRR median": round(s["irr_median"], 4),
            f"IRR p{lo:g}": round(s["irr_lo"], 4),
            f"IRR p{hi:g}": round(s["irr_hi"], 4),
            "P(target met)": round(s["pct_target_met"], 3),
            "Sims": s["n"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    state = st.selectbox("Histogram for state", list(results.keys()), key="sens_hist_state")
    irrs = np.array([x for x in results[state]["irrs"] if x == x])  # drop nan
    if len(irrs):
        counts, edges = np.histogram(irrs, bins=20)
        centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
        hist = pd.DataFrame({"IRR": centers, "count": counts})
        chart = alt.Chart(hist).mark_bar().encode(
            x=alt.X("IRR:Q", axis=alt.Axis(format="%"), title="IRR"),
            y=alt.Y("count:Q", title="Simulations"))
        st.altair_chart(chart, use_container_width=True)
        st.caption(f"{len(irrs)} simulations with a finite IRR.")
    else:
        st.info("No finite IRRs in the draws (try different distributions).")
