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

from ..engine import lookups as L
from ..models.assumptions import AssumptionSet
from .credibility import blend, credibility_z
from .decomp import differential, fit_main_effects

# index of each dimension within the cell-key tuple used by aggregate_sales
_DIM_INDEX = {"issue_age": 0, "gender": 1, "plan": 2, "uw": 3, "preferred": 4, "hhd": 5}


def _cell_label(k) -> str:
    """Cell-key tuple (issue_age,gender,plan,uw,preferred,hhd) -> CellKey label."""
    age, g, plan, uw, pref, hhd = k
    return f"{int(age)}{g}-{plan}-{uw}-P{pref}-H{hhd}"


def _blend_grids(own: dict, target: dict, z: float) -> dict:
    """Credibility-blend two distribution blocks: z*own + (1-z)*target, renormalised."""
    out = {}
    # joint grid
    joint: dict = {}
    keys = set(own["joint"]) | set(target["joint"])
    tot = 0.0
    for pl in keys:
        oa, ta = own["joint"].get(pl, {}), target["joint"].get(pl, {})
        for a in set(oa) | set(ta):
            ow, tw = oa.get(a, {}), ta.get(a, {})
            for u in set(ow) | set(tw):
                w = blend(ow.get(u, 0.0), tw.get(u, 0.0), z)
                if w:
                    joint.setdefault(pl, {}).setdefault(a, {})[u] = w
                    tot += w
    tot = tot or 1.0
    out["joint"] = {pl: {a: {u: round(w / tot, 8) for u, w in uws.items()}
                         for a, uws in ages.items()} for pl, ages in joint.items()}
    for dim in ("gender", "preferred", "hhd"):
        od, td = own.get(dim, {}), target.get(dim, {})
        m = {v: blend(od.get(v, 0.0), td.get(v, 0.0), z) for v in set(od) | set(td)}
        s = sum(m.values()) or 1.0
        out[dim] = {v: round(w / s, 8) for v, w in m.items()}
    return out


def _distribution_block(counts: dict) -> dict:
    """Build a {joint, gender, preferred, hhd} distribution block from cell-key counts
    (joint plan x issue-age x UW grid + independent gender/preferred/HHD marginals,
    each normalised to sum to 1)."""
    total = sum(counts.values()) or 1.0
    grid: dict[str, dict[str, dict[str, float]]] = {}
    for k, c in counts.items():
        age, _g, plan, uw, _p, _h = k  # tuple order per _DIM_INDEX
        ages = grid.setdefault(str(plan), {}).setdefault(str(int(age)), {})
        ages[str(uw)] = ages.get(str(uw), 0.0) + c / total
    joint = {pl: {a: {u: round(w, 8) for u, w in uws.items()} for a, uws in ages.items()}
             for pl, ages in grid.items()}
    out = {"joint": joint}
    for dim in ("gender", "preferred", "hhd"):
        marg: dict = defaultdict(float)
        for k, c in counts.items():
            marg[k[_DIM_INDEX[dim]]] += c
        out[dim] = {v: round(c / total, 8) for v, c in marg.items()}
    return out


