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


def _precompute(cells, asm: AssumptionSet, sens, state: str) -> dict:
    n = PROJECTION_YEARS
    nc = len(cells)
    morb = asm.morbidity
    state_cc = morb.state_factors.get(state, morb.state_factors.get("All", 1.0))
    lapse_state = asm.termination.state_factors.get(state, 1.0)

    weight = np.array([c.weight for c in cells], dtype=float)
    base_prem = np.array([L.premium_for_cell(asm, c.key, state) for c in cells], dtype=float)

    lapse_base = np.zeros((nc, n))
    mort = np.zeros((nc, n))
    claim_base = np.zeros((nc, n))
    selection = np.zeros((nc, n))
    aging_h = np.zeros((nc, n))
    for ci, c in enumerate(cells):
        k = c.key
        cls = L.claim_class_factors(asm, k.uw_class, k.preferred, k.hhd) * sens.morbidity_scale
        for i in range(n):
            d = i + 1
            attained = k.issue_age + d - 1
            lapse_base[ci, i] = L.lapse_rate(asm, k.uw_class, d) * lapse_state
            mort[ci, i] = asm.termination.mortality(attained)
            claim_base[ci, i] = L.base_claim_cost(asm, k.gender, attained, k.plan) * cls
            selection[ci, i] = L.selection_factor(asm, k.issue_age, k.uw_class, d)
            aging_h[ci, i] = L.aging_rerate(asm, attained) if d >= 2 else 0.0

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
        dur2=asm.termination.dur2_scaling, dur3=asm.termination.dur3plus_scaling,
        lam_lapse=asm.rerates.antiselection_lambda_lapse,
        lam_claims=asm.rerates.antiselection_lambda_claims,
        antisel_lapse=sens.antiselective_lapse, antisel_claims=sens.antiselective_claims,
        term_scale=sens.termination_scale,
    )


def _duration_step(P, i, rate, lives_prev, G_prev, H_prev, P_prev):
    """Vectorised one-duration step. Returns (earned_agg, claims_agg, inyear,
    lives_new, G_new, H_new, P_new)."""
    trend_i = P["trend"][i]
    lapse = P["lapse_base"][:, i] * P["term_scale"] * (
        1.0 + P["lam_lapse"] * (rate - trend_i) * P["antisel_lapse"])
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
        P_new = (1.0 + P["aging_p"][i]) * P_prev + P["lam_claims"] * (rate - trend_i) * P["antisel_claims"]
    claims = P["claim_base"][:, i] * P["selection"][:, i] * P["O"][i] * P_new * P["state_cc"] * avg
    claims_agg = float(np.dot(P["weight"], claims))

    inyear = claims_agg / earned_agg if earned_agg else 0.0
    return earned_agg, claims_agg, inyear, lives_new, G_new, H_new, P_new


def _floor_rate(P, i, lives_prev, G_prev, H_prev, P_prev, floor, lo, cap):
    """Largest rate in [lo, cap] keeping in-year LR >= floor (LR decreases in rate)."""
    def inyear(r):
        return _duration_step(P, i, r, lives_prev, G_prev, H_prev, P_prev)[2]
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
    P = _precompute(cells, asm, sens, state)
    n = P["n"]
    rr = asm.rerates
    spec = rr.specified_rerates
    floor = rr.in_year_lr_floor
    z, b_rule = rr.consecutive_z, max(1, rr.consecutive_b)
    nc = len(cells)

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
                    rate = _floor_rate(P, i, lives, G, H, Pv, floor, trend_i, cap)
                elif d == int(K) + 1 and (K - int(K)) > 0:
                    fr = _floor_rate(P, i, lives, G, H, Pv, floor, trend_i, cap)
                    rate = trend_i + (K - int(K)) * (fr - trend_i)
                else:
                    rate = trend_i
            ea, ca, _iy, lives, G, H, Pv = _duration_step(P, i, rate, lives, G, H, Pv)
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
