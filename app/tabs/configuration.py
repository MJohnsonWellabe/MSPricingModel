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
            value=False, key="cfg_use_study",
            help="When on, assumptions ported from the Experience Study tab are used.",
        )
        solve = st.toggle(
            "Solve rerates to target lifetime loss ratio",
            value=True, key="cfg_solve",
            help="When off, the specified rerate schedule on the Assumptions tab is used.",
        )

    with col2:
        states = available_states()
        scope = st.radio("State scope", ["All states (combined book)", "Select states"],
                         index=0, key="cfg_scope")
        if scope.startswith("All"):
            selected = ["All"]
        else:
            # "All" remains selectable alongside individual states
            selected = st.multiselect(
                "States", states,
                default=[s for s in states if s != "All"][:3], key="cfg_states",
            )
            if not selected:
                selected = ["All"]

    st.subheader("Sensitivities")
    st.caption("All default to no-op (1.00). Adjust to stress the model.")
    c = st.columns(5)
    morb = c[0].number_input("Morbidity scale (cc ×)", value=1.00, step=0.05, format="%.2f",
                             key="cfg_morb")
    term = c[1].number_input("Termination scale (wx ×)", value=1.00, step=0.05, format="%.2f",
                             key="cfg_term")
    reff = c[2].number_input("Rerate effectiveness (×)", value=1.00, step=0.05, format="%.2f",
                             key="cfg_reff")
    alap = c[3].number_input("Antiselective lapse (×)", value=1.00, step=0.05, format="%.2f",
                             key="cfg_alap")
    aclm = c[4].number_input("Antiselective claims (×)", value=1.00, step=0.05, format="%.2f",
                             key="cfg_aclm")

    sens = SensitivitySet(
        morbidity_scale=morb, termination_scale=term, rerate_effectiveness=reff,
        antiselective_lapse=alap, antiselective_claims=aclm,
    )

    st.session_state.run_config = RunConfig(
        states=selected, use_experience_study=use_study,
        sensitivities=sens, solve_rerates=solve,
    )

    st.divider()
    if st.button("Run model", type="primary", key="cfg_run"):
        st.session_state.run_requested = True
        st.success(
            f"Configured to run {len(selected)} state(s). "
            "Open the **Calculation** tab to execute."
        )
    st.caption("After clicking Run, go to the Calculation tab to compute results.")

    st.divider()
    st.subheader("Full model export / import")
    st.caption(
        "Download a single JSON capturing the **entire model** — assumptions, "
        "sensitivities, state scope, solve toggle, and formulas. Another user who "
        "imports it will reproduce your results exactly."
    )
    from app.state import assumptions_xlsx, load_model_json, model_json
    mc = st.columns([1, 1, 2])
    mc[0].download_button("Download full model (JSON)", model_json(),
                          "medigap_model.json", "application/json", key="cfg_model_download")
    mc[1].download_button(
        "Download assumptions (Excel)", assumptions_xlsx(), "assumptions.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="cfg_xlsx_download",
        help="All assumptions plus the engine's derived factors, one sheet per "
        "category — for verifying the model in Excel.")
    up = mc[2].file_uploader("Import full model JSON", type=["json"], key="model_upload")
    if up is not None:
        try:
            load_model_json(up.getvalue().decode("utf-8"))
            st.success("Model imported — assumptions, sensitivities, scope, and formulas "
                       "loaded. Re-run on the Calculation tab to reproduce results.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not import model: {exc}")
