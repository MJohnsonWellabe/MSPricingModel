"""Derive morbidity (claim-cost) assumptions from raw claims experience.

Exposure is measured in **life-years**: a row's exposure is its explicit ``exposure``
column when supplied, otherwise the ``cnt`` column (each row already carries
annualized exposure / life-years, not a monthly headcount). Observed annual claim cost
per life is ``sum(adj_claims) / sum(exposure)`` over any grouping. (A hardcoded
``cnt/12`` — or deriving exposure from ``earned/annualized_prem`` — over-divides this
data, since ``annualized_prem ≈ 12×earned``, and inflates the cost ~12×.)

Claim costs are keyed by **issue age** (collapsed to the model's key issue-age bands
by ``normalize_claims``), matching how the engine indexes base claim cost.
"""
from __future__ import annotations

from .decomp import differential, fit_main_effects
from .schema import normalize_claims


def exposure_life_years(row: dict) -> float:
    """Life-years of exposure for a claims row: the explicit ``exposure`` column if
    present, else ``cnt`` (which already carries annualized life-years of exposure)."""
    exp = row.get("exposure")
    if exp:
        return float(exp)
    return float(row.get("cnt", 0.0) or 0.0)


def _cc(claims: float, exposure_life_years: float) -> float:
    return claims / exposure_life_years if exposure_life_years else 0.0


