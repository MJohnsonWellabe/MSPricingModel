"""Limited-fluctuation (square-root rule) credibility.

A low-exposure cell shouldn't swing fully to its noisy experience value. The
credibility ``Z = min(1, sqrt(exposure / full_credibility_standard))`` weights the
observed experience against the current pricing assumption:

    adopted = Z · experience + (1 − Z) · pricing

Full credibility (Z = 1) is reached at ``full_credibility_standard`` life-years of
exposure. A standard of 0 means "always fully credible" (no blending). Pure stdlib.
"""
from __future__ import annotations

import math


def credibility_z(exposure: float, full_credibility_standard: float) -> float:
    """Square-root credibility factor in [0, 1]."""
    if full_credibility_standard <= 0:
        return 1.0
    return min(1.0, math.sqrt(max(0.0, exposure) / full_credibility_standard))


def blend(experience: float, pricing: float, z: float) -> float:
    """Credibility-weighted blend of an experience value with the pricing value."""
    return z * experience + (1.0 - z) * pricing
