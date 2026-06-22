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

# index of each dimension within the cell-key tuple used by aggregate_sales
_DIM_INDEX = {"issue_age": 0, "gender": 1, "plan": 2, "uw": 3, "preferred": 4, "hhd": 5}


def apply_sales(asm: AssumptionSet, sales: dict, parts=("distribution", "premium")) -> AssumptionSet:
    """Return a copy of ``asm`` with distribution weight factors and/or the premium
    factor model recalibrated from the sales aggregation. ``parts`` selects which
    blocks to adopt (default both)."""
    new = copy.deepcopy(asm)
    parts = set(parts)
    counts = sales["counts"]            # cell-key tuple -> total applications
    avg_premium = sales["avg_premium"]  # cell-key tuple -> average premium
    state_prem = sales["state_premiums"]

    # ---- distribution: joint plan x issue-age x UW grid (captures the
    # non-separable mix) plus independent gender / preferred / HHD marginals ----
    total = sum(counts.values()) or 1.0
    if "distribution" in parts and counts:
        grid: dict[str, dict[str, dict[str, float]]] = {}
        for k, c in counts.items():
            age, _g, plan, uw, _p, _h = k  # tuple order per _DIM_INDEX
            ages = grid.setdefault(str(plan), {}).setdefault(str(int(age)), {})
            ages[str(uw)] = ages.get(str(uw), 0.0) + c / total
        new.distribution.joint = {
            pl: {a: {u: round(w, 8) for u, w in uws.items()} for a, uws in ages.items()}
            for pl, ages in grid.items()}
        for dim in ("gender", "preferred", "hhd"):
            marg = defaultdict(float)
            for k, c in counts.items():
                marg[k[_DIM_INDEX[dim]]] += c
            setattr(new.distribution, dim, {v: round(c / total, 8) for v, c in marg.items()})

    # ---- premium: log main-effects decomposition weighted by count ----
    obs = [(k, math.log(p), counts.get(k, 0.0))
           for k, p in avg_premium.items() if p > 0 and counts.get(k, 0.0) > 0]
    if "premium" in parts and obs:
        wtot = sum(w for _, _, w in obs) or 1.0
        mu = sum(lp * w for _, lp, w in obs) / wtot

        def eff(idx):
            g = defaultdict(lambda: [0.0, 0.0])
            for k, lp, w in obs:
                g[k[idx]][0] += lp * w
                g[k[idx]][1] += w
            return {v: (s / w - mu) for v, (s, w) in g.items() if w}

        p = new.premium
        plan_eff = eff(2)
        plan_g = plan_eff.get("G", 0.0)
        # base = blend at plan G; plan relativities anchored at G = 1.0
        p.base_by_issue_age = {int(a): round(math.exp(mu + e + plan_g), 4)
                               for a, e in eff(0).items()}
        p.plan_rel = {v: round(math.exp(e - plan_g), 6) for v, e in plan_eff.items()}
        p.uw_rel = {v: round(math.exp(e), 6) for v, e in eff(3).items()}

        # two-level dims expressed as a single differential (high level over low)
        def diff(idx, high, low):
            e = eff(idx)
            return round(math.exp(e.get(high, 0.0) - e.get(low, 0.0)) - 1.0, 6)

        p.gender_diff = diff(1, "M", "F")
        p.preferred_diff = diff(4, "N", "Y")
        p.hhd_diff = diff(5, "N", "Y")

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


def apply_claims(asm: AssumptionSet, claims: dict,
                 parts=("base_cc", "gender", "state", "selection")) -> AssumptionSet:
    """Return a copy of ``asm`` with the morbidity assumptions the claims data can
    inform: base claim-cost level by plan & **issue age**, the gender differential,
    state morbidity factors, and UW selection factors. ``parts`` selects which to
    adopt (default all). Where an (issue age, plan) has no experience, the existing
    pricing value is retained — no smoothing or extrapolation (revert to pricing).
    (Claim-cost aging is a diagnostic, not adopted; lapse/mortality/trend are not in
    the data.)"""
    new = copy.deepcopy(asm)
    morb = new.morbidity
    parts = set(parts)

    # base claim cost by plan & ISSUE age (gender blend). Where a band has no data,
    # keep the current pricing value (revert to pricing — no extrapolation).
    if "base_cc" in parts:
        by_issue = claims.get("base_cc_by_issue_age", {})
        for plan in morb.plans:
            curve = by_issue.get(plan)
            if not curve:
                continue
            morb.base_cc[plan] = [round(curve[a], 4) if a in curve else old
                                  for a, old in zip(morb.ages, morb.base_cc[plan])]

    # gender differential
    if "gender" in parts and claims.get("gender_diff") is not None:
        morb.gender_cc_diff = float(claims["gender_diff"])

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
    return new
