"""Configuration tab: experience-study toggle, state selection, sensitivities,
and the Run button."""
from __future__ import annotations

import streamlit as st

from app.state import get_assumptions, get_cells, get_formulas, solve_toggle
from medigap_engine.engine.aggregate import aggregate_states
from medigap_engine.engine.run import normalize_weights, run_state
from medigap_engine.io.defaults import available_states
from medigap_engine.models.config import RunConfig
from medigap_engine.models.results import RunResult
from medigap_engine.models.sensitivities import SensitivitySet


def _process_run_job() -> None:
    """Advance the per-state run job by one state per Streamlit rerun, repainting the
    progress bar between states. When the last state finishes, store the result and
    switch the active tab to Output."""
    job = st.session_state.get("calc_job")
    if not job:
        return
    states = job["states"]
    total = len(states)
    i = job["i"]
    st.progress(i / total, text=f"Pricing {states[i]} ({i + 1}/{total})…")
    asm = get_assumptions()
    cells = normalize_weights(get_cells())
    st_res, info = run_state(states[i], cells, asm, job["config"], get_formulas())
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
    st.session_state.active_tab = "Output"
    st.rerun()


def render() -> None:
    st.header("Configuration")

    col1, col2 = st.columns(2)
    with col1:
        use_study = st.toggle(
            "Use experience study assumptions",
            value=False, key="cfg_use_study",
            help="When on, assumptions ported from the Experience Study tab are used.",
        )
        solve = solve_toggle(
            "cfg_solve", "Solve rerates to target lifetime loss ratio",
            help="Linked to the Assumptions->Rerates tab. When off, the specified "
            "rerate schedule on the Assumptions tab is used.",
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
        st.session_state.calc_job = {
            "states": list(selected), "i": 0, "by_state": {}, "diag": {},
            "config": st.session_state.run_config,
        }
        st.session_state.run_result = None
        st.rerun()
    # Process one state per rerun so the progress bar repaints beneath the button
    # (a single synchronous loop never repaints under stlite). On completion, jump to Output.
    _process_run_job()
    st.caption(f"Runs {len(selected)} state(s) here with a progress bar, then opens the "
               "Output tab automatically.")

    st.divider()
    st.subheader("Full model export / import")
    st.caption(
        "Download a single JSON capturing the **entire model** — assumptions, "
        "sensitivities, state scope, solve toggle, and formulas. Another user who "
        "imports it will reproduce your results exactly."
    )
    from app.state import assumptions_xlsx, load_assumptions_xlsx, load_model_json, model_json
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

    st.caption("Or upload an **assumptions Excel** workbook (as downloaded above) to "
               "load just the assumptions back.")
    xup = st.file_uploader("Upload assumptions Excel", type=["xlsx"], key="cfg_xlsx_upload")
    if xup is not None:
        try:
            load_assumptions_xlsx(xup.getvalue())
            st.success("Assumptions loaded from Excel. Re-run on the Calculation tab.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load assumptions Excel: {exc}")
