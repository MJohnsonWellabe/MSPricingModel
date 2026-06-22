"""Sensitivity tab: stochastic IRR ranges, pre-tax-income ranges and scenario drill-down.

Each simulation draws the 5 sensitivity factors from Normal(mean, std), re-solves
rerates (same lifetime target) and projects. Two modes:
- **Per state** — the distribution of each state's own IRR (equal book per state).
- **Portfolio (pooled per-state)** — each draw prices every state with its own factors and
  pools the cashflows into one portfolio IRR, so the distribution centres on the
  deterministic combined IRR (premium-weighted), resolving the per-state vs pooled gap.
"""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.state import get_assumptions, get_cells, get_formulas
from medigap_engine.engine.run import normalize_weights
from medigap_engine.engine.sensitivity import (
    FACTORS,
    project_scenario,
    simulate_portfolio,
    simulate_state,
)
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
# income-statement lines shown when drilling into a scenario, in presentation order
_INCOME_ROWS = [
    ("lives", "Lives"), ("earned_prem", "Earned premium"), ("nii", "Net investment income"),
    ("claims", "Claims"), ("commission", "Commission"), ("premium_tax", "Premium tax"),
    ("oper_acq", "Operating acquisition"), ("marketing", "Marketing acquisition"),
    ("maintenance", "Maintenance"), ("pretax_income", "Pre-tax income"), ("tax", "Tax"),
    ("at_income", "After-tax income"), ("rbc", "RBC"), ("ah_cashflow", "Distributable cashflow"),
]


def render() -> None:
    st.header("Sensitivity (stochastic)")
    st.caption("Draw the sensitivity factors randomly each simulation, re-solving rerates to "
               "the same lifetime-LR target, and see the spread of IRRs and cash flows.")

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

    states = [s for s in available_states() if s != "All"]
    mode = st.radio(
        "Mode", ["Per state", "Portfolio (pooled per-state)"], index=0, key="sens_mode",
        help="Per state: each state's own IRR distribution. Portfolio: pool every state's "
             "cashflows per draw into one IRR — its centre matches the deterministic "
             "combined run (the 'All states' national approximation reads higher because it "
             "ignores the per-state morbidity/premium/commission loadings).")
    if mode == "Per state":
        scope = st.radio("State scope", ["National (All)", "Select states"], index=0,
                         key="sens_scope")
        selected = ["All"] if scope.startswith("National") else st.multiselect(
            "States", states, default=states[:3], key="sens_states")
    else:
        selected = st.multiselect("States in portfolio", states, default=states,
                                  key="sens_port_states")
    if not selected:
        selected = ["All"]

    pool = mode != "Per state"
    n_states = len(selected)
    st.caption(f"≈ {n_sims} sims" + (f" × {n_states} states pooled per draw" if pool
               else f" × {n_states} state(s)") + ". Portfolio mode is the heaviest.")
    if st.button("Run stochastic analysis", type="primary", key="sens_run"):
        st.session_state.sens_job = {
            "mode": mode, "states": list(selected), "i": 0, "results": {},
            "specs": specs, "n_sims": n_sims, "ci": (ci_lo, ci_hi), "seed": seed,
        }
        st.session_state.sens_results = None
        st.rerun()

    _run_job()

    results = st.session_state.get("sens_results")
    if results:
        _show_results(results)


def _run_job() -> None:
    job = st.session_state.get("sens_job")
    if not job:
        return
    asm = get_assumptions()
    cells = normalize_weights(get_cells())
    if job["mode"] != "Per state":
        # portfolio: pool all states per draw, one heavy computation
        with st.spinner(f"Pooling {len(job['states'])} states × {job['n_sims']} sims…"):
            rng = np.random.default_rng(job["seed"])
            summary = simulate_portfolio(cells, asm, job["states"], job["specs"],
                                         job["n_sims"], job["ci"], rng, get_formulas())
            summary["states"] = job["states"]
            st.session_state.sens_results = {"Portfolio": summary}
        st.session_state.sens_job = None
        st.success("Portfolio stochastic analysis complete.")
        return
    # per-state: one state per rerun so the progress bar repaints
    states_j = job["states"]
    total = len(states_j)
    i = job["i"]
    st.progress(i / total, text=f"Simulating {states_j[i]} ({i + 1}/{total})…")
    rng = np.random.default_rng(job["seed"] + i)
    summary = simulate_state(cells, asm, states_j[i], job["specs"], job["n_sims"],
                             job["ci"], rng, get_formulas())
    summary["states"] = [states_j[i]]
    job["results"][states_j[i]] = summary
    job["i"] = i + 1
    if job["i"] < total:
        st.rerun()
    st.session_state.sens_results = job["results"]
    st.session_state.sens_job = None
    st.success("Stochastic analysis complete.")


