"""Assumption lookups used by the per-cell projection.

These translate the workbook's INDEX/MATCH/SUMIFS lookups into plain functions.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet


def base_claim_cost(asm: AssumptionSet, gender: str, attained_age: int, plan: str) -> float:
    """Workbook M column: INDEX into the gender base-cost table by attained age and
    plan. Ages outside the table clamp to the nearest end; intermediate ages use
    the nearest age at or below (the table is already age-by-age)."""
    morb = asm.morbidity
    ages = morb.ages
    table = morb.base_cc(gender)[plan]
    a = max(ages[0], min(attained_age, ages[-1]))
    # exact, else nearest age at or below
    if a in ages:
        idx = ages.index(a)
    else:
        idx = 0
        for i, ag in enumerate(ages):
            if ag <= a:
                idx = i
    return table[idx]


def claim_class_factors(asm: AssumptionSet, uw_class: str, preferred: str, hhd: str) -> float:
    """Workbook M column tail: preferred factor (applied only for UW class) times
    the household-discount factor (always applied)."""
    morb = asm.morbidity
    pref = morb.preferred_factor.get(preferred, 1.0) if uw_class == "UW" else 1.0
    hhd_f = morb.hhd_factor.get(hhd, 1.0)
    return pref * hhd_f


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
    table = asm.termination.base_lapse.get(uw_class) or asm.termination.base_lapse["UW"]
    d = min(duration, len(table)) - 1
    return table[d]


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
