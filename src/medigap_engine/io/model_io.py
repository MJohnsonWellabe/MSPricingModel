"""Full model document (de)serialization.

A *model* is everything needed to reproduce a run exactly: the assumptions, the
sensitivity set, the run configuration (state scope + solve toggle), and the
formula set. Pricing cells are derived from the distribution assumptions, so they
need not be stored. One JSON exported here can be imported by another user to get
identical results.
"""
from __future__ import annotations

from ..engine.formulas import default_formula_set
from ..models.config import RunConfig
from ..models.formulas import FormulaSet
from ..models.sensitivities import SensitivitySet
from .defaults import default_assumptions
from .serialize import (
    assumptions_from_dict,
    assumptions_to_dict,
    formulas_from_list,
    formulas_to_list,
)

MODEL_SCHEMA_VERSION = "1"

_SENS_FIELDS = (
    "morbidity_scale", "termination_scale", "rerate_effectiveness",
    "antiselective_lapse", "antiselective_claims",
)


def model_to_dict(asm, sensitivities: SensitivitySet, config: RunConfig,
                  formulas: FormulaSet) -> dict:
    return {
        "model_schema_version": MODEL_SCHEMA_VERSION,
        "assumptions": assumptions_to_dict(asm),
        "sensitivities": {f: getattr(sensitivities, f) for f in _SENS_FIELDS},
        "run_config": {
            "states": list(config.states),
            "solve_rerates": bool(config.solve_rerates),
            "use_experience_study": bool(config.use_experience_study),
        },
        "formulas": formulas_to_list(formulas),
    }


def model_from_dict(d: dict) -> dict:
    """Return {assumptions, sensitivities, config, formulas}. Missing blocks fall
    back to defaults so partial / assumptions-only documents still load."""
    asm = (assumptions_from_dict(d["assumptions"]) if "assumptions" in d
           else assumptions_from_dict(d))  # tolerate a bare assumptions document
    s = d.get("sensitivities", {})
    sensitivities = SensitivitySet(**{f: float(s[f]) for f in _SENS_FIELDS if f in s})
    rc = d.get("run_config", {})
    config = RunConfig(
        states=list(rc.get("states", ["All"])),
        solve_rerates=bool(rc.get("solve_rerates", True)),
        use_experience_study=bool(rc.get("use_experience_study", False)),
        sensitivities=sensitivities,
    )
    formulas = (formulas_from_list(d["formulas"]) if d.get("formulas")
                else default_formula_set())
    return {"assumptions": asm, "sensitivities": sensitivities,
            "config": config, "formulas": formulas}


def default_model() -> dict:
    return {
        "assumptions": default_assumptions(),
        "sensitivities": SensitivitySet(),
        "config": RunConfig(states=["All"]),
        "formulas": default_formula_set(),
    }