def apply_sales(asm: AssumptionSet, sales: dict, parts=("distribution", "premium"),
                distribution_cred_standard: float = 1000.0) -> AssumptionSet:
    """Return a copy of ``asm`` with distribution weight factors and/or the premium
    factor model recalibrated from the sales aggregation. ``parts`` selects which
    blocks to adopt. Per-state grids are credibility-blended toward the average of
    their like-type (Special Enrollment Period vs regular) states."""
    new = copy.deepcopy(asm)
    parts = set(parts)
    counts = sales["counts"]            # cell-key tuple -> total applications
    avg_premium = sales["avg_premium"]  # cell-key tuple -> average premium
    state_prem = sales["state_premiums"]
    state_counts = sales.get("state_counts", {})   # cell-key -> {state: count}

    # ---- distribution: a national joint plan x issue-age x UW grid + gender/preferred/
    # HHD marginals, AND a per-state grid blended toward the like-type average ----
    if "distribution" in parts and counts:
        nat = _distribution_block(counts)
        new.distribution.joint = nat["joint"]
        for dim in ("gender", "preferred", "hhd"):
            setattr(new.distribution, dim, nat[dim])
        # per-state cell counts
        by_state_counts: dict = defaultdict(dict)
        state_total: dict = defaultdict(float)
        for k, per_state in state_counts.items():
            for s, c in per_state.items():
                by_state_counts[s][k] = c
                state_total[s] += c
        # group states into SEP (Special Enrollment Period) vs regular and form each group's average grid
        sep = set(new.distribution.sep_rule_states or [])
        group_counts = {"sep": defaultdict(float), "reg": defaultdict(float)}
        for s, ck in by_state_counts.items():
            g = "sep" if s in sep else "reg"
            for k, c in ck.items():
                group_counts[g][k] += c
        group_grid = {g: _distribution_block(c) for g, c in group_counts.items() if c}
        # each state's own grid, credibility-blended toward its group's average grid
        new.distribution.by_state = {}
        for s, ck in by_state_counts.items():
            if not ck:
                continue
            own = _distribution_block(ck)
            g = "sep" if s in sep else "reg"
            target = group_grid.get(g, nat)
            z = credibility_z(state_total[s], distribution_cred_standard)
            new.distribution.by_state[s] = _blend_grids(own, target, z)
        # cross-state new-business volume shares, for the portfolio "(combined)" weighting
        tot = sum(state_total.values())
        if tot > 0:
            new.distribution.state_weights = {s: round(c / tot, 8)
                                              for s, c in state_total.items()}

    # ---- premium: ISOLATED multivariate main-effects fit (key dims 0=age, 1=gender,
    # 2=plan, 3=uw, 4=preferred, 5=hhd), so each differential holds the others fixed
    # rather than reading a confounded marginal ----
    obs = [(k, p, counts.get(k, 0.0))
           for k, p in avg_premium.items() if p > 0 and counts.get(k, 0.0) > 0]
    if "premium" in parts and obs:
        fit = fit_main_effects(obs, n_dims=6)
        factors, logeff, baseline = fit["factors"], fit["log_effects"], fit["baseline"]
        plan_g = factors[2].get("G", 1.0) or 1.0

        p = new.premium
        # base = blend at plan G; plan relativities anchored at G = 1.0
        p.base_by_issue_age = {int(a): round(baseline * f * plan_g, 4)
                               for a, f in factors[0].items()}
        p.plan_rel = {v: round(f / plan_g, 6) for v, f in factors[2].items()}
        p.uw_rel = {v: round(f, 6) for v, f in factors[3].items()}
        p.gender_diff = round(differential(factors, 1, "M", "F"), 6)
        p.preferred_diff = round(differential(factors, 4, "N", "Y"), 6)
        p.hhd_diff = round(differential(factors, 5, "N", "Y"), 6)
        _ = logeff  # (additive effects available if needed)

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

        # per-cell premiums from the sales averages, so adopting premiums actually moves
        # priced premiums (the per-cell table dominates lookups.premium_for_cell). Only
        # cells the sales data covers are written; others keep the existing premium.
        cell_prem = dict(p.cell_premiums)
        for k, comp in avg_premium.items():
            if comp <= 0:
                continue
            label = _cell_label(k)
            entry = dict(cell_prem.get(label, {}))
            entry["All"] = round(float(comp), 4)
            for s, sp in state_prem.get(k, {}).items():
                if sp > 0:
                    entry[s] = round(float(sp), 4)
            cell_prem[label] = entry
        p.cell_premiums = cell_prem
    return new


