"""Apply experience-study results into the assumption / cell model ('Adopt').

Sales results replace per-cell distribution weights and premiums. Claims results
recalibrate the *level* of the base claim-cost tables per plan and the state
morbidity factors. Selection and claim-cost aging are surfaced in the UI for the
user to judge rather than auto-applied (best-estimate aging already lives in the
attained-age base-cost curve, distinct from the pricing antiselection load).
"""
from __future__ import annotations

import copy

from ..models.assumptions import AssumptionSet
from ..models.cell import CellKey, PricingCell
from ..engine import lookups as L


def apply_sales(cells: list[PricingCell], sales: dict) -> list[PricingCell]:
    """Return a new cell list with weights, base premium, and per-state premiums
    taken from the sales aggregation. Cells absent from the sales data get weight
    0; cells present in sales but not in the prior list are added."""
    existing = {(_k(c.key)): c for c in cells}
    keys = set(existing) | set(sales["weights"])
    out: list[PricingCell] = []
    for k in sorted(keys):
        weight = sales["weights"].get(k, 0.0)
        avg_prem = sales["avg_premium"].get(k)
        state_prem = sales["state_premiums"].get(k, {})
        prev = existing.get(k)
        base_prem = avg_prem if avg_prem else (prev.base_prem if prev else 0.0)
        key = CellKey(issue_age=k[0], gender=k[1], plan=k[2], uw_class=k[3],
                      preferred=k[4], hhd=k[5])
        out.append(PricingCell(key=key, base_prem=base_prem, weight=weight,
                               state_premiums=dict(state_prem)))
    return out


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


def _k(key: CellKey) -> tuple:
    return (key.issue_age, key.gender, key.plan, key.uw_class, key.preferred, key.hhd)
