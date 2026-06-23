"""Financial metrics, hand-rolled to avoid scipy / numpy_financial (neither is a
safe Pyodide dependency)."""
from __future__ import annotations

from typing import Sequence


def npv(rate: float, cashflows: Sequence[float]) -> float:
    """Net present value. Period 0 is the first element (Excel NPV discounts the
    first element by one period, matching the workbook's NPV usage)."""
    return sum(cf / (1.0 + rate) ** (t + 1) for t, cf in enumerate(cashflows))


def discounted_cumulative_lr(claims: Sequence[float], premium: Sequence[float],
                             rate: float) -> list[float]:
    """Running NPV-discounted loss ratio by duration: at duration d, the NPV of claims
    through d divided by the NPV of premium through d (same discount convention as ``npv``,
    so the final element equals ``npv(rate, claims) / npv(rate, premium)``)."""
    out, cum_c, cum_p = [], 0.0, 0.0
    for t, (c, p) in enumerate(zip(claims, premium)):
        df = 1.0 / (1.0 + rate) ** (t + 1)
        cum_c += c * df
        cum_p += p * df
        out.append(cum_c / cum_p if cum_p else 0.0)
    return out


def _npv_for_irr(rate: float, cashflows: Sequence[float]) -> float:
    # IRR convention: first cashflow at t=0 (undiscounted).
    base = 1.0 + rate
    if base <= 1e-9:
        base = 1e-9
    total = 0.0
    factor = 1.0
    for cf in cashflows:
        total += cf / factor
        factor *= base
        if factor == float("inf"):
            break
    return total


def irr(cashflows: Sequence[float]) -> float:
    """Internal rate of return via bisection over a wide bracket.

    Returns float('nan') when there is no sign change (no real IRR in range)."""
    cfs = list(cashflows)
    if not cfs or all(c >= 0 for c in cfs) or all(c <= 0 for c in cfs):
        return float("nan")

    lo, hi = -0.9999, 100.0
    flo = _npv_for_irr(lo, cfs)
    fhi = _npv_for_irr(hi, cfs)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fmid = _npv_for_irr(mid, cfs)
        if abs(fmid) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0