def _isotonic(values: list, weights: list) -> list:
    """Weighted monotone non-decreasing fit (pool-adjacent-violators). Smooths a noisy
    increasing series (e.g. claim cost by attained age) into a clean monotone curve."""
    blocks = []  # each: [weighted_sum, weight, count]
    for v, w in zip(values, weights):
        w = w or 1e-9
        blocks.append([v * w, w, 1])
        while len(blocks) >= 2 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, wt, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += wt
            blocks[-1][2] += n
    out = []
    for s, wt, n in blocks:
        out.extend([s / wt] * n)
    return out


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
    by_plan_issue: dict = {}         # (plan, issue age) -> cc (all durations), diagnostics
    by_state: dict = {}
    by_gender: dict = {}
    by_uw_dur: dict = {}
    by_age_uw_dur: dict = {}         # (issue_age, uw, duration) -> for selection
    by_age: dict = {}                # issue_age -> for selection normalisation
    by_dur: dict = {}
    by_cell_full: dict = {}          # (issue_age,gender,plan,uw,duration) -> for the fit
    by_cell_attained: dict = {}      # (attained_age,gender,plan,uw) -> for the aging fit
    issue_exp: dict = {}             # issue_age -> exposure, for the reference issue age
    total = acc()

    for r in canon:
        exp = exposure_life_years(r)
        cl = r["adj_claims"]
        total["claims"] += cl
        total["exp"] += exp
        attained = r["issue_age"] + r["duration"] - 1
        issue_exp[r["issue_age"]] = issue_exp.get(r["issue_age"], 0.0) + exp
        fkey = (r["issue_age"], r["gender"], r["plan"], r["uw_class"], r["duration"])
        akey = (attained, r["gender"], r["plan"], r["uw_class"])
        for d, key in ((by_state, r["state"]), (by_gender, r["gender"]),
                       (by_dur, r["duration"]), (by_age, r["issue_age"]),
                       (by_uw_dur, (r["uw_class"], r["duration"])),
                       (by_age_uw_dur, (r["issue_age"], r["uw_class"], r["duration"])),
                       (by_plan_issue, (r["plan"], r["issue_age"])),
                       (by_cell_full, fkey), (by_cell_attained, akey)):
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

    # base claim-cost level by (plan, ISSUE age) = the ALL-UW, DURATION-1 blended claim cost
    # (matches a direct duration-1 pull from the data, and the engine's indexing: base_cc is
    # applied constant across duration, with the durational and UW-class pattern carried by
    # selection × aging — including OE's antiselection ramp by issue age). Exposure behind
    # each band is retained for credibility weighting.
    base_cc_by_issue_age: dict = {}
    base_cc_exposure: dict = {}
    for plan, ages in dur1_cc.items():
        for age, cc in ages.items():
            base_cc_by_issue_age.setdefault(plan, {})[age] = cc
            base_cc_exposure.setdefault(plan, {})[age] = by_plan_age_d1[plan][age]["exp"]

    # gender differential (male vs female), de-meaned by exposure
    g_cc = {g: _cc(v["claims"], v["exp"]) for g, v in by_gender.items()}
    gender_diff = (g_cc["M"] / g_cc["F"] - 1.0) if g_cc.get("F") else 0.0

    state_factors = {s: (_cc(v["claims"], v["exp"]) / overall if overall else 1.0)
                     for s, v in by_state.items()}

    # selection is referenced to the ALL-UW / duration-1 blended claim level by issue age, so
    # the UW-mix-weighted selection ≈ 1.0 at duration 1 (OE ramps up with issue age as it
    # antiselects, UW < 1, GI > 1) — matching the engine: claim = base_cc(issue_age) × selection.
    allcell_d1 = {a: _cc(sum(by_plan_age_d1[p][a]["claims"] for p in by_plan_age_d1 if a in by_plan_age_d1[p]),
                         sum(by_plan_age_d1[p][a]["exp"] for p in by_plan_age_d1 if a in by_plan_age_d1[p]))
                  for a in {a for p in by_plan_age_d1 for a in by_plan_age_d1[p]}}

    def _ref(age):
        return allcell_d1.get(age) or 0.0

    dur_cc = {d: _cc(v["claims"], v["exp"]) for d, v in by_dur.items()}
    selection = {}            # (uw, duration) -> factor on the all-UW/dur1 reference (book-wide)
    selection_exposure = {}
    uwdur_cc = {(uw, d): _cc(v["claims"], v["exp"]) for (uw, d), v in by_uw_dur.items()}
    # exposure-weighted all-UW/dur1 reference across ages for the book-wide (uw, dur) view
    d1_tot = sum(by_plan_age_d1[p][a]["claims"] for p in by_plan_age_d1 for a in by_plan_age_d1[p])
    d1_exp = sum(by_plan_age_d1[p][a]["exp"] for p in by_plan_age_d1 for a in by_plan_age_d1[p])
    ref_book = (d1_tot / d1_exp) if d1_exp else (dur_cc.get(1, 0.0) or 1.0)
    for (uw, d), v in by_uw_dur.items():
        selection[(uw, d)] = (uwdur_cc[(uw, d)] / ref_book) if ref_book else 1.0
        selection_exposure[(uw, d)] = v["exp"]

    # selection by (issue_age, uw, duration) on the all-UW/dur1 reference; carry exposure
    selection_rows = []
    for (age, uw, d), v in by_age_uw_dur.items():
        base = _ref(age)
        factor = (_cc(v["claims"], v["exp"]) / base) if base else 1.0
        selection_rows.append({"issue_age": age, "uw": uw, "duration": d,
                               "factor": round(factor, 6), "exposure": round(v["exp"], 2)})

    cc1 = dur_cc.get(1, 0.0)
    aging_by_duration = {d: (cc / cc1 if cc1 else 1.0) for d, cc in dur_cc.items()}

    # gender differential isolated by the multivariate fit (holds age/plan/uw fixed)
    fobs = [(k, _cc(v["claims"], v["exp"]), v["exp"]) for k, v in by_cell_full.items()
            if v["exp"] > 0]
    gender_diff_isolated = differential(fit_main_effects(fobs, n_dims=5)["factors"], 1, "M", "F")

    # AGING from the ATTAINED-AGE progression (claims rise with age), isolated over
    # (attained_age, gender, plan, uw). The duration signal is unreliable here (the data
    # only has ~6 policy durations). The attained-age claim-cost factors are smoothed to a
    # monotone curve (weighted isotonic / PAVA) and walked out from a reference
    # (exposure-weighted) issue age, so the aging curve is monotone >= 1.
    aobs = [(k, _cc(v["claims"], v["exp"]), v["exp"]) for k, v in by_cell_attained.items()
            if v["exp"] > 0]
    afac = fit_main_effects(aobs, n_dims=4)["factors"][0]   # attained-age factor
    att_exp: dict = {}
    for (att, _g, _p, _u), v in by_cell_attained.items():
        att_exp[att] = att_exp.get(att, 0.0) + v["exp"]
    ref_issue = (round(sum(a * e for a, e in issue_exp.items()) / sum(issue_exp.values()))
                 if issue_exp else 65)
    aging_curve: dict = {}
    if afac:
        ages = sorted(afac)
        smooth = dict(zip(ages, _isotonic([afac[a] for a in ages],
                                          [att_exp.get(a, 1.0) for a in ages])))
        amin, amax = ages[0], ages[-1]

        def _f(a):
            a = max(amin, min(a, amax))
            return smooth.get(a) or smooth[min(smooth, key=lambda x: abs(x - a))]

        base_a = _f(ref_issue) or 1.0
        for d in range(1, 31):
            aging_curve[d] = round(max(1.0, _f(ref_issue + d - 1) / base_a), 6)

    return {
        "dur1_cc": dur1_cc,
        "base_cc_by_issue_age": base_cc_by_issue_age,
        "base_cc_exposure": base_cc_exposure,
        "gender_diff": round(gender_diff, 6),
        "gender_diff_isolated": round(gender_diff_isolated, 6),
        "state_factors": state_factors,
        "selection": selection,
        "selection_exposure": selection_exposure,
        "selection_rows": selection_rows,
        "aging_by_duration": aging_by_duration,
        "aging_curve": aging_curve,
        "aging_ref_issue_age": ref_issue,
        "overall_cc": overall,
        "n_rows": len(canon),
        "total_exposure": total["exp"],
    }

