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

    tabs = st.tabs([
        "Configuration",
        "Experience Study",
        "Assumptions",
        "Calculation",
        "Output",
        "Sensitivity",
        "Documentation",
    ])
    with tabs[0]:
        t_configuration.render()
    with tabs[1]:
        t_experience.render()
    with tabs[2]:
        t_assumptions.render()
    with tabs[3]:
        t_calculation.render()
    with tabs[4]:
        t_output.render()
    with tabs[5]:
        t_sensitivity.render()
    with tabs[6]:
        t_documentation.render()


if __name__ == "__main__":
    main()
