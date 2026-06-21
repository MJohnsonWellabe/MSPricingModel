"""Streamlit session-state helpers.

The authoritative model lives in session_state: an AssumptionSet, a FormulaSet,
and the run configuration. We (de)serialise to dict for download/upload — both an
assumptions-only JSON and a full-model JSON (assumptions + sensitivities + run
config + formulas) that reproduces results exactly.
"""
from __future__ import annotations

import copy
import io
import json

import streamlit as st

from medigap_engine.engine.formulas import default_formula_set
from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.io.excel_export import assumptions_to_xlsx_bytes
from medigap_engine.io.excel_import import assumptions_from_workbook
from medigap_engine.io.model_io import model_from_dict, model_to_dict
from medigap_engine.io.serialize import assumptions_from_dict, assumptions_to_dict
from medigap_engine.models.config import RunConfig


def init_state() -> None:
    if "assumptions" not in st.session_state:
        st.session_state.assumptions = copy.deepcopy(default_assumptions())
    if "formulas" not in st.session_state:
        st.session_state.formulas = default_formula_set()
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


def get_formulas():
    if "formulas" not in st.session_state:
        st.session_state.formulas = default_formula_set()
    return st.session_state.formulas


def set_formulas(f) -> None:
    st.session_state.formulas = f


def reset_formulas() -> None:
    st.session_state.formulas = default_formula_set()


def get_run_config() -> RunConfig:
    return st.session_state.get("run_config") or RunConfig(states=["All"])


def assumptions_json() -> str:
    return json.dumps(assumptions_to_dict(st.session_state.assumptions), indent=1)


def load_assumptions_json(text: str) -> None:
    st.session_state.assumptions = assumptions_from_dict(json.loads(text))


def assumptions_xlsx() -> bytes:
    """Current assumptions as a multi-sheet Excel workbook (for download)."""
    return assumptions_to_xlsx_bytes(st.session_state.assumptions)


def load_assumptions_xlsx(data: bytes) -> None:
    """Load assumptions from an uploaded Excel workbook (as produced by the export)."""
    doc = assumptions_from_workbook(io.BytesIO(data))
    st.session_state.assumptions = assumptions_from_dict(doc)


def model_json() -> str:
    cfg = get_run_config()
    doc = model_to_dict(st.session_state.assumptions, cfg.sensitivities, cfg,
                        get_formulas())
    return json.dumps(doc, indent=1)


def load_model_json(text: str) -> None:
    out = model_from_dict(json.loads(text))
    st.session_state.assumptions = out["assumptions"]
    st.session_state.formulas = out["formulas"]
    st.session_state.run_config = out["config"]
