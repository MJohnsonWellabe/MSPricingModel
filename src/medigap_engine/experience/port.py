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
from ..engine import lookups as L

# index of each dimension within the cell-key tuple used by aggregate_sales
_DIM_INDEX = {"issue_age": 0, "gender": 1, "plan": 2, "uw": 3, "preferred": 4, "hhd": 5}


def apply_sales(asm: AssumptionSet, sales: dict) -> AssumptionSet:
    """Return a copy of ``asm`` with distribution weight factors and the premium
    factor model recalibrated from the sales aggregation."""
    new = copy.deepcopy(asm)
    counts = sales["counts"]            # cell-key tuple -> total applications
    avg_premium = sales["avg_premium"]  # cell-key tuple -> average premium
    state_prem = sales["state_premiums"]

    # ---- distribution: per-dimension marginal weights from counts ----
    total = sum(counts.values()) or 1.0
    for dim, idx in _DIM_INDEX.items():
        marg = defaultdict(float)
        for k, c in counts.items():
            marg[k[idx]] += c
        if not marg:
            continue
        weights = {v: round(c / total, 8) for v, c in marg.items()}
        target = {"issue_age": "by_issue_age", "uw": "uw"}.get(dim, dim)
        setattr(new.distribution, target, weights)

    # ---- premium: log main-effects decomposition weighted by count ----
    obs = [(k, math.log(p), counts.get(k, 0.0))
           for k, p in avg_premium.items() if p > 0 and counts.get(k, 0.0) > 0]
    if obs:
        wtot = sum(w for _, _, w in obs) or 1.0
        mu = sum(lp * w for _, lp, w in obs) / wtot

        def eff(idx):
            g = defaultdict(lambda: [0.0, 0.0])
            for k, lp, w in obs:
                g[k[idx]][0] += lp * w
                g[k[idx]][1] += w
            return {v: (s / w - mu) for v, (s, w) in g.items() if w}

        p = new.premium
        p.base_by_issue_age = {int(a): round(math.exp(mu + e), 4)
                               for a, e in eff(0).items()}
        p.gender_factor = {v: round(math.exp(e), 6) for v, e in eff(1).items()}
        p.plan_factor = {v: round(math.exp(e), 6) for v, e in eff(2).items()}
        p.uw_factor = {v: round(math.exp(e), 6) for v, e in eff(3).items()}
        p.preferred_factor = {v: round(math.exp(e), 6) for v, e in eff(4).items()}
        p.hhd_factor = {v: round(math.exp(e), 6) for v, e in eff(5).items()}

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


def apply_claims(asm: AssumptionSet, claims: dict) -> AssumptionSet:
    """Return a copy of ``asm`` with base claim-cost levels (per plan) and state
    factors recalibrated to observed experience."""
    new = copy.deepcopy(asm)
    morb = new.morbidity

    # per-plan level factor: observed duration-1 cc vs current (gender-blended) table
    dur1 = claims["dur1_cc"]
    for plan in morb.plans:
        ratios = []
        for band, obs in dur1.get(plan, {}).items():
            if obs <= 0:
                continue
            cur = 0.5 * (L.base_claim_cost(asm, "M", band, plan)
                         + L.base_claim_cost(asm, "F", band, plan))
            if cur > 0:
                ratios.append(obs / cur)
        if ratios:
            factor = sum(ratios) / len(ratios)
            morb.base_cc_male[plan] = [v * factor for v in morb.base_cc_male[plan]]
            morb.base_cc_female[plan] = [v * factor for v in morb.base_cc_female[plan]]

    # state factors from observed relativities (keep existing where not observed)
    for state, f in claims["state_factors"].items():
        if f > 0:
            morb.state_factors[state] = f
    return new