def _show_results(results: dict) -> None:
    st.subheader("IRR distribution")
    rows = []
    for label, s in results.items():
        lo, hi = s["ci"]
        rows.append({
            "Scope": label,
            "IRR mean": round(s["irr_mean"], 4),
            "IRR median": round(s["irr_median"], 4),
            f"IRR p{lo:g}": round(s["irr_lo"], 4),
            f"IRR p{hi:g}": round(s["irr_hi"], 4),
            "P(target met)": round(s["pct_target_met"], 3),
            "Sims": s["n"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if "Portfolio" in results:
        st.caption("Portfolio IRR is the pooled, premium-weighted distribution — its centre "
                   "matches the deterministic combined-book run on the Output tab.")

    label = st.selectbox("Drill into", list(results.keys()), key="sens_drill")
    s = results[label]

    irrs = np.array([x for x in s["irrs"] if x == x])  # drop nan
    if len(irrs):
        counts, edges = np.histogram(irrs, bins=20)
        centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
        chart = alt.Chart(pd.DataFrame({"IRR": centers, "count": counts})).mark_bar().encode(
            x=alt.X("IRR:Q", axis=alt.Axis(format="%"), title="IRR"),
            y=alt.Y("count:Q", title="Simulations"))
        st.altair_chart(chart, use_container_width=True)

    # pre-tax income range by year (P-lo / expected / P-hi)
    if s.get("pti_mean"):
        lo, hi = s["ci"]
        yrs = list(range(1, len(s["pti_mean"]) + 1))
        pti = pd.DataFrame({"Year": yrs, f"P{lo:g}": s["pti_lo"],
                            "Expected": s["pti_mean"], f"P{hi:g}": s["pti_hi"]})
        st.markdown("**Pre-tax income by year** (per policy issued)")
        band = alt.Chart(pti).mark_area(opacity=0.25).encode(
            x="Year:Q", y=alt.Y(f"P{lo:g}:Q", title="Pre-tax income"), y2=f"P{hi:g}:Q")
        line = alt.Chart(pti).mark_line().encode(x="Year:Q", y="Expected:Q")
        st.altair_chart(band + line, use_container_width=True)
        st.dataframe(pti.set_index("Year").T.style.format("{:,.2f}"),
                     use_container_width=True)

    _scenario_income_statement(label, s)


def _scenario_income_statement(label: str, s: dict) -> None:
    """Pick a scenario (by IRR percentile) and re-project its full income statement."""
    vecs = s.get("sens_vecs")
    if not vecs:
        return
    st.markdown("**Scenario income statement** — re-project a single draw")
    irrs = np.array(s["irrs"], dtype=float)
    finite = np.where(np.isfinite(irrs))[0]
    if not len(finite):
        return
    order = finite[np.argsort(irrs[finite])]
    choice = st.radio("Scenario", ["Worst (P5 IRR)", "Median IRR", "Best (P95 IRR)"],
                      horizontal=True, key=f"sens_scen_{label}")
    pick = {"Worst (P5 IRR)": 0.05, "Median IRR": 0.5, "Best (P95 IRR)": 0.95}[choice]
    idx = int(order[min(len(order) - 1, int(round(pick * (len(order) - 1))))])
    vec = vecs[idx]
    st.caption("Drawn factors: " + ", ".join(f"{_LABELS[f].rstrip(' ×')} {vec[f]:.3f}"
                                             for f in FACTORS) + f"  |  IRR {irrs[idx]:.2%}")
    cells = normalize_weights(get_cells())
    series = project_scenario(cells, get_assumptions(), s.get("states", [label]), vec,
                              get_formulas())
    if not series:
        return
    data = {lbl: series[key] for key, lbl in _INCOME_ROWS if key in series}
    df = pd.DataFrame(data).T
    df.columns = [f"Yr {i}" for i in range(1, len(df.columns) + 1)]
    st.table(df.style.format("{:,.2f}"))
