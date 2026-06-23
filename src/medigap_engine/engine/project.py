"""Per-cell 30-year pricing projection.

The per-duration line items are computed from an editable :class:`FormulaSet`
(see ``models/formulas`` and ``engine/formulas``); this module resolves the
lookup namespace each duration and evaluates the formulas. Defaults reproduce the
workbook ``Model`` tab. Compounding columns (rerate G, aging-rerate H, trend O,
antiselection P, lives) depend on the prior duration, so it is a sequential loop.
"""
from __future__ import annotations

from typing import Optional

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from ..models.cell import PricingCell
from ..models.formulas import FormulaSet
from ..models.results import CellProjection, CellResult
from ..models.sensitivities import SensitivitySet
from . import lookups as L
from .formulas import compile_steps, default_formula_set, eval_steps
from .metrics import irr, npv

# series stored on the projection -> the namespace variable that fills it
_SERIES_FROM_NS = {
    "lives": "lives_d", "lapse": "lapse_d", "mortality": "mort_d",
    "total_term": "term_d", "rerate_used": "rate_d", "total_rerate": "total_rerate",
    "earned_prem": "earned_prem", "ibnr": "ibnr", "nii": "nii",
    "base_cc": "base_cc_eff", "selection": "selection", "trend": "O_d",
    "antiselection": "P_d", "claims": "claims", "commission": "commission",
    "premium_tax": "premium_tax", "oper_acq": "oper_acq", "marketing": "marketing",
    "maintenance": "maintenance", "pretax_income": "pretax", "tax": "tax",
    "at_income": "at_income", "rbc": "rbc", "int_on_rbc": "int_on_rbc",
    "tax_on_int": "tax_on_int", "ah_cashflow": "ah",
}


def project_cell(
    cell: PricingCell,
    asm: AssumptionSet,
    sens: SensitivitySet,
    state: str,
    rerates: list[float],
    formulas: Optional[FormulaSet] = None,
) -> CellResult:
    """Project a single pricing cell.

    ``rerates`` is the recommended rerate % by duration (length 30). The achieved
    rerate is scaled by ``sens.rerate_effectiveness``.
    """
    key = cell.key
    n = PROJECTION_YEARS
    o = asm.other
    _, full = compile_steps(formulas or default_formula_set())

    base_prem = L.premium_for_cell(asm, key, state)
    state_cc_factor = morb_state(asm, state)
    lapse_state_factor = asm.termination.state_factors.get(state, 1.0)
    eff = sens.rerate_effectiveness
    rerate_used = [rerates[i] * eff for i in range(n)]
    yr1_prem = base_prem * (1.0 + rerate_used[0])

    # constant part of the namespace (same every duration)
    const = {
        "base_prem": base_prem, "state_cc": state_cc_factor, "yr1_prem": yr1_prem,
        "is_gi": key.uw_class == "GI",
        "comm_age_mult": 0.5 if (asm.commission.age80_halving and key.issue_age >= 80) else 1.0,
        "planf_offset_d": asm.commission.plan_f_offset if key.plan == "F" else 0.0,
        "gi_flat": asm.commission.gi_flat,
        "morbidity_scale": sens.morbidity_scale,
        "termination_scale": sens.termination_scale,
        "antiselective_lapse": sens.antiselective_lapse,
        "antiselective_claims": sens.antiselective_claims,
        "lam_lapse": asm.rerates.antiselection_lambda_lapse,
        "lam_claims": asm.rerates.antiselection_lambda_claims,
        "ibnr_pct": o.ibnr_pct, "nier": o.nier, "premium_tax_rate": o.premium_tax,
        "tax_rate": o.tax_rate, "oper_acq_amt": o.oper_acq,
        "marketing_amt": o.marketing_acq, "maintenance_amt": o.maintenance,
        "inflation": o.inflation, "rbc_pct": o.rbc_pct_of_prem,
        "rbc_factor": o.rbc_factor, "covariance": o.covariance,
    }

    S = {k: [0.0] * n for k in (*_SERIES_FROM_NS, "in_year_lr", "lifetime_lr")}

    lives_prev = 1.0
    G_prev = H_prev = O_prev = P_prev = 1.0
    ibnr_prev = rbc_prev = 0.0
    cum_claims = cum_prem = 0.0

    for i in range(n):
        d = i + 1
        attained = key.issue_age + d - 1
        trend_d = L.trend_year(asm, d)
        ns = dict(const)
        ns.update(
            d=d, rate_d=rerate_used[i], trend_d=trend_d,
            trend_step=0.0 if d == 1 else trend_d,
            dur_scale=(1.0 if d == 1 else asm.termination.dur2_scaling if d == 2
                       else asm.termination.dur3plus_scaling),
            acq_active=1.0 if d == 1 else 0.0,
            first_year=1.0 if d == 1 else 0.0,
            aging_p=L.cc_aging_duration(asm, d),
            # claims base cost is by ISSUE age (constant across duration), matching the
            # workbook Output/Aggregate; mortality & aging-rerate stay attained-age
            base_cc=L.base_claim_cost(asm, key.gender, key.issue_age, key.plan, state)
            * L.claim_class_factors(asm, key.uw_class, key.preferred, key.hhd, state),
            selection=L.selection_factor(asm, key.issue_age, key.uw_class, d),
            lapse_base=L.lapse_rate(asm, key.uw_class, d) * lapse_state_factor,
            mort_d=asm.termination.mortality(attained),
            aging_h=L.aging_rerate(asm, attained) if d >= 2 else 0.0,
            comm_rate=asm.commission.rate(state, d, key.plan),
            lives_prev=lives_prev, G_prev=G_prev, H_prev=H_prev,
            O_prev=O_prev, P_prev=P_prev, ibnr_prev=ibnr_prev, rbc_prev=rbc_prev,
        )
        eval_steps(full, ns)

        for series_name, ns_name in _SERIES_FROM_NS.items():
            S[series_name][i] = float(ns[ns_name])
        earned = S["earned_prem"][i]
        claims = S["claims"][i]
        df = 1.0 / (1.0 + o.discount_rate) ** (i + 1)   # NPV-discounted lifetime LR
        cum_claims += claims * df
        cum_prem += earned * df
        S["in_year_lr"][i] = claims / earned if earned else 0.0   # per-year ratio, undiscounted
        S["lifetime_lr"][i] = cum_claims / cum_prem if cum_prem else 0.0

        lives_prev = ns["lives_d"]
        G_prev, H_prev, O_prev, P_prev = ns["G_d"], ns["H_d"], ns["O_d"], ns["P_d"]
        ibnr_prev, rbc_prev = ns["ibnr"], ns["rbc"]

    proj = CellProjection(series=S)
    return CellResult(
        key=key, weight=cell.weight, projection=proj,
        irr=irr(S["ah_cashflow"]), lifetime_lr=S["lifetime_lr"][-1],
        npv_pretax=npv(o.discount_rate, S["pretax_income"]),
    )


def morb_state(asm: AssumptionSet, state: str) -> float:
    sf = asm.morbidity.state_factors
    return sf.get(state, sf.get("All", 1.0))
