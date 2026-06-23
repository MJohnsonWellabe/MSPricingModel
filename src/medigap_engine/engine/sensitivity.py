"""Stochastic sensitivity analysis.

For each state, draw the 5 sensitivity factors from Normal(mean, std) each
simulation, re-solve rerates (targeting the same lifetime LR) and project to an
IRR. Returns the per-state distribution of IRRs plus summary statistics. The
per-state precompute is reused across simulations for speed.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from ..models.assumptions import AssumptionSet
from ..models.formulas import FormulaSet
from ..models.sensitivities import SensitivitySet
from .forward_solver import precompute, project_aggregate, solve_with_precompute
from .run import normalize_weights

FACTORS = (
    "morbidity_scale", "termination_scale", "rerate_effectiveness",
    "antiselective_lapse", "antiselective_claims",
)


def _draw(rng, specs: dict) -> SensitivitySet:
    vals = {}
    for f in FACTORS:
        mean, std = specs.get(f, (1.0, 0.0))
        v = rng.normal(mean, std) if std > 0 else mean
        vals[f] = max(0.01, float(v))   # keep strictly positive
    return SensitivitySet(**vals)


def _summarise(irrs, lrs, pti, sens_vecs, ci, n_sims, target_met) -> dict:
    """Build the per-run summary: IRR stats + P-lo/expected/P-hi pre-tax-income by year."""
    arr = np.array(irrs, dtype=float)
    pti_arr = np.array(pti, dtype=float) if pti else np.zeros((0, 0))   # (n_sims, years)
    if pti_arr.size:
        pti_lo = np.nanpercentile(pti_arr, ci[0], axis=0).tolist()
        pti_mean = np.nanmean(pti_arr, axis=0).tolist()
        pti_hi = np.nanpercentile(pti_arr, ci[1], axis=0).tolist()
    else:
        pti_lo = pti_mean = pti_hi = []
    return {
        "n": n_sims,
        "irrs": [float(x) for x in irrs],
        "lifetime_lrs": [float(x) for x in lrs],
        "irr_mean": float(np.nanmean(arr)) if arr.size else float("nan"),
        "irr_median": float(np.nanmedian(arr)) if arr.size else float("nan"),
        "irr_lo": float(np.nanpercentile(arr, ci[0])) if arr.size else float("nan"),
        "irr_hi": float(np.nanpercentile(arr, ci[1])) if arr.size else float("nan"),
        "pct_target_met": target_met / n_sims if n_sims else 0.0,
        "ci": ci,
        "pti_lo": pti_lo, "pti_mean": pti_mean, "pti_hi": pti_hi,
        "sens_vecs": sens_vecs,   # per-draw factor dict, for re-projecting a chosen scenario
    }


def simulate_state(cells, asm: AssumptionSet, state: str, specs: dict,
                   n_sims: int, ci: tuple[float, float], rng,
                   formulas: Optional[FormulaSet] = None) -> dict:
    """Run ``n_sims`` stochastic simulations for one state; return a summary including the
    per-year pre-tax-income range and the per-draw factor vectors."""
    P = precompute(cells, asm, state)
    irrs, lrs, pti, sens_vecs = [], [], [], []
    target_met = 0
    for _ in range(n_sims):
        sens = _draw(rng, specs)
        vec, info = solve_with_precompute(P, asm, sens, formulas=formulas)
        irr, lifetime, series = project_aggregate(P, asm, sens, vec, formulas=formulas,
                                                  return_series=True)
        irrs.append(irr)
        lrs.append(lifetime)
        pti.append(series["pretax_income"])
        sens_vecs.append({f: getattr(sens, f) for f in FACTORS})
        if info.get("status") in ("converged", "target_met_without_rerate"):
            target_met += 1
    return _summarise(irrs, lrs, pti, sens_vecs, ci, n_sims, target_met)


def simulate_portfolio(cells, asm: AssumptionSet, states: list[str], specs: dict,
                       n_sims: int, ci: tuple[float, float], rng,
                       formulas: Optional[FormulaSet] = None) -> dict:
    """Pooled-portfolio stochastic run: each draw prices EVERY state with its own factors
    and pools the cashflows into one portfolio IRR (premium-weighted by construction), so
    the distribution centres on the deterministic combined IRR. Returns the same summary
    shape as ``simulate_state`` plus pooled pre-tax-income ranges."""
    Ps = {s: precompute(cells, asm, s) for s in states}
    irrs, lrs, pti, sens_vecs = [], [], [], []
    target_met = 0
    from .metrics import discounted_cumulative_lr, irr as _irr
    dr = asm.other.discount_rate
    for _ in range(n_sims):
        sens = _draw(rng, specs)
        pooled_ah = None
        pooled_pti = None
        pooled_c = pooled_p = None
        ok = True
        for s, P in Ps.items():
            vec, info = solve_with_precompute(P, asm, sens, formulas=formulas)
            _irr_s, _lr, series = project_aggregate(P, asm, sens, vec, formulas=formulas,
                                                    return_series=True)
            ah = series["ah_cashflow"]
            ptis = series["pretax_income"]
            if pooled_ah is None:
                pooled_ah = list(ah)
                pooled_pti = list(ptis)
                pooled_c = list(series["claims"])
                pooled_p = list(series["earned_prem"])
            else:
                pooled_ah = [a + b for a, b in zip(pooled_ah, ah)]
                pooled_pti = [a + b for a, b in zip(pooled_pti, ptis)]
                pooled_c = [a + b for a, b in zip(pooled_c, series["claims"])]
                pooled_p = [a + b for a, b in zip(pooled_p, series["earned_prem"])]
            if info.get("status") not in ("converged", "target_met_without_rerate"):
                ok = False
        irrs.append(_irr(pooled_ah or [0.0]))
        lrs.append(discounted_cumulative_lr(pooled_c or [0.0], pooled_p or [1.0], dr)[-1])
        pti.append(pooled_pti or [])
        sens_vecs.append({f: getattr(sens, f) for f in FACTORS})
        if ok:
            target_met += 1
    return _summarise(irrs, lrs, pti, sens_vecs, ci, n_sims, target_met)


def project_scenario(cells, asm: AssumptionSet, states: list[str], sens_vec: dict,
                     formulas: Optional[FormulaSet] = None) -> dict:
    """Re-project a single drawn scenario (its factor vector) across one or more states,
    pooling the cashflows, and return the full income-statement series dict — used to show
    the full income statement behind a selected stochastic scenario."""
    sens = SensitivitySet(**{f: float(sens_vec.get(f, 1.0)) for f in FACTORS})
    pooled = None
    for s in states:
        P = precompute(cells, asm, s)
        vec, _ = solve_with_precompute(P, asm, sens, formulas=formulas)
        _irr, _lr, series = project_aggregate(P, asm, sens, vec, formulas=formulas,
                                              return_series=True)
        if pooled is None:
            pooled = {k: list(v) for k, v in series.items()}
        else:
            for k, v in series.items():
                pooled[k] = [a + b for a, b in zip(pooled[k], v)]
    return pooled or {}


def run_stochastic(cells, asm: AssumptionSet, states: list[str], specs: dict,
                   n_sims: int = 100, ci: tuple[float, float] = (5.0, 95.0),
                   seed: int = 0,
                   progress: Optional[Callable[[str, int, int], None]] = None,
                   formulas: Optional[FormulaSet] = None) -> dict:
    """Run stochastic sims across states. ``specs`` maps each factor name to
    (mean, std). Returns {state: summary}."""
    cells = normalize_weights(cells)
    rng = np.random.default_rng(seed)
    out: dict = {}
    for si, state in enumerate(states):
        if progress:
            progress(state, si, len(states))
        out[state] = simulate_state(cells, asm, state, specs, n_sims, ci, rng, formulas)
    return out
