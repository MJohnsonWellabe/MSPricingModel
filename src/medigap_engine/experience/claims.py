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

import math

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
    by_state_cell_d1: dict = {}      # (state,plan,issue_age,gender,uw) dur-1 -> isolated state factor
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
            sk = (r["state"], r["plan"], r["issue_age"], r["gender"], r["uw_class"])
            c4 = by_state_cell_d1.setdefault(sk, acc())
            c4["claims"] += cl
            c4["exp"] += exp

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

    # state morbidity factor: ISOLATED (mix-free) DURATION-1 relativity via a multivariate
    # fit over (state, plan, issue_age, gender, uw). base_cc is the national duration-1 blend
    # and each state's own age/UW/plan mix is already applied through the distribution grid,
    # so the state factor must be the pure state effect (holding the cell fixed), not the
    # raw state/national average — which is confounded by the state's mix and would
    # double-count it (e.g. a state skewed to young/UW cells looks cheap on average but runs
    # above national cell-for-cell). Normalised to an exposure-weighted mean of 1.0.
    sobs = [(k, _cc(v["claims"], v["exp"]), v["exp"])
            for k, v in by_state_cell_d1.items() if v["exp"] > 0]
    sfit = fit_main_effects(sobs, n_dims=5)["factors"][0] if sobs else {}
    sexp: dict = {}
    for (st, _p, _a, _g, _u), v in by_state_cell_d1.items():
        sexp[st] = sexp.get(st, 0.0) + v["exp"]
    wmean = (sum(sfit.get(s, 1.0) * e for s, e in sexp.items()) / sum(sexp.values())
             if sexp else 1.0) or 1.0
    state_factors = {s: round(sfit.get(s, 1.0) / wmean, 6) for s in sexp}

    # ATTAINED-AGE aging slope: exposure-weighted log-linear fit of ln(cc) on attained age
    # over (attained_age, gender, plan, uw). A single robust morbidity %/yr — used for the
    # aging curve AND to net aging out of the selection wear-off so they don't double-count.
    # (Walking a noisy attained-age curve out from one reference age previously caught a local
    # +11% blip; the slope here is ~1-2%/yr.)
    att_cc: dict = {}
    for (att, _g, _p, _u), v in by_cell_attained.items():
        c = att_cc.setdefault(att, {"claims": 0.0, "exp": 0.0})
        c["claims"] += v["claims"]
        c["exp"] += v["exp"]
    pts = [(a, math.log(c["claims"] / c["exp"]), c["exp"])
           for a, c in att_cc.items() if c["exp"] > 0 and c["claims"] > 0]
    aging_rate = 0.0
    if len(pts) >= 2:
        sw = sum(w for _a, _y, w in pts) or 1.0
        mx = sum(w * a for a, _y, w in pts) / sw
        my = sum(w * y for _a, y, w in pts) / sw
        sxx = sum(w * (a - mx) ** 2 for a, _y, w in pts)
        sxy = sum(w * (a - mx) * (y - my) for a, y, w in pts)
        if sxx > 0:
            aging_rate = max(0.0, math.exp(sxy / sxx) - 1.0)
    ref_issue = (round(sum(a * e for a, e in issue_exp.items()) / sum(issue_exp.values()))
                 if issue_exp else 65)

    # selection LEVEL at duration 1 by (issue_age, uw), referenced to the all-UW/dur1 blend
    # (decent exposure: OE ramps up with issue age as it antiselects, UW < 1, GI > 1). The
    # DURATION wear-off comes from the well-populated (uw, duration) aggregation, net of the
    # aging slope so it isn't double-counted with the engine's aging (P_d). Estimating the
    # wear-off per (issue_age, uw, duration) cell was too thin and injected noise (UW jumping
    # 0.54->0.94). claim = base_cc(issue_age) × selection.
    allcell_d1 = {a: _cc(sum(by_plan_age_d1[p][a]["claims"] for p in by_plan_age_d1 if a in by_plan_age_d1[p]),
                         sum(by_plan_age_d1[p][a]["exp"] for p in by_plan_age_d1 if a in by_plan_age_d1[p]))
                  for a in {a for p in by_plan_age_d1 for a in by_plan_age_d1[p]}}

    def _ref(age):
        return allcell_d1.get(age) or 0.0

    dur_cc = {d: _cc(v["claims"], v["exp"]) for d, v in by_dur.items()}
    uwdur_cc = {(uw, d): _cc(v["claims"], v["exp"]) for (uw, d), v in by_uw_dur.items()}
    durs = sorted({d for (_uw, d) in by_uw_dur})
    uws = {u for (u, _d) in by_uw_dur}
    # duration wear-off per UW class, net of the aging slope (so dur-1 = 1.0)
    wear = {}
    for uw in uws:
        c1 = uwdur_cc.get((uw, 1), 0.0)
        for d in durs:
            cd = uwdur_cc.get((uw, d), 0.0)
            wear[(uw, d)] = (cd / c1 / (1.0 + aging_rate) ** (d - 1)) if c1 else 1.0
    # duration-1 selection level by (issue_age, uw)
    sel_d1 = {}
    for (age, uw, d), v in by_age_uw_dur.items():
        if d == 1:
            base = _ref(age)
            sel_d1[(age, uw)] = (_cc(v["claims"], v["exp"]) / base) if base else 1.0
    # book-wide (uw, duration) view = book dur-1 level × wear-off
    selection = {}
    selection_exposure = {}
    for (uw, d), v in by_uw_dur.items():
        lvl = (uwdur_cc.get((uw, 1), 0.0) / dur_cc.get(1, 1.0)) if dur_cc.get(1) else 1.0
        selection[(uw, d)] = lvl * wear.get((uw, d), 1.0)
        selection_exposure[(uw, d)] = v["exp"]
    # full grid = duration-1 level (by issue_age, uw) × duration wear-off (by uw); carry the
    # (uw, duration) exposure for the credibility blend on adopt
    selection_rows = []
    for (age, uw) in sel_d1:
        for d in durs:
            factor = sel_d1[(age, uw)] * wear.get((uw, d), 1.0)
            selection_rows.append({"issue_age": age, "uw": uw, "duration": d,
                                   "factor": round(factor, 6),
                                   "exposure": round(by_uw_dur.get((uw, d), {"exp": 0.0})["exp"], 2)})

    cc1 = dur_cc.get(1, 0.0)
    aging_by_duration = {d: (cc / cc1 if cc1 else 1.0) for d, cc in dur_cc.items()}

    # gender differential isolated by the multivariate fit (holds age/plan/uw fixed)
    fobs = [(k, _cc(v["claims"], v["exp"]), v["exp"]) for k, v in by_cell_full.items()
            if v["exp"] > 0]
    gender_diff_isolated = differential(fit_main_effects(fobs, n_dims=5)["factors"], 1, "M", "F")

    # AGING curve from the constant attained-age slope (computed above): monotone
    # (1 + aging_rate) ** (duration - 1). The engine applies it as the per-duration aging
    # increment (cc_aging), separately from the projection trend (O_d) and the UW selection
    # wear-off (which is already net of this slope).
    aging_curve = {d: round((1.0 + aging_rate) ** (d - 1), 6) for d in range(1, 31)}

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

