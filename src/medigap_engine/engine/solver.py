"""Rerate solver.

Implements the user's described mechanism: take rerates (as large as the rules
allow) until the projected lifetime loss ratio reaches the target, then take
trend-only rerates for the remainder.

The control variable is a continuous "switchover" ``x`` in [2, 30]: durations up
to ``x`` take the full (rule-capped) rerate, the duration straddling ``x`` takes a
partial rerate, and later durations take trend-only. Lifetime loss ratio is
monotone decreasing in ``x`` (more rerate -> more premium -> lower LR), so a
bisection on ``x`` converges without scipy.

Rules enforced while building the candidate vector:
* ``max_rerate``           - no single rerate above this
* ``consecutive_z`` / ``b`` - at most ``b`` consecutive rerates above ``z``
The ``in_year_lr_floor`` is reported as a diagnostic (see ``solve_rerates``).
"""
from __future__ import annotations

from typing import Callable

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from ..models.results import StateResult


def build_rerate_vector(asm: AssumptionSet, x: float) -> list[float]:
    """Build a length-30 rerate vector for switchover ``x``."""
    rr = asm.rerates
    n = PROJECTION_YEARS
    trend = asm.morbidity.trend_by_year
    spec = rr.specified_rerates
    z = rr.consecutive_z
    b = max(1, rr.consecutive_b)

    out = [0.0] * n
    # durations 1 and 2 are always user-specified
    out[0] = spec[0] if len(spec) > 0 else 0.0
    out[1] = spec[1] if len(spec) > 1 else 0.0

    run_gt_z = 1 if out[1] > z else 0  # trailing run of rerates above z

    full_until = int(x)        # durations <= full_until take full rerate
    frac = x - full_until      # partial rerate on the straddling duration

    for i in range(2, n):
        d = i + 1
        tr = trend[min(d, len(trend)) - 1]
        if d <= full_until:
            cand = rr.max_rerate
            if run_gt_z >= b and cand > z:   # consecutive-rule cap
                cand = z
        elif d == full_until + 1 and frac > 0:
            target_full = rr.max_rerate
            if run_gt_z >= b and target_full > z:
                target_full = z
            cand = tr + frac * (target_full - tr)
        else:
            cand = tr                         # trend-only tail
        out[i] = cand
        run_gt_z = run_gt_z + 1 if cand > z else 0
    return out


def solve_rerates(
    project_state: Callable[[list[float]], StateResult],
    asm: AssumptionSet,
    tol: float = 1e-4,
    max_iter: int = 60,
) -> tuple[list[float], dict]:
    """Find the rerate vector whose aggregate lifetime LR meets the target.

    ``project_state(rerates)`` must project the whole state with the given rerate
    vector and return its aggregate :class:`StateResult`.
    """
    target = asm.rerates.target_lifetime_lr
    n = PROJECTION_YEARS

    def lr_at(x: float) -> float:
        return project_state(build_rerate_vector(asm, x)).lifetime_lr

    lo, hi = 2.0, float(n)
    lr_lo = lr_at(lo)   # least rerate -> highest LR
    lr_hi = lr_at(hi)   # most rerate  -> lowest LR

    info: dict = {"target": target, "lr_min": lr_hi, "lr_max": lr_lo}

    if lr_lo <= target:
        # even with trend-only the LR is already at/below target
        vec = build_rerate_vector(asm, lo)
        info["status"] = "target_met_without_rerate"
        info["x"] = lo
    elif lr_hi >= target:
        # cannot reach target even at maximum rerating
        vec = build_rerate_vector(asm, hi)
        info["status"] = "target_unreachable"
        info["x"] = hi
    else:
        x = (lo + hi) / 2.0
        for _ in range(max_iter):
            x = (lo + hi) / 2.0
            lr = lr_at(x)
            if abs(lr - target) < tol:
                break
            # LR decreases as x increases
            if lr > target:
                lo = x
            else:
                hi = x
        vec = build_rerate_vector(asm, x)
        info["status"] = "converged"
        info["x"] = x

    # diagnostic: where does the in-year LR breach the floor?
    result = project_state(vec)
    floor = asm.rerates.in_year_lr_floor
    breaches = [i + 1 for i, lr in enumerate(result.series["in_year_lr"]) if 0 < lr < floor]
    info["in_year_lr_floor_breaches"] = breaches
    info["achieved_lifetime_lr"] = result.lifetime_lr
    return vec, info
