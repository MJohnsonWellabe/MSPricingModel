import json

from medigap_engine.engine.formulas import default_formula_set
from medigap_engine.engine.run import run
from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.io.model_io import model_from_dict, model_to_dict
from medigap_engine.io.serialize import assumptions_to_dict
from medigap_engine.models.config import RunConfig
from medigap_engine.models.sensitivities import SensitivitySet


def _doc():
    asm = default_assumptions()
    sens = SensitivitySet(morbidity_scale=1.05, rerate_effectiveness=0.95)
    config = RunConfig(states=["TX", "All"], solve_rerates=True, sensitivities=sens)
    fs = default_formula_set()
    for s in fs.steps:
        if s.name == "claims":
            s.expr = s.expr + " * 1.02"
    return asm, sens, config, fs


def test_model_round_trip():
    asm, sens, config, fs = _doc()
    d = model_to_dict(asm, sens, config, fs)
    text = json.dumps(d)              # must be JSON-serialisable
    out = model_from_dict(json.loads(text))
    assert out["config"].states == ["TX", "All"]
    assert out["config"].solve_rerates is True
    assert out["sensitivities"].morbidity_scale == 1.05
    assert out["sensitivities"].rerate_effectiveness == 0.95
    assert [s.expr for s in out["formulas"].steps] == [s.expr for s in fs.steps]


def test_export_import_reproduces_results_exactly():
    asm, sens, config, fs = _doc()
    cells = build_cells(asm)
    res1, _ = run(cells, asm, config, fs)

    # export -> import (as a fresh user would) -> run
    doc = json.loads(json.dumps(model_to_dict(asm, sens, config, fs)))
    loaded = model_from_dict(doc)
    cells2 = build_cells(loaded["assumptions"])
    res2, _ = run(cells2, loaded["assumptions"], loaded["config"], loaded["formulas"])

    for state in config.states:
        a, b = res1.by_state[state], res2.by_state[state]
        assert abs(a.irr - b.irr) < 1e-12
        assert abs(a.lifetime_lr - b.lifetime_lr) < 1e-12


def test_model_from_bare_assumptions_document():
    # a plain assumptions-only dict should still load (formulas/config default)
    out = model_from_dict(assumptions_to_dict(default_assumptions()))
    assert out["config"].states == ["All"]
    assert out["formulas"].names() == default_formula_set().names()
