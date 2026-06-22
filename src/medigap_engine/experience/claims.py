"""Derive morbidity (claim-cost) assumptions from raw claims experience.

Exposure is measured in **life-years**: a row's exposure is ``cnt * earned /
annualized_prem`` (count times the fraction-of-year of coverage the earned premium
implies), falling back to ``cnt / 12`` only when earned/annualized premium are not
supplied. This is correct whether the data is reported monthly, quarterly or
annually — using a hardcoded ``cnt / 12`` on non-monthly rows would understate
exposure and inflate the per-life claim cost. Observed annual claim cost per life is
``sum(adj_claims) / sum(exposure)`` over any grouping.

Claim costs are keyed by **issue age** (collapsed to the model's key issue-age bands
by ``normalize_claims``), matching how the engine indexes base claim cost — not by
attained age. Outputs are levels/relativities suitable for recalibrating the existing
assumption tables (see ``port.py``).
"""
from __future__ import annotations

from .schema import normalize_claims

MONTHS_PER_YEAR = 12.0


def exposure_life_years(row: dict) -> float:
    """Life-years of exposure for a claims row: ``cnt * earned/annualized_prem``
    (the earned fraction of a policy-year), or ``cnt / 12`` if premium is absent."""
    cnt = row.get("cnt", 0.0) or 0.0
    earned = row.get("earned", 0.0) or 0.0
    annual = row.get("annualized_prem", 0.0) or 0.0
    if earned > 0 and annual > 0:
        return cnt * (earned / annual)
    return cnt / MONTHS_PER_YEAR


def _cc(claims: float, exposure_life_years: float) -> float:
    return claims / exposure_life_years if exposure_life_years else 0.0


def derive_morbidity(rows) -> dict:
    """Aggregate claims rows into observed claim-cost metrics.

    Returns a dict with:
      * ``dur1_cc[plan][issue_age]``   observed annual claim cost/life, duration 1
      * ``base_cc_by_issue_age[plan][issue_age]``  observed cc/life by issue-age band
      * ``state_factors[state]``       claim cost relative to the 'All' book
      * ``selection[(uw, duration)]``  claim cost relative to all-UW at that duration
      * ``aging_by_duration[d]``       claim cost at duration d / duration 1
      * ``overall_cc``, ``n_rows``, ``total_exposure``
    """
    canon = normalize_claims(rows)

    def acc():
        return {"claims": 0.0, "exp": 0.0}

    by_plan_age_d1: dict = {}
    by_plan_issue: dict = {}         # (plan, issue age) -> cc, the base-cost level
    by_state: dict = {}
    by_gender: dict = {}
    by_uw_dur: dict = {}
    by_age_uw_dur: dict = {}         # (issue_age, uw, duration) -> for selection
    by_age: dict = {}                # issue_age -> for selection normalisation
    by_dur: dict = {}
    total = acc()

    for r in canon:
        exp = exposure_life_years(r)
        cl = r["adj_claims"]
        total["claims"] += cl
        total["exp"] += exp
        for d, key in ((by_state, r["state"]), (by_gender, r["gender"]),
                       (by_dur, r["duration"]), (by_age, r["issue_age"]),
                       (by_uw_dur, (r["uw_class"], r["duration"])),
                       (by_age_uw_dur, (r["issue_age"], r["uw_class"], r["duration"])),
                       (by_plan_issue, (r["plan"], r["issue_age"]))):
            cell = d.setdefault(key, acc())
            cell["claims"] += cl
            cell["exp"] += exp
        if r["duration"] == 1:
            cell = by_plan_age_d1.setdefault(r["plan"], {}).setdefault(r["issue_age"], acc())
            cell["claims"] += cl
            cell["exp"] += exp

    overall = _cc(total["claims"], total["exp"])
    dur1_cc = {p: {a: _cc(v["claims"], v["exp"]) for a, v in ages.items()}
               for p, ages in by_plan_age_d1.items()}

    # base claim-cost level by (plan, ISSUE age) — matches the engine's indexing
    base_cc_by_issue_age: dict = {}
    for (plan, age), v in by_plan_issue.items():
        base_cc_by_issue_age.setdefault(plan, {})[age] = _cc(v["claims"], v["exp"])

    # gender differential (male vs female), de-meaned by exposure
    g_cc = {g: _cc(v["claims"], v["exp"]) for g, v in by_gender.items()}
    gender_diff = (g_cc["M"] / g_cc["F"] - 1.0) if g_cc.get("F") else 0.0

    state_factors = {s: (_cc(v["claims"], v["exp"]) / overall if overall else 1.0)
                     for s, v in by_state.items()}

    dur_cc = {d: _cc(v["claims"], v["exp"]) for d, v in by_dur.items()}
    selection = {}
    for (uw, d), v in by_uw_dur.items():
        base = dur_cc.get(d, 0.0)
        selection[(uw, d)] = (_cc(v["claims"], v["exp"]) / base) if base else 1.0

    # selection by (issue_age, uw, duration), normalised within issue_age so it
    # captures the uw/duration pattern, not the level (level is in base_cc_by_issue_age)
    age_cc = {a: _cc(v["claims"], v["exp"]) for a, v in by_age.items()}
    selection_rows = []
    for (age, uw, d), v in by_age_uw_dur.items():
        base = age_cc.get(age, 0.0)
        factor = (_cc(v["claims"], v["exp"]) / base) if base else 1.0
        selection_rows.append({"issue_age": age, "uw": uw, "duration": d,
                               "factor": round(factor, 6)})

    cc1 = dur_cc.get(1, 0.0)
    aging_by_duration = {d: (cc / cc1 if cc1 else 1.0) for d, cc in dur_cc.items()}

    return {
        "dur1_cc": dur1_cc,
        "base_cc_by_issue_age": base_cc_by_issue_age,
        "gender_diff": round(gender_diff, 6),
        "state_factors": state_factors,
        "selection": selection,
        "selection_rows": selection_rows,
        "aging_by_duration": aging_by_duration,
        "overall_cc": overall,
        "n_rows": len(canon),
        "total_exposure": total["exp"],
    }

