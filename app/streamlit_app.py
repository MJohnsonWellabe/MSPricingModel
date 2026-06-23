"""Medicare Supplement pricing model — Streamlit entrypoint.

Runs server-side for local development (``streamlit run app/streamlit_app.py``)
and client-side in the browser via stlite (see ``web/index.html``). All heavy
computation lives in the dependency-free ``medigap_engine`` package.
"""
from __future__ import annotations

import streamlit as st

from app.state import init_state
from app.tabs import (
    assumptions as t_assumptions,
    calculation as t_calculation,
    configuration as t_configuration,
    documentation as t_documentation,
    experience_study as t_experience,
    formulas as t_formulas,
    output as t_output,
    sensitivity as t_sensitivity,
)


def main() -> None:
    st.set_page_config(page_title="Medigap Pricing Model", layout="wide")
    init_state()

    st.title("Medicare Supplement Pricing Model")
    st.caption(
        "A from-scratch rebuild of the MS pricing workbook. Configure, set "
        "assumptions, run, and review per-state results."
    )

    # Session-state-driven nav (instead of st.tabs) so the run can auto-switch the
    # active tab — e.g. land on Output when a model run completes.
    pages = [
        ("Configuration", t_configuration),
        ("Experience Study", t_experience),
        ("Assumptions", t_assumptions),
        ("Formulas", t_formulas),
        ("Calculation", t_calculation),
        ("Output", t_output),
        ("Sensitivity", t_sensitivity),
        ("Documentation", t_documentation),
    ]
    names = [n for n, _ in pages]
    active = st.session_state.get("active_tab", names[0])
    if active not in names:
        active = names[0]

    cols = st.columns(len(pages))
    for col, name in zip(cols, names):
        kind = "primary" if name == active else "secondary"
        if col.button(name, key=f"nav_{name}", use_container_width=True, type=kind):
            st.session_state.active_tab = name
            st.rerun()
    st.divider()

    dict(pages)[active].render()



if __name__ == "__main__":
    main()
