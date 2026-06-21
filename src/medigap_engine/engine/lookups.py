"""Assumption lookups used by the per-cell projection.

These translate the workbook's INDEX/MATCH/SUMIFS lookups into plain functions.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet, derive_two_level, normalized_factors


def base_claim_cost(asm: AssumptionSet, gender: str, attained_age: int, plan: str) -> float:
    """Base (gender-blend) claim cost by attained age and plan, scaled by the
    gender relativity normalised against the gender mix. Ages outside the table
    clamp to the nearest end; intermediate ages use the nearest age at or below."""
    morb = asm.morbidity
    ages = morb.ages
    table = morb.base_cc[plan]
    a = max(ages[0], min(attained_age, ages[-1]))
    if a in ages:
        idx = ages.index(a)
    else:
        idx = 0
        for i, ag in enumerate(ages):
            if ag <= a:
                idx = i
    gfac = normalized_factors(morb.gender_cc_rel, asm.distribution.gender)
    return table[idx] * gfac.get(gender, 1.0)


def premium_for_cell(asm: AssumptionSet, key, state: str) -> float:
    """Premium = base(blend at plan G) × plan relativity (G-anchored) × mix-normalised
    gender/preferred/hhd/uw relativities × raw state factor."""
    p = asm.premium
    dist = asm.distribution
    base = p.base_for_age(key.issue_age)
    plan_f = p.plan_rel.get(key.plan, 1.0)
    g = normalized_factors(p.gender_rel, dist.gender).get(key.gender, 1.0)
    pr = normalized_factors(p.preferred_rel, dist.preferred).get(key.preferred, 1.0)
    h = normalized_factors(p.hhd_rel, dist.hhd).get(key.hhd, 1.0)
    uw = normalized_factors(p.uw_rel, dist.uw).get(key.uw_class, 1.0)
    sf = p.state_factor.get(state, p.state_factor.get("All", 1.0))
    return base * plan_f * g * pr * h * uw * sf


def claim_class_factors(asm: AssumptionSet, uw_class: str, preferred: str, hhd: str) -> float:
    """Preferred factor (applied only for UW class) times the household-discount
    factor. Both are derived from a differential and the distribution mix so the
    weighted mean is 1 (the base claim cost already carries the blend)."""
    morb = asm.morbidity
    dist = asm.distribution
    pref_f = derive_two_level(dist.preferred.get("Y", 0.5), morb.preferred_diff)
    hhd_f = derive_two_level(dist.hhd.get("Y", 0.5), morb.hhd_diff)
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
