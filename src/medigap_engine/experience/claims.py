"""Derive morbidity (claim-cost) assumptions from raw claims experience.

Each claims row is roughly one month of exposure for ``cnt`` lives (the workbook
confirms ``earned ≈ annualized_prem / 12``), so a life-year of exposure is
``cnt / 12``. Observed annual claim cost per life is therefore
``sum(adj_claims) / sum(cnt/12)`` over any grouping.

Outputs are *relativities* and duration-1 levels suitable for recalibrating the
existing assumption tables (see ``port.py``); they intentionally do not rebuild
the full attained-age curve.
"""
from __future__ import annotations

from .schema import normalize_claims

MONTHS_PER_YEAR = 12.0


def _cc(claims: float, exposure_life_years: float) -> float:
    return claims / exposure_life_years if exposure_life_years else 0.0


def derive_morbidity(rows) -> dict:
    """Aggregate claims rows into observed claim-cost metrics.

    Returns a dict with:
      * ``dur1_cc[plan][issue_age]``   observed annual claim cost/life, duration 1
      * ``state_factors[state]``       claim cost relative to the 'All' book
      * ``selection[(uw, duration)]``  claim cost relative to all-UW at that duration
      * ``aging_by_duration[d]``       claim cost at duration d / duration 1 (de-trended-ish)
      * ``overall_cc``, ``n_rows``, ``total_exposure``
    """
    canon = normalize_claims(rows)

    def acc():
        return {"claims": 0.0, "exp": 0.0}

    by_plan_age_d1: dict = {}
    by_state: dict = {}
    by_uw_dur: dict = {}
    by_dur: dict = {}
    total = acc()

    for r in canon:
        exp = r["cnt"] / MONTHS_PER_YEAR
        cl = r["adj_claims"]
        total["claims"] += cl
        total["exp"] += exp

        by_state.setdefault(r["state"], acc())
        by_state[r["state"]]["claims"] += cl
        by_state[r["state"]]["exp"] += exp

        by_uw_dur.setdefault((r["uw_class"], r["duration"]), acc())
        by_uw_dur[(r["uw_class"], r["duration"])]["claims"] += cl
        by_uw_dur[(r["uw_class"], r["duration"])]["exp"] += exp

        by_dur.setdefault(r["duration"], acc())
        by_dur[r["duration"]]["claims"] += cl
        by_dur[r["duration"]]["exp"] += exp

        if r["duration"] == 1:
            by_plan_age_d1.setdefault(r["plan"], {}).setdefault(r["issue_age"], acc())
            cell = by_plan_age_d1[r["plan"]][r["issue_age"]]
            cell["claims"] += cl
            cell["exp"] += exp

    overall = _cc(total["claims"], total["exp"])

    dur1_cc = {p: {a: _cc(v["claims"], v["exp"]) for a, v in ages.items()}
               for p, ages in by_plan_age_d1.items()}

    # state factors relative to the All-book observed claim cost
    state_factors = {s: (_cc(v["claims"], v["exp"]) / overall if overall else 1.0)
                     for s, v in by_state.items()}

    # selection relative to the all-UW claim cost at each duration
    dur_cc = {d: _cc(v["claims"], v["exp"]) for d, v in by_dur.items()}
    selection = {}
    for (uw, d), v in by_uw_dur.items():
        base = dur_cc.get(d, 0.0)
        selection[(uw, d)] = (_cc(v["claims"], v["exp"]) / base) if base else 1.0

    # aging: claim cost by duration relative to duration 1
    cc1 = dur_cc.get(1, 0.0)
    aging_by_duration = {d: (cc / cc1 if cc1 else 1.0) for d, cc in dur_cc.items()}

    return {
        "dur1_cc": dur1_cc,
        "state_factors": state_factors,
        "selection": selection,
        "aging_by_duration": aging_by_duration,
        "overall_cc": overall,
        "n_rows": len(canon),
        "total_exposure": total["exp"],
    }
