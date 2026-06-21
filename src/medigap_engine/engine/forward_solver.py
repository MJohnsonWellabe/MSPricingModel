"""Front-load rerate solver (targets the lifetime loss ratio).

Strategy (confirmed with the user): each year take the largest rerate that does NOT
push the aggregate in-year loss ratio below the floor (capped by ``max_rerate`` and
the consecutive-rerate rule), front-loading the early durations, then ride at trend.
Choose how many years to front-load (continuous ``K``) so the lifetime loss ratio
hits the target; best effort if it can't be reached within the floor/rules.

Implemented with numpy over the state's cells for speed. It mirrors ``project.py``
math for lives / premium / claims; the final reported numbers still come from
``project_cell`` with the returned rerate vector. Rerate effectiveness is treated
as 1.0 here (the solver picks *recommended* rerates; the effectiveness haircut is
applied later by the projection), while the other sensitivities do affect the solve.
"""
from __future__ import annotations

import numpy as np

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from . import lookups as L


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
    claim_base = np.zeros((nc, n))   # excludes morbidity_scale (applied per-sim)
    selection = np.zeros((nc, n))
    aging_h = np.zeros((nc, n))
    comm_rate = np.zeros((nc, n))
    gi = np.zeros(nc, dtype=bool)
    planf = np.zeros(nc, dtype=bool)
    age80 = np.zeros(nc, dtype=bool)
    for ci, c in enumerate(cells):
        k = c.key
        cls = L.claim_class_factors(asm, k.uw_class, k.preferred, k.hhd)
        gi[ci] = k.uw_class == "GI"
        planf[ci] = k.plan == "F"
        age80[ci] = k.issue_age >= 80
        for i in range(n):
            d = i + 1
            attained = k.issue_age + d - 1
            lapse_base[ci, i] = L.lapse_rate(asm, k.uw_class, d) * lapse_state
            mort[ci, i] = asm.termination.mortality(attained)
            claim_base[ci, i] = L.base_claim_cost(asm, k.gender, attained, k.plan) * cls
            selection[ci, i] = L.selection_factor(asm, k.issue_age, k.uw_class, d)
            aging_h[ci, i] = L.aging_rerate(asm, attained) if d >= 2 else 0.0
            comm_rate[ci, i] = asm.commission.rate(state, d, k.plan)

    trend = np.array([L.trend_year(asm, i + 1) for i in range(n)])
    O = np.zeros(n)
    O[0] = (1.0 + trend[0]) ** morb.trend_first_year_exponent
    for i in range(1, n):
        O[i] = O[i - 1] * (1.0 + trend[i])
    aging_p = np.array([L.cc_aging_duration(asm, i + 1) for i in range(n)])

    return dict(
        n=n, weight=weight, base_prem=base_prem, lapse_base=lapse_base, mort=mort,
        claim_base=claim_base, selection=selection, aging_h=aging_h, trend=trend,
        O=O, aging_p=aging_p, state_cc=state_cc,
        comm_rate=comm_rate, gi=gi, planf=planf, age80=age80,
        dur2=asm.termination.dur2_scaling, dur3=asm.termination.dur3plus_scaling,
        lam_lapse=asm.rerates.antiselection_lambda_lapse,
        lam_claims=asm.rerates.antiselection_lambda_claims,
    )


def _duration_step(P, sens, i, rate, lives_prev, G_prev, H_prev, P_prev):
    """Vectorised one-duration step (sensitivities applied here). Returns
    (earned_agg, claims_agg, inyear, lives_new, G_new, H_new, P_new)."""
    trend_i = P["trend"][i]
    lapse = P["lapse_base"][:, i] * sens.termination_scale * (
        1.0 + P["lam_lapse"] * (rate - trend_i) * sens.antiselective_lapse)
    lapse = np.clip(lapse, 0.0, 1.0)
    term = 1.0 - (1.0 - lapse) * (1.0 - P["mort"][:, i])
    if i == 1:
        term = np.minimum(term * P["dur2"], 1.0)
    elif i >= 2:
        term = np.minimum(term * P["dur3"], 1.0)
    lives_new = lives_prev * (1.0 - term)
    avg = (lives_prev + lives_new) / 2.0

    G_new = G_prev * (1.0 + rate)
    H_new = H_prev * (1.0 + P["aging_h"][:, i]) if i >= 1 else np.ones_like(H_prev)
    earned = P["base_prem"] * G_new * H_new * avg
    earned_agg = float(np.dot(P["weight"], earned))

    if i == 0:
        P_new = 1.0
    else:
        P_new = (1.0 + P["aging_p"][i]) * P_prev + P["lam_claims"] * (rate - trend_i) * sens.antiselective_claims
    claims = (P["claim_base"][:, i] * sens.morbidity_scale * P["selection"][:, i]
              * P["O"][i] * P_new * P["state_cc"] * avg)
    claims_agg = float(np.dot(P["weight"], claims))

    inyear = claims_agg / earned_agg if earned_agg else 0.0
    return earned_agg, claims_agg, inyear, lives_new, G_new, H_new, P_new


def _floor_rate(P, sens, i, lives_prev, G_prev, H_prev, P_prev, floor, lo, cap):
    """Largest rate in [lo, cap] keeping in-year LR >= floor (LR decreases in rate)."""
    def inyear(r):
        return _duration_step(P, sens, i, r, lives_prev, G_prev, H_prev, P_prev)[2]
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
                  tol: float = 1e-3) -> tuple[list[float], dict]:
    return solve_with_precompute(precompute(cells, asm, state), asm, sens, tol)


