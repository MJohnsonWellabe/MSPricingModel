"""Front-load rerate solver (targets the lifetime loss ratio).

Strategy (confirmed with the user): each year take the largest rerate that does NOT
push the aggregate in-year loss ratio below the floor (capped by ``max_rerate`` and
the consecutive-rerate rule), front-loading the early durations, then ride at trend.
Choose how many years to front-load (continuous ``K``) so the lifetime loss ratio
hits the target; best effort if it can't be reached within the floor/rules.

Implemented with numpy over the state's cells for speed. Per-duration line items
come from the same editable :class:`FormulaSet` the per-cell projection uses — the
expressions evaluate over numpy arrays here and over scalars in ``project.py`` — so
the solver, the deterministic projection, and the stochastic engine stay consistent.
The solver only evaluates the *core* formulas (through earned premium and claims);
the full set (expenses/income/capital) is evaluated by ``project_aggregate``.
Rerate effectiveness is 1.0 during the solve (recommended rerates); the effectiveness
haircut is applied by the projection.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from ..models.formulas import FormulaSet
from . import lookups as L
from .formulas import compile_steps, default_formula_set, eval_steps


def precompute(cells, asm: AssumptionSet, state: str) -> dict:
    """Sensitivity-independent per-state precompute (reusable across simulations)."""
    n = PROJECTION_YEARS
    nc = len(cells)
    morb = asm.morbidity
    state_cc = morb.state_factors.get(state, morb.state_factors.get("All", 1.0))
    lapse_state = asm.termination.state_factors.get(state, 1.0)

    weight = np.array([c.weight for c in cells], dtype=float)
    base_prem = np.array([L.premium_for_cell(asm, c.key, state) for c in cells], dtype=float)

    lapse_base = np.zeros((nc, n))
    mort = np.zeros((nc, n))
    claim_base = np.zeros((nc, n))   # base_cc x class factors x pull-forward (no morbidity_scale)
    selection = np.zeros((nc, n))
    aging_h = np.zeros((nc, n))
    comm_rate = np.zeros((nc, n))
    gi = np.zeros(nc, dtype=bool)
    planf = np.zeros(nc, dtype=bool)
    age80 = np.zeros(nc, dtype=bool)
    for ci, c in enumerate(cells):
        k = c.key
        cls = L.claim_class_factors(asm, k.uw_class, k.preferred, k.hhd, state)
        gi[ci] = k.uw_class == "GI"
        planf[ci] = k.plan == "F"
        age80[ci] = k.issue_age >= 80
        # claims base cost is by ISSUE age (constant across duration), matching the
        # workbook Output/Aggregate; mortality & aging-rerate stay attained-age
        cell_claim_base = L.base_claim_cost(asm, k.gender, k.issue_age, k.plan, state) * cls
        for i in range(n):
            d = i + 1
            attained = k.issue_age + d - 1
            lapse_base[ci, i] = L.lapse_rate(asm, k.uw_class, d) * lapse_state
            mort[ci, i] = asm.termination.mortality(attained)
            claim_base[ci, i] = cell_claim_base
            selection[ci, i] = L.selection_factor(asm, k.issue_age, k.uw_class, d)
            aging_h[ci, i] = L.aging_rerate(asm, attained) if d >= 2 else 0.0
            comm_rate[ci, i] = asm.commission.rate(state, d, k.plan)

    trend = np.array([L.trend_year(asm, i + 1) for i in range(n)])
    aging_p = np.array([L.cc_aging_duration(asm, i + 1) for i in range(n)])
    age_mult = np.where(age80 & asm.commission.age80_halving, 0.5, 1.0)
    planf_offset = np.where(planf, asm.commission.plan_f_offset, 0.0)

    return dict(
        n=n, weight=weight, base_prem=base_prem, lapse_base=lapse_base, mort=mort,
        claim_base=claim_base, selection=selection, aging_h=aging_h, trend=trend,
        aging_p=aging_p, state_cc=state_cc, comm_rate=comm_rate, gi=gi,
        age_mult=age_mult, planf_offset=planf_offset,
        dur2=asm.termination.dur2_scaling, dur3=asm.termination.dur3plus_scaling,
        lam_lapse=asm.rerates.antiselection_lambda_lapse,
        lam_claims=asm.rerates.antiselection_lambda_claims,
        spec=list(asm.rerates.rerates_for(state)),   # per-state specified rerates (durs 1-2)
    )


def _make_ns(P, asm, sens, i, rate, carry, extra=None):
    """Build the per-duration namespace (numpy arrays + scalars) shared by the
    core solve and the full aggregate projection."""
    d = i + 1
    trend_i = P["trend"][i]
    ns = {
        "d": d, "rate_d": rate, "trend_d": trend_i,
        "trend_step": 0.0 if i == 0 else trend_i,
        "dur_scale": 1.0 if i == 0 else P["dur2"] if i == 1 else P["dur3"],
        "acq_active": 1.0 if i == 0 else 0.0,
        "first_year": 1.0 if i == 0 else 0.0,
        "aging_p": P["aging_p"][i], "state_cc": P["state_cc"],
        "base_prem": P["base_prem"], "base_cc": P["claim_base"][:, i],
        "selection": P["selection"][:, i], "lapse_base": P["lapse_base"][:, i],
        "mort_d": P["mort"][:, i], "aging_h": P["aging_h"][:, i],
        "comm_rate": P["comm_rate"][:, i], "is_gi": P["gi"],
        "comm_age_mult": P["age_mult"], "planf_offset_d": P["planf_offset"],
        "morbidity_scale": sens.morbidity_scale,
        "termination_scale": sens.termination_scale,
        "antiselective_lapse": sens.antiselective_lapse,
        "antiselective_claims": sens.antiselective_claims,
        "lam_lapse": P["lam_lapse"], "lam_claims": P["lam_claims"],
    }
    ns.update(carry)
    if extra:
        ns.update(extra)
    return ns


def _core_step(P, asm, sens, i, rate, carry, core):
    """Evaluate the core formulas → (earned_agg, claims_agg, inyear, new_carry)."""
    ns = _make_ns(P, asm, sens, i, rate, carry)
    eval_steps(core, ns)
    ea = float(np.dot(P["weight"], ns["earned_prem"]))
    ca = float(np.dot(P["weight"], ns["claims"]))
    inyear = ca / ea if ea else 0.0
    new_carry = {"lives_prev": ns["lives_d"], "G_prev": ns["G_d"],
                 "H_prev": ns["H_d"], "O_prev": ns["O_d"], "P_prev": ns["P_d"]}
    return ea, ca, inyear, new_carry


def _init_carry(nc, full=False):
    carry = {"lives_prev": np.ones(nc), "G_prev": 1.0, "H_prev": np.ones(nc),
             "O_prev": 1.0, "P_prev": 1.0}
    if full:
        carry["ibnr_prev"] = np.zeros(nc)
        carry["rbc_prev"] = np.zeros(nc)
    return carry


def _floor_rate(P, asm, sens, i, carry, core, floor, lo, cap):
    """Largest rate in [lo, cap] keeping in-year LR >= floor (LR decreases in rate)."""
    def inyear(r):
        return _core_step(P, asm, sens, i, r, carry, core)[2]
    if inyear(cap) >= floor:
        return cap
    if inyear(lo) <= floor:
        return lo
    a, b = lo, cap
    for _ in range(40):
        mid = (a + b) / 2.0
        if inyear(mid) >= floor:
            a = mid
        else:
            b = mid
    return a


def solve_rerates(cells, asm: AssumptionSet, sens, state: str,
                  tol: float = 1e-3, formulas: Optional[FormulaSet] = None
                  ) -> tuple[list[float], dict]:
    return solve_with_precompute(precompute(cells, asm, state), asm, sens, tol, formulas)


def solve_with_precompute(P, asm: AssumptionSet, sens, tol: float = 1e-3,
                          formulas: Optional[FormulaSet] = None
                          ) -> tuple[list[float], dict]:
    n = P["n"]
    rr = asm.rerates
    dr = asm.other.discount_rate                   # for the discounted lifetime-LR target
    spec = P.get("spec") or rr.specified_rerates   # per-state schedule when present
    floor = rr.in_year_lr_floor
    z, b_rule = rr.consecutive_z, max(1, rr.consecutive_b)
    nc = len(P["weight"])
    core, _ = compile_steps(formulas or default_formula_set())

    def forward(K: float):
        """Front-load floor-limited rerates for durations up to K, trend after.
        Returns (rerates list, lifetime_lr)."""
        carry = _init_carry(nc)
        run = 0  # trailing run of rerates above z
        cum_c = cum_p = 0.0
        rates = [0.0] * n
        for i in range(n):
            d = i + 1
            trend_i = P["trend"][i]
            if d <= 2:
                rate = spec[i] if i < len(spec) else trend_i
            else:
                cap = rr.max_rerate
                if run >= b_rule:
                    cap = min(cap, z)
                cap = max(cap, trend_i)
                if d <= int(K):
                    rate = _floor_rate(P, asm, sens, i, carry, core, floor, trend_i, cap)
                elif d == int(K) + 1 and (K - int(K)) > 0:
                    fr = _floor_rate(P, asm, sens, i, carry, core, floor, trend_i, cap)
                    rate = trend_i + (K - int(K)) * (fr - trend_i)
                else:
                    rate = trend_i
            ea, ca, _iy, carry = _core_step(P, asm, sens, i, rate, carry, core)
            df = 1.0 / (1.0 + dr) ** (i + 1)   # NPV-discounted lifetime LR (solver target)
            cum_p += ea * df
            cum_c += ca * df
            rates[i] = rate
            run = run + 1 if rate > z else 0
        lifetime = cum_c / cum_p if cum_p else 0.0
        return rates, lifetime

    target = rr.target_lifetime_lr
    rates_lo, lr_hi = forward(2.0)      # least rerate -> highest lifetime LR
    rates_hi, lr_lo = forward(float(n))  # most rerate -> lowest lifetime LR

    info: dict = {"target": target, "lr_min": lr_lo, "lr_max": lr_hi}
    if lr_hi <= target:
        rates, info["status"], info["K"] = rates_lo, "target_met_without_rerate", 2.0
    elif lr_lo >= target:
        rates, info["status"], info["K"] = rates_hi, "target_unreachable", float(n)
    else:
        lo, hi = 2.0, float(n)
        rates = rates_hi
        for _ in range(40):
            mid = (lo + hi) / 2.0
            rates, lr = forward(mid)
            if abs(lr - target) < tol:
                break
            if lr > target:   # not enough rerate -> push more
                lo = mid
            else:
                hi = mid
        info["status"], info["K"] = "converged", mid

    _, achieved = forward(info["K"])
    info["achieved_lifetime_lr"] = float(achieved)
    return [float(r) for r in rates], info


def project_aggregate(P, asm: AssumptionSet, sens, rates,
                      formulas: Optional[FormulaSet] = None, return_series: bool = False):
    """Fast numpy aggregate projection of a given rerate vector → (irr, lifetime_lr).

    Evaluates the full formula set over the cell arrays and aggregates the
    distributable cashflow; used by the stochastic sensitivity loop to avoid the
    per-cell Python projection. Rerate effectiveness is applied (as the projection
    does). With ``return_series=True`` also returns the weight-aggregated dollar
    series dict (income-statement lines by duration) → (irr, lifetime_lr, series)."""
    from .metrics import irr as _irr
    from .project import _SERIES_FROM_NS

    n = P["n"]
    w = P["weight"]
    _, full = compile_steps(formulas or default_formula_set())
    eff = sens.rerate_effectiveness
    rate0 = (rates[0] if len(rates) else 0.0) * eff
    yr1_prem = P["base_prem"] * (1.0 + rate0)
    extra = {
        "yr1_prem": yr1_prem, "gi_flat": asm.commission.gi_flat,
        "ibnr_pct": asm.other.ibnr_pct, "nier": asm.other.nier,
        "premium_tax_rate": asm.other.premium_tax, "tax_rate": asm.other.tax_rate,
        "oper_acq_amt": asm.other.oper_acq, "marketing_amt": asm.other.marketing_acq,
        "maintenance_amt": asm.other.maintenance, "inflation": asm.other.inflation,
        "rbc_pct": asm.other.rbc_pct_of_prem, "rbc_factor": asm.other.rbc_factor,
        "covariance": asm.other.covariance,
    }

    # income-statement lines to aggregate when return_series is requested
    _LINES = ("lives", "earned_prem", "ibnr", "nii", "claims", "commission",
              "premium_tax", "oper_acq", "marketing", "maintenance", "pretax_income",
              "tax", "at_income", "rbc", "int_on_rbc", "tax_on_int", "ah_cashflow")
    series = {k: [0.0] * n for k in _LINES} if return_series else None
    wsum = float(np.sum(w))

    nc = len(w)
    carry = _init_carry(nc, full=True)
    cum_c = cum_p = 0.0
    dr = asm.other.discount_rate                   # discounted lifetime LR (matches aggregate)
    ah = [0.0] * n
    for i in range(n):
        rate = rates[i] * eff
        ns = _make_ns(P, asm, sens, i, rate, carry, extra=extra)
        eval_steps(full, ns)
        df = 1.0 / (1.0 + dr) ** (i + 1)
        cum_p += float(np.dot(w, ns["earned_prem"])) * df
        cum_c += float(np.dot(w, ns["claims"])) * df
        ah[i] = float(np.dot(w, ns["ah"]))
        if series is not None:
            for k in _LINES:
                val = ns[_SERIES_FROM_NS[k]]
                # some lines (flat acquisition amounts) are scalars broadcast across cells
                series[k][i] = (float(np.dot(w, val)) if np.ndim(val)
                                else float(val) * wsum)
        carry = {"lives_prev": ns["lives_d"], "G_prev": ns["G_d"], "H_prev": ns["H_d"],
                 "O_prev": ns["O_d"], "P_prev": ns["P_d"],
                 "ibnr_prev": ns["ibnr"], "rbc_prev": ns["rbc"]}

    lifetime = cum_c / cum_p if cum_p else 0.0
    if return_series:
        return _irr(ah), lifetime, series
    return _irr(ah), lifetime
