"""Apply experience-study results into the assumption model ('Adopt').

Sales results update the distribution weight factors and the premium factor model
(base by issue age + multiplicative factors). Claims results recalibrate the
*level* of the base claim-cost tables per plan and the state morbidity factors.
Selection and claim-cost aging are surfaced in the UI for the user to judge rather
than auto-applied (best-estimate aging already lives in the attained-age base-cost
curve, distinct from the pricing antiselection load).
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict

from ..models.assumptions import AssumptionSet
from .credibility import blend, credibility_z
from .decomp import differential, fit_main_effects

# index of each dimension within the cell-key tuple used by aggregate_sales
_DIM_INDEX = {"issue_age": 0, "gender": 1, "plan": 2, "uw": 3, "preferred": 4, "hhd": 5}


def _distribution_block(counts: dict) -> dict:
    """Build a {joint, gender, preferred, hhd} distribution block from cell-key counts
    (joint plan x issue-age x UW grid + independent gender/preferred/HHD marginals,
    each normalised to sum to 1)."""
    total = sum(counts.values()) or 1.0
    grid: dict[str, dict[str, dict[str, float]]] = {}
    for k, c in counts.items():
        age, _g, plan, uw, _p, _h = k  # tuple order per _DIM_INDEX
        ages = grid.setdefault(str(plan), {}).setdefault(str(int(age)), {})
        ages[str(uw)] = ages.get(str(uw), 0.0) + c / total
    joint = {pl: {a: {u: round(w, 8) for u, w in uws.items()} for a, uws in ages.items()}
             for pl, ages in grid.items()}
    out = {"joint": joint}
    for dim in ("gender", "preferred", "hhd"):
        marg: dict = defaultdict(float)
        for k, c in counts.items():
            marg[k[_DIM_INDEX[dim]]] += c
        out[dim] = {v: round(c / total, 8) for v, c in marg.items()}
    return out


def apply_sales(asm: AssumptionSet, sales: dict, parts=("distribution", "premium")) -> AssumptionSet:
    """Return a copy of ``asm`` with distribution weight factors and/or the premium
    factor model recalibrated from the sales aggregation. ``parts`` selects which
    blocks to adopt (default both)."""
    new = copy.deepcopy(asm)
    parts = set(parts)
    counts = sales["counts"]            # cell-key tuple -> total applications
    avg_premium = sales["avg_premium"]  # cell-key tuple -> average premium
    state_prem = sales["state_premiums"]
    state_counts = sales.get("state_counts", {})   # cell-key -> {state: count}

    # ---- distribution: a national joint plan x issue-age x UW grid + gender/preferred/
    # HHD marginals, AND a per-state grid (GI/OE/UW and plan mix vary by state) ----
    if "distribution" in parts and counts:
        nat = _distribution_block(counts)
        new.distribution.joint = nat["joint"]
        for dim in ("gender", "preferred", "hhd"):
            setattr(new.distribution, dim, nat[dim])
        # per-state grids from the per-(cell, state) counts
        by_state_counts: dict = defaultdict(dict)
        for k, per_state in state_counts.items():
            for s, c in per_state.items():
                by_state_counts[s][k] = c
        new.distribution.by_state = {
            s: _distribution_block(ck) for s, ck in by_state_counts.items() if ck}

    # ---- premium: ISOLATED multivariate main-effects fit (key dims 0=age, 1=gender,
    # 2=plan, 3=uw, 4=preferred, 5=hhd), so each differential holds the others fixed
    # rather than reading a confounded marginal ----
    obs = [(k, p, counts.get(k, 0.0))
           for k, p in avg_premium.items() if p > 0 and counts.get(k, 0.0) > 0]
    if "premium" in parts and obs:
        fit = fit_main_effects(obs, n_dims=6)
        factors, logeff, baseline = fit["factors"], fit["log_effects"], fit["baseline"]
        plan_g = factors[2].get("G", 1.0) or 1.0

        p = new.premium
        # base = blend at plan G; plan relativities anchored at G = 1.0
        p.base_by_issue_age = {int(a): round(baseline * f * plan_g, 4)
                               for a, f in factors[0].items()}
        p.plan_rel = {v: round(f / plan_g, 6) for v, f in factors[2].items()}
        p.uw_rel = {v: round(f, 6) for v, f in factors[3].items()}
        p.gender_diff = round(differential(factors, 1, "M", "F"), 6)
        p.preferred_diff = round(differential(factors, 4, "N", "Y"), 6)
        p.hhd_diff = round(differential(factors, 5, "N", "Y"), 6)
        _ = logeff  # (additive effects available if needed)

        # state premium factors: geomean of (state premium / cell average premium)
        st_logs = defaultdict(list)
        for k, by_state in state_prem.items():
            comp = avg_premium.get(k, 0.0)
            for s, sp in by_state.items():
                if comp > 0 and sp > 0:
                    st_logs[s].append(math.log(sp / comp))
        if st_logs:
            sf = {s: round(math.exp(sum(v) / len(v)), 6) for s, v in st_logs.items()}
            sf.setdefault("All", 1.0)
            p.state_factor = sf
    return new


def _incremental_aging(curve: dict, n: int) -> list:
    """Cumulative aging curve (duration -> factor >=1) -> the engine's incremental
    cc_aging_by_duration of length ``n`` (index d-1). Increment is cum_d/cum_{d-1}-1,
    floored at 0 so (1+aging) is never below 1; durations past the data hold flat."""
    if not curve:
        return [0.0] * n
    durs = sorted(curve)
    last = durs[-1]
    inc = [0.0] * n
    for d in range(2, n + 1):
        cum_d = curve.get(d, curve[last])
        cum_prev = curve.get(d - 1, curve[last])
        inc[d - 1] = round(max(0.0, cum_d / cum_prev - 1.0), 6) if cum_prev else 0.0
    return inc


def apply_claims(asm: AssumptionSet, claims: dict,
                 parts=("base_cc", "gender", "state", "selection"),
                 credibility_standard: float = 0.0) -> AssumptionSet:
    """Return a copy of ``asm`` with the morbidity assumptions the claims data can
    inform: base claim-cost level by plan & **issue age**, the gender differential,
    state morbidity factors, UW selection, and claim-cost aging. ``parts`` selects
    which to adopt. ``credibility_standard`` (life-years for full credibility, 0 = off)
    blends each base-cost band's experience with the current pricing value via the
    square-root rule. Where an (issue age, plan) has no experience, the existing
    pricing value is retained (revert to pricing — no extrapolation)."""
    new = copy.deepcopy(asm)
    morb = new.morbidity
    parts = set(parts)

    # base claim cost by plan & ISSUE age (gender blend), credibility-blended toward
    # the current pricing value; bands with no data keep the pricing value.
    if "base_cc" in parts:
        by_issue = claims.get("base_cc_by_issue_age", {})
        expo = claims.get("base_cc_exposure", {})
        for plan in morb.plans:
            curve = by_issue.get(plan)
            if not curve:
                continue
            new_vals = []
            for a, old in zip(morb.ages, morb.base_cc[plan]):
                if a in curve:
                    z = credibility_z(expo.get(plan, {}).get(a, 0.0), credibility_standard)
                    new_vals.append(round(blend(curve[a], old, z), 4))
                else:
                    new_vals.append(old)   # revert to pricing
            morb.base_cc[plan] = new_vals

    # gender differential — prefer the isolated (multivariate) estimate
    if "gender" in parts:
        gd = claims.get("gender_diff_isolated", claims.get("gender_diff"))
        if gd is not None:
            morb.gender_cc_diff = float(gd)

    # state factors from observed relativities (keep existing where not observed)
    if "state" in parts:
        for state, f in claims.get("state_factors", {}).items():
            if f > 0:
                morb.state_factors[state] = f

    # UW selection factors by (issue_age, uw, duration)
    if "selection" in parts:
        rows = claims.get("selection_rows")
        if rows:
            morb.selection_factors = [dict(r) for r in rows]

    # claim-cost aging (antiselection P): isolated, monotone >=1 curve -> increments
    if "aging" in parts:
        curve = claims.get("aging_curve")
        if curve:
            morb.cc_aging_by_duration = _incremental_aging(
                curve, len(morb.cc_aging_by_duration))
    return new
