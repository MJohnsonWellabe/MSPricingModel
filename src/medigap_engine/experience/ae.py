"""Actual-to-expected (A/E) analysis for morbidity.

Expected claim cost per life uses the current best-estimate assumptions (base
claim cost x class factors x selection x state factor x compounded trend). The
pricing antiselection load (column P) is excluded — A/E measures experience
against best estimate, not the priced margin.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet
from ..engine import lookups as L
from .schema import normalize_claims
from .claims import exposure_life_years


def _trend_factor(asm: AssumptionSet, duration: int) -> float:
    # base claim cost is already pulled forward to the year-1 level; the projection
    # trend compounds from year 1->2 onward (year-1 factor is 1.0).
    O = 1.0
    for d in range(2, duration + 1):
        O *= 1.0 + L.trend_year(asm, d)
    return O


def expected_cc_per_life(asm: AssumptionSet, gender: str, issue_age: int,
                         plan: str, uw: str, duration: int, state: str) -> float:
    # base claim cost is indexed by ISSUE age (matches the engine), not attained age
    if gender in ("M", "F"):
        base = L.base_claim_cost(asm, gender, issue_age, plan)
    else:  # unknown gender -> blend male/female
        base = 0.5 * (L.base_claim_cost(asm, "M", issue_age, plan)
                      + L.base_claim_cost(asm, "F", issue_age, plan))
    sel = L.selection_factor(asm, issue_age, uw, duration)
    state_f = asm.morbidity.state_factors.get(state, asm.morbidity.state_factors.get("All", 1.0))
    return base * sel * _trend_factor(asm, duration) * state_f


def actual_to_expected(rows, asm: AssumptionSet, by=("state",)) -> list[dict]:
    """Aggregate A/E by the requested dimensions.

    ``by`` is any subset of ('state','plan','issue_age','uw_class','duration').
    Returns rows of {dims..., actual, expected, ae, exposure}.
    """
    canon = normalize_claims(rows)
    groups: dict[tuple, dict] = {}
    for r in canon:
        exp_ly = exposure_life_years(r)
        actual = r["adj_claims"]
        expected = expected_cc_per_life(
            asm, r["gender"], r["issue_age"], r["plan"], r["uw_class"],
            r["duration"], r["state"]) * exp_ly
        key = tuple(r[d] for d in by)
        g = groups.setdefault(key, {"actual": 0.0, "expected": 0.0, "exposure": 0.0})
        g["actual"] += actual
        g["expected"] += expected
        g["exposure"] += exp_ly

    out = []
    for key, g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        row = {d: key[i] for i, d in enumerate(by)}
        row["actual"] = g["actual"]
        row["expected"] = g["expected"]
        row["exposure"] = g["exposure"]
        row["ae"] = (g["actual"] / g["expected"]) if g["expected"] else float("nan")
        out.append(row)
    return out
