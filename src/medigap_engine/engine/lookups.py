"""Assumption lookups used by the per-cell projection.

These translate the workbook's INDEX/MATCH/SUMIFS lookups into plain functions.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet, derive_two_level, normalized_factors


def base_claim_cost(asm: AssumptionSet, gender: str, age: int, plan: str,
                    state: str | None = None, bring_forward: bool = True) -> float:
    """Base (gender-blend) claim cost by **issue age** and plan, scaled by the gender
    relativity normalised against the gender mix and brought forward to the pricing
    period by the one-time claims pull-forward. Ages outside the table clamp to the
    nearest end; intermediate ages use the nearest age at or below. Pass
    ``bring_forward=False`` for the experience-level (best-estimate) cost, e.g. A/E."""
    morb = asm.morbidity
    ages = morb.ages
    table = morb.base_cc[plan]
    a = max(ages[0], min(age, ages[-1]))
    if a in ages:
        idx = ages.index(a)
    else:
        idx = 0
        for i, ag in enumerate(ages):
            if ag <= a:
                idx = i
    gfac = normalized_factors({"M": 1.0 + morb.gender_cc_diff, "F": 1.0},
                              asm.distribution.gender_mix(state))
    pf = asm.pull_forward
    bf = (1.0 + pf.claims_trend) ** pf.duration if bring_forward else 1.0
    return table[idx] * gfac.get(gender, 1.0) * bf


def premium_for_cell(asm: AssumptionSet, key, state: str) -> float:
    """Premium = base(blend at plan G) × plan relativity (G-anchored) × mix-normalised
    gender/preferred/hhd differentials and uw relativity × raw state factor, brought
    forward to the pricing period by the one-time premium pull-forward (same window
    as the claims pull-forward)."""
    p = asm.premium
    pf = asm.pull_forward
    bring_forward = (1.0 + pf.premium_trend) ** pf.duration
    # exact per-cell premium, still subject to the one-time premium pull-forward
    # (bring_forward is 1.0 when premium_trend is 0, so per-cell premiums are used
    # verbatim by default; a non-zero trend stresses them through to loss ratios)
    cp = p.cell_premiums.get(key.label())
    if cp:
        v = cp.get(state, cp.get("All"))
        if v is not None:
            return float(v) * bring_forward
    dist = asm.distribution
    base = p.base_for_age(key.issue_age)
    plan_f = p.plan_rel.get(key.plan, 1.0)
    g = normalized_factors({"M": 1.0 + p.gender_diff, "F": 1.0}, dist.gender_mix(state)).get(key.gender, 1.0)
    pr = normalized_factors({"N": 1.0 + p.preferred_diff, "Y": 1.0}, dist.preferred_mix(state)).get(key.preferred, 1.0)
    h = normalized_factors({"N": 1.0 + p.hhd_diff, "Y": 1.0}, dist.hhd_mix(state)).get(key.hhd, 1.0)
    uw = normalized_factors(p.uw_rel, dist.uw_mix(state)).get(key.uw_class, 1.0)
    sf = p.state_factor.get(state, p.state_factor.get("All", 1.0))
    return base * plan_f * g * pr * h * uw * sf * bring_forward


def claim_class_factors(asm: AssumptionSet, uw_class: str, preferred: str, hhd: str,
                        state: str | None = None) -> float:
    """Preferred factor (applied only for UW class) times the household-discount
    factor. Both are derived from a differential and the distribution mix so the
    weighted mean is 1 (the base claim cost already carries the blend)."""
    morb = asm.morbidity
    dist = asm.distribution
    # raw factors (workbook) take precedence over mix-normalised derivation
    pref_f = morb.preferred_factors or derive_two_level(dist.preferred_mix(state).get("Y", 0.5),
                                                        morb.preferred_diff)
    hhd_f = morb.hhd_factors or derive_two_level(dist.hhd_mix(state).get("Y", 0.5), morb.hhd_diff)
    pref = pref_f.get(preferred, 1.0) if uw_class == "UW" else 1.0
    return pref * hhd_f.get(hhd, 1.0)


def selection_factor(asm: AssumptionSet, issue_age: int, uw_class: str, duration: int) -> float:
    """Workbook N column SUMIFS over (issue_age, uw, duration). The workbook table
    only carries early durations; beyond its last duration we carry the last
    available factor forward (the workbook would otherwise return 0 and zero out
    claims, which is clearly unintended for a 30-year projection)."""
    rows = asm.morbidity.selection_factors
    # exact match
    for r in rows:
        if r["issue_age"] == issue_age and r["uw"] == uw_class and r["duration"] == duration:
            return r["factor"]
    # carry-forward last available duration for this (issue_age, uw)
    candidates = [r for r in rows if r["issue_age"] == issue_age and r["uw"] == uw_class]
    if candidates:
        last = max(candidates, key=lambda r: r["duration"])
        return last["factor"]
    return 1.0


def lapse_rate(asm: AssumptionSet, uw_class: str, duration: int) -> float:
    """Blended base lapse by duration, scaled by the UW-vs-other relativity
    normalised against the uw mix (so the blend is preserved)."""
    term = asm.termination
    d = min(duration, len(term.base_lapse)) - 1
    base = term.base_lapse[d]
    fi = min(duration, len(term.uw_lapse_rel)) - 1
    rel = term.uw_lapse_rel[fi]
    fac = normalized_factors({"UW": rel, "OE": 1.0, "GI": 1.0}, asm.distribution.uw)
    return base * fac.get(uw_class, 1.0)


def trend_year(asm: AssumptionSet, duration: int) -> float:
    t = asm.morbidity.trend_by_year
    return t[min(duration, len(t)) - 1]


def cc_aging_duration(asm: AssumptionSet, duration: int) -> float:
    """Antiselection (col P) aging factor by duration."""
    a = asm.morbidity.cc_aging_by_duration
    return a[min(duration, len(a)) - 1]


def aging_rerate(asm: AssumptionSet, attained_age: int) -> float:
    """Premium aging-rerate (col H) by attained age."""
    ages = asm.rerates.aging_rerate_by_age_ages
    fac = asm.rerates.aging_rerate_by_age_factor
    a = max(ages[0], min(attained_age, ages[-1]))
    if a in ages:
        return fac[ages.index(a)]
    idx = 0
    for i, ag in enumerate(ages):
        if ag <= a:
            idx = i
    return fac[idx]
