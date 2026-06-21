"""Formula Database tab.

The per-duration projection line items are editable expressions. They are grouped
by category, edited inline, and validated (parsed + test-evaluated on a sample
namespace) before a run. Defaults reproduce the workbook math exactly.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import get_formulas, reset_formulas, set_formulas
from medigap_engine.engine.formulas import (
    default_formula_set,
    sample_namespace,
    validate_formula_set,
)
from medigap_engine.models.formulas import CATEGORIES, FormulaSet, FormulaStep

_NAMESPACE_HELP = """
**Available variables** (resolved by the engine each duration):

- *Flags / scalars*: `d`, `rate_d`, `trend_d`, `trend_step`, `dur_scale`,
  `acq_active`, `first_year`, `aging_p`, `state_cc`
- *Per-cell*: `base_prem`, `base_cc`, `selection`, `lapse_base`, `mort_d`,
  `aging_h`, `comm_rate`, `is_gi`, `comm_age_mult`, `planf_offset_d`, `yr1_prem`
- *Prior duration (carry)*: `lives_prev`, `G_prev`, `H_prev`, `O_prev`,
  `P_prev`, `ibnr_prev`, `rbc_prev`
- *Sensitivities*: `morbidity_scale`, `termination_scale`,
  `antiselective_lapse`, `antiselective_claims`
- *Assumption scalars*: `lam_lapse`, `lam_claims`, `ibnr_pct`, `nier`,
  `premium_tax_rate`, `tax_rate`, `oper_acq_amt`, `marketing_amt`,
  `maintenance_amt`, `inflation`, `rbc_pct`, `rbc_factor`, `covariance`, `gi_flat`
- *Earlier steps in this list* (e.g. `avg_lives`, `earned_prem`, `claims`)

**Allowed**: arithmetic (`+ - * / ** %`), comparisons, `a if cond else b`, and the
helpers `minimum(a,b)`, `maximum(a,b)`, `clamp(x,lo,hi)`, `where(cond,a,b)`, `abs(x)`.
No attribute access, subscripting, imports, or other function calls.
"""


def render() -> None:
    st.header("Formula Database")
    st.caption(
        "Every per-duration line item is an editable expression. The engine resolves "
        "lookups into a variable namespace and evaluates these in order; the rerate "
        "solver and the per-cell projection use the same formulas. Edit, **Validate**, "
        "then run. Loss ratio, IRR and NPV are derived metrics (computed from these "
        "line items) and are not edited here."
    )
    with st.expander("Variable & operator reference"):
        st.markdown(_NAMESPACE_HELP)

    fs = get_formulas()

    top = st.columns([1, 1, 3])
    if top[0].button("Validate formulas", type="primary", key="formulas_validate"):
        errors = validate_formula_set(fs, sample_namespace())
        if errors:
            st.error("Found problems — fix these before running:")
            st.table(pd.DataFrame(errors, columns=["Formula", "Error"]))
        else:
            st.success("All formulas parsed and evaluated cleanly on a sample namespace.")
    if top[1].button("Reset to defaults", key="formulas_reset"):
        reset_formulas()
        st.rerun()

    defaults = {s.name: s.expr for s in default_formula_set().steps}
    by_cat = fs.by_category()
    new_steps: list[FormulaStep] = []
    for cat in CATEGORIES:
        steps = by_cat.get(cat, [])
        if not steps:
            continue
        st.subheader(cat)
        df = pd.DataFrame([
            {"Variable": s.name, "Expression": s.expr,
             "Modified": "•" if s.expr != defaults.get(s.name, s.expr) else "",
             "Description": s.doc}
            for s in steps
        ])
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, key=f"fml_{cat}",
            column_config={
                "Variable": st.column_config.TextColumn(disabled=True, width="small"),
                "Expression": st.column_config.TextColumn(width="large"),
                "Modified": st.column_config.TextColumn(disabled=True, width="small"),
                "Description": st.column_config.TextColumn(disabled=True, width="large"),
            },
        )
        for s, (_, row) in zip(steps, edited.iterrows()):
            new_steps.append(FormulaStep(
                name=s.name, category=s.category,
                expr=str(row["Expression"]), doc=s.doc))

    set_formulas(FormulaSet(steps=new_steps))
