from medigap_engine.engine.formulas import (
    default_formula_set,
    sample_namespace,
    validate_formula,
    validate_formula_set,
)
from medigap_engine.engine.project import project_cell
from medigap_engine.models.formulas import FormulaStep


def test_validate_rejects_unsafe():
    assert validate_formula("__import__('os')") is not None
    assert validate_formula("asm.morbidity") is not None        # attribute access
    assert validate_formula("foo(1)") is not None               # unknown call
    assert validate_formula("[x for x in y]") is not None       # comprehension


def test_validate_accepts_arithmetic():
    assert validate_formula("a * b + minimum(c, 1.0)") is None
    assert validate_formula("where(flag, 1.0, x / (y + 1))") is None
    assert validate_formula("(1 + t) ** d") is None


def test_default_formula_set_is_valid():
    assert validate_formula_set(default_formula_set(), sample_namespace()) == []


def test_validate_formula_set_flags_broken_step():
    fs = default_formula_set()
    fs.steps.append(FormulaStep("boom", "Income", "does_not_exist + 1", ""))
    errs = validate_formula_set(fs)
    assert any(name == "boom" for name, _ in errs)


def test_editing_claims_formula_changes_projection(asm, sample_cell, base_sens):
    rerates = list(asm.rerates.specified_rerates)
    base = project_cell(sample_cell, asm, base_sens, "All", rerates)
    fs = default_formula_set()
    for s in fs.steps:
        if s.name == "claims":
            s.expr = s.expr + " * 1.25"
    edited = project_cell(sample_cell, asm, base_sens, "All", rerates, formulas=fs)
    b0 = base.projection.series["claims"][0]
    e0 = edited.projection.series["claims"][0]
    assert abs(e0 / b0 - 1.25) < 1e-9


def test_default_set_matches_builtin_projection(asm, sample_cell, base_sens):
    # passing the default formula set explicitly == the built-in default
    rerates = list(asm.rerates.specified_rerates)
    a = project_cell(sample_cell, asm, base_sens, "All", rerates)
    b = project_cell(sample_cell, asm, base_sens, "All", rerates,
                     formulas=default_formula_set())
    assert a.projection.series["claims"] == b.projection.series["claims"]
    assert a.irr == b.irr