def solve_with_precompute(P, asm: AssumptionSet, sens,
                          tol: float = 1e-3) -> tuple[list[float], dict]:
    n = P["n"]
    rr = asm.rerates
    spec = rr.specified_rerates
    floor = rr.in_year_lr_floor
    z, b_rule = rr.consecutive_z, max(1, rr.consecutive_b)
    nc = len(P["weight"])

    def forward(K: float):
        """Front-load floor-limited rerates for durations up to K, trend after.
        Returns (rerates list, lifetime_lr)."""
        lives = np.ones(nc)
        G = 1.0
        H = np.ones(nc)
        Pv = 1.0
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
                    rate = _floor_rate(P, sens, i, lives, G, H, Pv, floor, trend_i, cap)
                elif d == int(K) + 1 and (K - int(K)) > 0:
                    fr = _floor_rate(P, sens, i, lives, G, H, Pv, floor, trend_i, cap)
                    rate = trend_i + (K - int(K)) * (fr - trend_i)
                else:
                    rate = trend_i
            ea, ca, _iy, lives, G, H, Pv = _duration_step(P, sens, i, rate, lives, G, H, Pv)
            cum_p += ea
            cum_c += ca
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

    # diagnostics from a final pass
    _, achieved = forward(info["K"])
    info["achieved_lifetime_lr"] = float(achieved)
    return [float(r) for r in rates], info


def project_aggregate(P, asm: AssumptionSet, sens, rates) -> tuple[float, float]:
    """Fast numpy aggregate projection of a given rerate vector → (irr, lifetime_lr).

    Mirrors ``project_cell`` + ``aggregate_cells`` at the aggregate level (rerate
    effectiveness applied, as the projection does). Used by the stochastic
    sensitivity loop to avoid the per-cell Python projection."""
    from .metrics import irr as _irr

    n = P["n"]
    w = P["weight"]
    o = asm.other
    comm = asm.commission
    eff = sens.rerate_effectiveness
    rate0 = (rates[0] if len(rates) else 0.0) * eff
    yr1_prem = P["base_prem"] * (1.0 + rate0)
    comm_base = yr1_prem - np.where(P["planf"], comm.plan_f_offset, 0.0)
    age_mult = np.where(P["age80"] & comm.age80_halving, 0.5, 1.0)

    nc = len(w)
    lives_prev = np.ones(nc)
    G = 1.0
    H = np.ones(nc)
    P_prev = 1.0
    ibnr_prev = np.zeros(nc)
    rbc_prev = np.zeros(nc)
    cum_c = cum_p = 0.0
    ah = [0.0] * n
    for i in range(n):
        rate = rates[i] * eff
        trend_i = P["trend"][i]
        lapse = np.clip(P["lapse_base"][:, i] * sens.termination_scale
                        * (1.0 + P["lam_lapse"] * (rate - trend_i) * sens.antiselective_lapse), 0.0, 1.0)
        term = 1.0 - (1.0 - lapse) * (1.0 - P["mort"][:, i])
        if i == 1:
            term = np.minimum(term * P["dur2"], 1.0)
        elif i >= 2:
            term = np.minimum(term * P["dur3"], 1.0)
        lives = lives_prev * (1.0 - term)
        avg = (lives_prev + lives) / 2.0
        G = G * (1.0 + rate)
        H = H * (1.0 + P["aging_h"][:, i]) if i >= 1 else H
        if i == 0:
            Pv = 1.0
        else:
            Pv = (1.0 + P["aging_p"][i]) * P_prev + P["lam_claims"] * (rate - trend_i) * sens.antiselective_claims
        earned = P["base_prem"] * G * H * avg
        claims = (P["claim_base"][:, i] * sens.morbidity_scale * P["selection"][:, i]
                  * P["O"][i] * Pv * P["state_cc"] * avg)
        ea = float(np.dot(w, earned))
        ca = float(np.dot(w, claims))
        ibnr = o.ibnr_pct * claims
        nii = (ibnr_prev + ibnr) / 2.0 * o.nier
        commission = np.where(P["gi"], comm.gi_flat * avg,
                              age_mult * P["comm_rate"][:, i] * comm_base * avg)
        premium_tax = o.premium_tax * earned
        oper_acq = o.oper_acq if i == 0 else 0.0
        marketing = o.marketing_acq if i == 0 else 0.0
        maintenance = o.maintenance * avg * (1.0 + o.inflation) ** (i + 1)
        pretax = earned + nii - claims - commission - premium_tax - oper_acq - marketing - maintenance
        tax = -o.tax_rate * pretax
        at_income = pretax + tax
        rbc = o.rbc_pct_of_prem * earned * o.rbc_factor * o.covariance
        int_rbc = rbc * o.nier
        tax_int = -o.tax_rate * int_rbc
        ah_cell = rbc_prev - rbc + int_rbc + tax_int + at_income
        ah[i] = float(np.dot(w, ah_cell))
        cum_c += ca
        cum_p += ea
        ibnr_prev, rbc_prev = ibnr, rbc
        lives_prev, P_prev = lives, Pv

    lifetime = cum_c / cum_p if cum_p else 0.0
    return _irr(ah), lifetime
