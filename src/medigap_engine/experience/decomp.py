"""Multivariate main-effects decomposition (minimum-bias / method of marginal totals).

A single-pass marginal mean (average premium for males vs females) is *confounded* by
the other variables — if males skew younger, more preferred, etc., their marginal mean
mixes the gender effect with those. This fits a multiplicative model

    value(cell) ≈ baseline · Π_d factor[d][cell[d]]

by iterating each dimension's log-effect to the weighted-mean residual holding the
other dimensions fixed, until convergence. Each factor then isolates that dimension's
effect with the others held constant. Pure stdlib so it runs under Pyodide.
"""
from __future__ import annotations

import math
from collections import defaultdict


def fit_main_effects(observations, n_dims: int, iterations: int = 200,
                     tol: float = 1e-10) -> dict:
    """Fit isolated multiplicative main effects.

    ``observations`` is an iterable of ``(key, value, weight)`` where ``key`` is a
    tuple of length ``n_dims`` of level labels, ``value`` is a positive quantity and
    ``weight`` is a positive exposure/count. Returns a dict with:
      * ``baseline``    exp(weighted-mean log value)
      * ``factors``     list (per dim) of {level -> multiplicative factor}
      * ``log_effects`` list (per dim) of {level -> additive log effect}
    """
    pts = [(k, math.log(v), float(w)) for k, v, w in observations if v > 0 and w > 0]
    if not pts:
        return {"baseline": 0.0, "factors": [{} for _ in range(n_dims)],
                "log_effects": [{} for _ in range(n_dims)]}
    wtot = sum(w for _, _, w in pts)
    mu = sum(lv * w for _, lv, w in pts) / wtot
    eff = [defaultdict(float) for _ in range(n_dims)]
    for _ in range(iterations):
        max_change = 0.0
        for d in range(n_dims):
            num: dict = defaultdict(float)
            den: dict = defaultdict(float)
            for k, lv, w in pts:
                resid = lv - mu - sum(eff[dd][k[dd]] for dd in range(n_dims) if dd != d)
                num[k[d]] += resid * w
                den[k[d]] += w
            for lvl, s in num.items():
                new = s / den[lvl] if den[lvl] else 0.0
                max_change = max(max_change, abs(new - eff[d][lvl]))
                eff[d][lvl] = new
        if max_change < tol:
            break
    factors = [{lvl: math.exp(v) for lvl, v in eff[d].items()} for d in range(n_dims)]
    return {"baseline": math.exp(mu), "factors": factors,
            "log_effects": [dict(e) for e in eff]}


def differential(factors: list, dim: int, high, low) -> float:
    """High-over-low multiplicative differential for one dimension, e.g. the isolated
    male-vs-female premium load. Returns 0.0 if either level is absent."""
    f = factors[dim]
    if high in f and low in f and f[low]:
        return f[high] / f[low] - 1.0
    return 0.0
