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


def simulate_state(cells, asm: AssumptionSet, state: str, specs: dict,
                   n_sims: int, ci: tuple[float, float], rng) -> dict:
    """Run ``n_sims`` stochastic simulations for one state; return a summary."""
    P = precompute(cells, asm, state)
    irrs, lrs = [], []
    target_met = 0
    for _ in range(n_sims):
        sens = _draw(rng, specs)
        vec, info = solve_with_precompute(P, asm, sens)
        irr, lifetime = project_aggregate(P, asm, sens, vec)
        irrs.append(irr)
        lrs.append(lifetime)
        if info.get("status") in ("converged", "target_met_without_rerate"):
            target_met += 1
    arr = np.array(irrs, dtype=float)
    return {
        "n": n_sims,
        "irrs": [float(x) for x in irrs],
        "lifetime_lrs": [float(x) for x in lrs],
        "irr_mean": float(np.nanmean(arr)),
        "irr_median": float(np.nanmedian(arr)),
        "irr_lo": float(np.nanpercentile(arr, ci[0])),
        "irr_hi": float(np.nanpercentile(arr, ci[1])),
        "pct_target_met": target_met / n_sims if n_sims else 0.0,
        "ci": ci,
    }


def run_stochastic(cells, asm: AssumptionSet, states: list[str], specs: dict,
                   n_sims: int = 100, ci: tuple[float, float] = (5.0, 95.0),
                   seed: int = 0,
                   progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """Run stochastic sims across states. ``specs`` maps each factor name to
    (mean, std). Returns {state: summary}."""
    cells = normalize_weights(cells)
    rng = np.random.default_rng(seed)
    out: dict = {}
    for si, state in enumerate(states):
        if progress:
            progress(state, si, len(states))
        out[state] = simulate_state(cells, asm, state, specs, n_sims, ci, rng)
    return out
