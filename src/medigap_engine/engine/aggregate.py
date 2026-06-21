"""Aggregate per-cell projections into state and all-state results.

Dollar line items are summed weighted by each cell's distribution weight; ratio
metrics (loss ratio, IRR) are then re-derived from the aggregated cashflows.
Never average ratios directly.
"""
from __future__ import annotations

from ..models.assumptions import AssumptionSet, PROJECTION_YEARS
from ..models.results import CellResult, RunResult, StateResult
from .metrics import irr, npv

# Additive series safe to weight-and-sum: dollar line items plus inforce lives
# (lives is per policy issued, the book being normalised to weights summing to 1).
_DOLLAR_SERIES = (
    "lives",
    "earned_prem", "ibnr", "nii", "claims", "commission", "premium_tax",
    "oper_acq", "marketing", "maintenance", "pretax_income", "tax", "at_income",
    "rbc", "int_on_rbc", "tax_on_int", "ah_cashflow",
)


def _blank() -> dict[str, list[float]]:
    return {k: [0.0] * PROJECTION_YEARS for k in _DOLLAR_SERIES}


def _add_weighted(acc: dict[str, list[float]], result: CellResult, weight: float) -> None:
    for k in _DOLLAR_SERIES:
        src = result.projection.series[k]
        dst = acc[k]
        for i in range(PROJECTION_YEARS):
            dst[i] += src[i] * weight


def _finalise(series: dict[str, list[float]], asm: AssumptionSet) -> dict:
    claims = series["claims"]
    prem = series["earned_prem"]
    cum_c = cum_p = 0.0
    in_year = [0.0] * PROJECTION_YEARS
    lifetime = [0.0] * PROJECTION_YEARS
    for i in range(PROJECTION_YEARS):
        cum_c += claims[i]
        cum_p += prem[i]
        in_year[i] = claims[i] / prem[i] if prem[i] else 0.0
        lifetime[i] = cum_c / cum_p if cum_p else 0.0
    series = dict(series)
    series["in_year_lr"] = in_year
    series["lifetime_lr"] = lifetime
    metrics = {
        "irr": irr(series["ah_cashflow"]),
        "lifetime_lr": lifetime[-1],
        "npv_pretax": npv(asm.other.discount_rate, series["pretax_income"]),
        "npv_premium": npv(asm.other.discount_rate, series["earned_prem"]),
    }
    return series, metrics


def aggregate_cells(state: str, results: list[CellResult], asm: AssumptionSet) -> StateResult:
    acc = _blank()
    for res in results:
        _add_weighted(acc, res, res.weight)
    series, metrics = _finalise(acc, asm)
    # the rerate vector is identical across cells in a state; surface it
    rerates = list(results[0].projection.series["rerate_used"]) if results else []
    return StateResult(
        state=state, series=series, cells=results, rerates=rerates,
        irr=metrics["irr"], lifetime_lr=metrics["lifetime_lr"],
        npv_pretax=metrics["npv_pretax"], npv_premium=metrics["npv_premium"],
    )


def aggregate_states(per_state: dict[str, StateResult], asm: AssumptionSet) -> StateResult:
    """Combine multiple states (equal book weight per state) into one result."""
    acc = _blank()
    for st in per_state.values():
        for k in _DOLLAR_SERIES:
            for i in range(PROJECTION_YEARS):
                acc[k][i] += st.series[k][i]
    series, metrics = _finalise(acc, asm)
    return StateResult(
        state="(combined)", series=series, cells=[],
        irr=metrics["irr"], lifetime_lr=metrics["lifetime_lr"],
        npv_pretax=metrics["npv_pretax"], npv_premium=metrics["npv_premium"],
    )
