"""Streamlit session-state helpers.

The authoritative assumptions live in session_state as an AssumptionSet; we
(de)serialise to dict for download/upload.
"""
from __future__ import annotations

import copy

import streamlit as st

from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.io.serialize import assumptions_from_dict, assumptions_to_dict


def init_state() -> None:
    if "assumptions" not in st.session_state:
        st.session_state.assumptions = copy.deepcopy(default_assumptions())
    if "run_result" not in st.session_state:
        st.session_state.run_result = None
    if "diagnostics" not in st.session_state:
        st.session_state.diagnostics = None


def get_cells():
    """Cells are derived from the current assumptions' distribution factors."""
    return list(build_cells(st.session_state.assumptions))


def get_assumptions():
    return st.session_state.assumptions


def set_assumptions(a) -> None:
    st.session_state.assumptions = a


def reset_assumptions() -> None:
    st.session_state.assumptions = copy.deepcopy(default_assumptions())


def assumptions_json() -> str:
    import json
    return json.dumps(assumptions_to_dict(st.session_state.assumptions), indent=1)


def load_assumptions_json(text: str) -> None:
    import json
    st.session_state.assumptions = assumptions_from_dict(json.loads(text))
