"""Per-cell 30-year pricing projection.

Reproduces the workbook ``Model`` tab line-by-line. Each duration's compounding
columns (rerate G, aging-rerate H, trend O, antiselection P, lives) depend on the
prior duration, so the projection is a sequential loop over durations 1..30.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from ..models.cell import PricingCell
from ..models.results import CellProjection, CellResult
from ..models.sensitivities import SensitivitySet
from . import lookups as L
from .metrics import irr, npv


def project_cell(
    cell: PricingCell,
    asm: AssumptionSet,
    sens: SensitivitySet,
    state: str,
    rerates: list[float],
) -> CellResult:
    """Project a single pricing cell.

    ``rerates`` is the recommended rerate % by duration (length 30). The achieved
    rerate is scaled by ``sens.rerate_effectiveness``.
    """
    key = cell.key
    n = PROJECTION_YEARS
    o = asm.other
    morb = asm.morbidity
    rr = asm.rerates
    lam_claims = rr.antiselection_lambda_claims
    lam_lapse = rr.antiselection_lambda_lapse
    base_prem = L.premium_for_cell(asm, key, state)
    state_cc_factor = morb.state_factors.get(state, morb.state_factors.get("All", 1.0))
    lapse_state_factor = asm.termination.state_factors.get(state, 1.0)

    # effective rerate vector
    eff = sens.rerate_effectiveness
    rerate_used = [rerates[i] * eff for i in range(n)]

    # series buffers
    S = {k: [0.0] * n for k in (
        "lives", "lapse", "mortality", "total_term", "rerate_used", "total_rerate",
        "earned_prem", "ibnr", "nii", "base_cc", "selection", "trend",
        "antiselection", "claims", "commission", "premium_tax", "oper_acq",
        "marketing", "maintenance", "pretax_income", "tax", "at_income",
        "rbc", "int_on_rbc", "tax_on_int", "ah_cashflow", "in_year_lr", "lifetime_lr",
    )}

    lives_prev = 1.0       # lives at time 0 (issue)
    G_prev = 1.0           # cumulative rerate factor
    H_prev = 1.0           # cumulative aging-rerate factor
    O_prev = 1.0           # cumulative trend factor
    P_prev = 1.0           # antiselection factor
    ibnr_prev = 0.0
    rbc_prev = 0.0
    cum_claims = 0.0
    cum_prem = 0.0

    for i in range(n):
        d = i + 1
        attained_age = key.issue_age + d - 1
        rate_d = rerate_used[i]
        trend_d = L.trend_year(asm, d)

        # --- termination -------------------------------------------------
        base_lapse = L.lapse_rate(asm, key.uw_class, d) * lapse_state_factor
        # rerate-driven antiselective lapse: (1 + lambda*(rerate - trend)), with sensitivity
        lapse_antisel = 1.0 + lam_lapse * (rate_d - trend_d) * sens.antiselective_lapse
        lapse_d = base_lapse * sens.termination_scale * lapse_antisel
        lapse_d = max(0.0, min(lapse_d, 1.0))
        mort_d = asm.termination.mortality(attained_age)
        term_raw = 1.0 - (1.0 - lapse_d) * (1.0 - mort_d)
        if d == 1:
            term_d = term_raw
        elif d == 2:
            term_d = min(term_raw * asm.termination.dur2_scaling, 1.0)
        else:
            term_d = min(term_raw * asm.termination.dur3plus_scaling, 1.0)
        lives_d = lives_prev * (1.0 - term_d)
        avg_lives = (lives_prev + lives_d) / 2.0

        # --- premium / rerate -------------------------------------------
        G_d = G_prev * (1.0 + rate_d)
        if d == 1:
            H_d = 1.0
        else:
            H_d = H_prev * (1.0 + L.aging_rerate(asm, attained_age))
        total_rerate = G_d * H_d
        earned_prem = base_prem * total_rerate * avg_lives

        # --- trend & antiselection (col O, P) ---------------------------
        if d == 1:
            O_d = (1.0 + trend_d) ** morb.trend_first_year_exponent
            P_d = 1.0
        else:
            O_d = O_prev * (1.0 + trend_d)
            aging = L.cc_aging_duration(asm, d)
            P_d = (1.0 + aging) * P_prev + lam_claims * (rate_d - trend_d) * sens.antiselective_claims

        # --- claims ------------------------------------------------------
        base_cc = (
            L.base_claim_cost(asm, key.gender, attained_age, key.plan)
            * L.claim_class_factors(asm, key.uw_class, key.preferred, key.hhd)
            * sens.morbidity_scale
        )
        selection = L.selection_factor(asm, key.issue_age, key.uw_class, d)
        claims = base_cc * selection * O_d * P_d * state_cc_factor * avg_lives

        # --- IBNR / NII --------------------------------------------------
        ibnr = o.ibnr_pct * claims
        nii = (ibnr_prev + ibnr) / 2.0 * o.nier

        # --- expenses ----------------------------------------------------
        yr1_prem = base_prem * (1.0 + rerate_used[0])
        comm_base = yr1_prem - (asm.commission.plan_f_offset if key.plan == "F" else 0.0)
        if key.uw_class == "GI":
            commission = asm.commission.gi_flat * avg_lives
        else:
            age_mult = 0.5 if (asm.commission.age80_halving and key.issue_age >= 80) else 1.0
            commission = age_mult * asm.commission.rate(state, d, key.plan) * comm_base * avg_lives
        premium_tax = o.premium_tax * earned_prem
        # acquisition costs are one-time at issue (year 1); maintenance recurs and inflates
        oper_acq = o.oper_acq if d == 1 else 0.0
        marketing = o.marketing_acq if d == 1 else 0.0
        maintenance = o.maintenance * avg_lives * (1.0 + o.inflation) ** d

        # --- income ------------------------------------------------------
        pretax = earned_prem + nii - claims - commission - premium_tax - oper_acq - marketing - maintenance
        tax = -o.tax_rate * pretax
        at_income = pretax + tax

        # --- capital -----------------------------------------------------
        rbc = o.rbc_pct_of_prem * earned_prem * o.rbc_factor * o.covariance
        int_on_rbc = rbc * o.nier
        tax_on_int = -o.tax_rate * int_on_rbc
        ah = rbc_prev - rbc + int_on_rbc + tax_on_int + at_income

        # --- ratios ------------------------------------------------------
        cum_claims += claims
        cum_prem += earned_prem
        in_year_lr = claims / earned_prem if earned_prem else 0.0
        lifetime_lr = cum_claims / cum_prem if cum_prem else 0.0

        # store
        S["lives"][i] = lives_d
        S["lapse"][i] = lapse_d
        S["mortality"][i] = mort_d
        S["total_term"][i] = term_d
        S["rerate_used"][i] = rate_d
        S["total_rerate"][i] = total_rerate
        S["earned_prem"][i] = earned_prem
        S["ibnr"][i] = ibnr
        S["nii"][i] = nii
        S["base_cc"][i] = base_cc
        S["selection"][i] = selection
        S["trend"][i] = O_d
        S["antiselection"][i] = P_d
        S["claims"][i] = claims
        S["commission"][i] = commission
        S["premium_tax"][i] = premium_tax
        S["oper_acq"][i] = oper_acq
        S["marketing"][i] = marketing
        S["maintenance"][i] = maintenance
        S["pretax_income"][i] = pretax
        S["tax"][i] = tax
        S["at_income"][i] = at_income
        S["rbc"][i] = rbc
        S["int_on_rbc"][i] = int_on_rbc
        S["tax_on_int"][i] = tax_on_int
        S["ah_cashflow"][i] = ah
        S["in_year_lr"][i] = in_year_lr
        S["lifetime_lr"][i] = lifetime_lr

        lives_prev, G_prev, H_prev, O_prev, P_prev = lives_d, G_d, H_d, O_d, P_d
        ibnr_prev, rbc_prev = ibnr, rbc

    proj = CellProjection(series=S)
    cell_irr = irr(S["ah_cashflow"])
    lifetime = S["lifetime_lr"][-1]
    npv_pretax = npv(o.discount_rate, S["pretax_income"])
    return CellResult(
        key=key, weight=cell.weight, projection=proj,
        irr=cell_irr, lifetime_lr=lifetime, npv_pretax=npv_pretax,
    )