def _incremental_aging(curve: dict, n: int) -> list:
    """Cumulative aging curve (duration -> factor >=1) -> the engine's incremental
    cc_aging_by_duration of length ``n`` (index d-1). Increment is cum_d/cum_{d-1}-1,
    floored at 0 so (1+aging) is never below 1; durations past the data hold flat."""
    if not curve:
        return [0.0] * n
    durs = sorted(curve)
    last = durs[-1]
    inc = [0.0] * n
    for d in range(2, n + 1):
        cum_d = curve.get(d, curve[last])
        cum_prev = curve.get(d - 1, curve[last])
        inc[d - 1] = round(max(0.0, cum_d / cum_prev - 1.0), 6) if cum_prev else 0.0
    return inc


def apply_claims(asm: AssumptionSet, claims: dict,
                 parts=("base_cc", "gender", "state", "selection"),
                 credibility_standard: float = 0.0) -> AssumptionSet:
    """Return a copy of ``asm`` with the morbidity assumptions the claims data can
    inform: base claim-cost level by plan & **issue age**, the gender differential,
    state morbidity factors, UW selection, and claim-cost aging. ``parts`` selects
    which to adopt. ``credibility_standard`` (life-years for full credibility, 0 = off)
    blends each base-cost band's experience with the current pricing value via the
    square-root rule. Where an (issue age, plan) has no experience, the existing
    pricing value is retained (revert to pricing — no extrapolation)."""
    new = copy.deepcopy(asm)
    morb = new.morbidity
    parts = set(parts)

    # base claim cost by plan & ISSUE age (gender blend), credibility-blended toward
    # the current pricing value; bands with no data keep the pricing value.
    if "base_cc" in parts:
        by_issue = claims.get("base_cc_by_issue_age", {})
        expo = claims.get("base_cc_exposure", {})
        for plan in morb.plans:
            curve = by_issue.get(plan)
            if not curve:
                continue
            new_vals = []
            for a, old in zip(morb.ages, morb.base_cc[plan]):
                if a in curve:
                    z = credibility_z(expo.get(plan, {}).get(a, 0.0), credibility_standard)
                    new_vals.append(round(blend(curve[a], old, z), 4))
                else:
                    new_vals.append(old)   # revert to pricing
            morb.base_cc[plan] = new_vals

    # gender differential — prefer the isolated (multivariate) estimate
    if "gender" in parts:
        gd = claims.get("gender_diff_isolated", claims.get("gender_diff"))
        if gd is not None:
            morb.gender_cc_diff = float(gd)

    # state factors from observed relativities, credibility-blended toward 1.0 (national) by
    # each state's exposure — thin states revert toward the national level.
    if "state" in parts:
        sexp = claims.get("state_exposure", {})
        for state, f in claims.get("state_factors", {}).items():
            if f > 0:
                z = credibility_z(sexp.get(state, 0.0), credibility_standard)
                morb.state_factors[state] = round(blend(f, 1.0, z), 6)

    # UW selection by (issue_age, uw, duration), credibility-blended toward the current
    # pricing selection (thin cells, e.g. high durations, revert to pricing).
    if "selection" in parts:
        rows = claims.get("selection_rows")
        if rows:
            cur = {(r["issue_age"], r["uw"], r["duration"]): r["factor"]
                   for r in morb.selection_factors}
            exp_rows = {(r["issue_age"], r["uw"], r["duration"]): r for r in rows}
            new_rows = []
            for key in sorted(set(cur) | set(exp_rows)):
                age, uw, d = key
                pricing = cur.get(key)
                if pricing is None:
                    pricing = L.selection_factor(new, age, uw, d)
                er = exp_rows.get(key)
                if er:
                    z = credibility_z(er.get("exposure", 0.0), credibility_standard)
                    factor = blend(er["factor"], pricing, z)
                else:
                    factor = pricing   # revert to pricing where no experience
                new_rows.append({"issue_age": age, "uw": uw, "duration": d,
                                 "factor": round(factor, 6)})
            morb.selection_factors = new_rows

    # claim-cost aging (antiselection P): isolated, monotone >=1 curve -> increments
    if "aging" in parts:
        curve = claims.get("aging_curve")
        if curve:
            morb.cc_aging_by_duration = _incremental_aging(
                curve, len(morb.cc_aging_by_duration))
    return new
