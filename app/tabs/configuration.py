"""Configuration tab: experience-study toggle, state selection, sensitivities,
and the Run button."""
from __future__ import annotations

import math

import streamlit as st

from app.state import get_assumptions, get_cells, get_formulas, solve_toggle
from medigap_engine.engine.aggregate import aggregate_cells, aggregate_states
from medigap_engine.engine.forward_solver import solve_rerates
from medigap_engine.engine.project import project_cell
from medigap_engine.engine.run import _state_cells, normalize_weights, run_state
from medigap_engine.io.defaults import available_states
from medigap_engine.models.config import RunConfig
from medigap_engine.models.results import RunResult
from medigap_engine.models.sensitivities import SensitivitySet


def _store_state(job: dict, asm, state: str, res, info: dict) -> None:
    """Attach a finished state result + diagnostics to the job (mirrors run_state's tail)."""
    floor = asm.rerates.in_year_lr_floor
    info["in_year_lr_floor_breaches"] = [
        i + 1 for i, lr in enumerate(res.series["in_year_lr"]) if 0 < lr < floor - 1e-6]
    info.setdefault("achieved_lifetime_lr", res.lifetime_lr)
    job["by_state"][state] = res
    job["diag"][state] = info


def _finalize(job: dict, asm) -> None:
    by_state = job["by_state"]
    combined = (aggregate_states(by_state, asm) if len(by_state) > 1
                else next(iter(by_state.values()), None))
    st.session_state.run_result = RunResult(by_state=by_state, all_states=combined)
    st.session_state.diagnostics = job["diag"]
    st.session_state.calc_job = None
    st.session_state.active_tab = "Output"
    st.rerun()


def _process_run_job() -> None:
    """Advance the run job one chunk per Streamlit rerun so the progress bar repaints
    (a single synchronous loop never repaints under stlite). A single-state run (e.g. the
    combined 'All' book) is chunked by cell batches for a live cell-level bar; multi-state
    runs advance one state per rerun. On completion, store the result and open Output."""
    job = st.session_state.get("calc_job")
    if not job:
        return
    states = job["states"]
    nst = len(states)
    asm = get_assumptions()
    if job["si"] >= nst:
        _finalize(job, asm)
        return
    state = states[job["si"]]
    cells_all = normalize_weights(get_cells())

    if nst > 1:
        # multi-state: one state per rerun (the per-state tick already shows movement)
        st.progress(job["si"] / nst, text=f"Pricing {state} ({job['si'] + 1}/{nst})…")
        res, info = run_state(state, cells_all, asm, job["config"], get_formulas())
        job["by_state"][state] = res
        job["diag"][state] = info
        job["si"] += 1
        st.rerun()

    # single state: solve once, then project cells in batches with a live bar
    cfg = job["config"]
    work = job.get("work")
    if work is None:
        scells = _state_cells(state, cells_all, asm)
        if cfg.solve_rerates and asm.rerates.solve:
            rerates, info = solve_rerates(scells, asm, cfg.sensitivities, state,
                                          formulas=get_formulas())
        else:
            rerates = list(asm.rerates.rerates_for(state))
            info = {"status": "specified", "rerates": rerates}
        job["work"] = {"cells": scells, "rerates": rerates, "info": info, "results": [], "ci": 0}
        st.progress(0.02, text=f"Solving rerates for {state}…")
        st.rerun()

    ncells = len(work["cells"])
    batch_size = max(24, math.ceil(ncells / 18))
    ci = work["ci"]
    for c in work["cells"][ci:ci + batch_size]:
        work["results"].append(
            project_cell(c, asm, cfg.sensitivities, state, work["rerates"], get_formulas()))
    work["ci"] = min(ci + batch_size, ncells)
    st.progress(min(0.99, work["ci"] / ncells),
                text=f"Pricing {state} — cell {work['ci']}/{ncells}…")
    if work["ci"] < ncells:
        st.rerun()
    res = aggregate_cells(state, work["results"], asm)
    _store_state(job, asm, state, res, work["info"])
    job["si"] += 1
    job["work"] = None
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
        individual = [s for s in states if s != "All"]
        scope_opts = ["All states (combined book)",
                      "All states individually (run each of the ~%d)" % len(individual),
                      "Select states"]
        # persist the scope across the session-state nav
        scope_default = st.session_state.get("cfg_scope_sel", scope_opts[0])
        scope = st.radio("State scope", scope_opts,
                         index=scope_opts.index(scope_default) if scope_default in scope_opts else 0,
                         key="cfg_scope")
        st.session_state.cfg_scope_sel = scope
        if scope.startswith("All states (combined"):
            selected = ["All"]
        elif scope.startswith("All states individually"):
            selected = list(individual)
        else:
            # persist the multiselect across nav (the nav re-renders this tab fresh)
            prev = [s for s in st.session_state.get("cfg_states_sel", individual[:3]) if s in states]
            selected = st.multiselect("States", states, default=prev or individual[:3],
                                      key="cfg_states")
            st.session_state.cfg_states_sel = selected
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
            "states": list(selected), "si": 0, "work": None, "by_state": {}, "diag": {},
            "config": st.session_state.run_config,
        }
        st.session_state.run_result = None
        st.rerun()
    # Advance one chunk per rerun so the progress bar repaints (a single synchronous loop
    # never repaints under stlite). On completion, jump to Output.
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
