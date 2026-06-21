"""Configuration tab: experience-study toggle, state selection, sensitivities,
and the Run button."""
from __future__ import annotations

import streamlit as st

from medigap_engine.io.defaults import available_states
from medigap_engine.models.config import RunConfig
from medigap_engine.models.sensitivities import SensitivitySet


def render() -> None:
    st.header("Configuration")

    col1, col2 = st.columns(2)
    with col1:
        use_study = st.toggle(
            "Use experience study assumptions",
            value=False,
            help="When on, assumptions ported from the Experience Study tab are used.",
        )
        solve = st.toggle(
            "Solve rerates to target lifetime loss ratio",
            value=True,
            help="When off, the specified rerate schedule on the Assumptions tab is used.",
        )

    with col2:
        states = available_states()
        scope = st.radio("State scope", ["All states (combined book)", "Select states"],
                         index=0)
        if scope.startswith("All"):
            selected = ["All"]
        else:
            selected = st.multiselect(
                "States", [s for s in states if s != "All"],
                default=[s for s in states if s != "All"][:3],
            )
            if not selected:
                selected = ["All"]

    st.subheader("Sensitivities")
    st.caption("All default to no-op (1.00). Adjust to stress the model.")
    c = st.columns(5)
    morb = c[0].number_input("Morbidity scale (cc ×)", value=1.00, step=0.05, format="%.2f")
    term = c[1].number_input("Termination scale (wx ×)", value=1.00, step=0.05, format="%.2f")
    reff = c[2].number_input("Rerate effectiveness (×)", value=1.00, step=0.05, format="%.2f")
    alap = c[3].number_input("Antiselective lapse (×)", value=1.00, step=0.05, format="%.2f")
    aclm = c[4].number_input("Antiselective claims (×)", value=1.00, step=0.05, format="%.2f")

    sens = SensitivitySet(
        morbidity_scale=morb, termination_scale=term, rerate_effectiveness=reff,
        antiselective_lapse=alap, antiselective_claims=aclm,
    )

    st.session_state.run_config = RunConfig(
        states=selected, use_experience_study=use_study,
        sensitivities=sens, solve_rerates=solve,
    )

    st.divider()
    if st.button("Run model", type="primary"):
        st.session_state.run_requested = True
        st.success(
            f"Configured to run {len(selected)} state(s). "
            "Open the **Calculation** tab to execute."
        )
    st.caption("After clicking Run, go to the Calculation tab to compute results.")
