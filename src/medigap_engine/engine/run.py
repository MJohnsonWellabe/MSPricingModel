"""Top-level run orchestration: price a set of states from cells + assumptions."""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from ..models.assumptions import AssumptionSet
from ..models.cell import PricingCell
from ..models.config import RunConfig
from ..models.formulas import FormulaSet
from ..models.results import RunResult, StateResult
from .aggregate import aggregate_cells, aggregate_states
from .forward_solver import solve_rerates
from .project import project_cell


def normalize_weights(cells: list[PricingCell]) -> list[PricingCell]:
    """Scale cell weights to sum to 1 (ratio metrics are scale-invariant, but
    this keeps aggregated dollar magnitudes interpretable)."""
    total = sum(c.weight for c in cells)
    if total <= 0:
        return list(cells)
    return [replace(c, weight=c.weight / total) for c in cells]


def _project_state(
    state: str, cells: list[PricingCell], asm: AssumptionSet,
    sens, rerates: list[float], formulas: Optional[FormulaSet],
) -> StateResult:
    results = [project_cell(c, asm, sens, state, rerates, formulas) for c in cells]
    return aggregate_cells(state, results, asm)


def _state_cells(state: str, cells: list[PricingCell], asm: AssumptionSet) -> list[PricingCell]:
    """Reweight cells by the state's distribution grid when one is present (per-state
    GI/OE/UW and plan mix); otherwise use the national weights unchanged."""
    if state not in asm.distribution.by_state:
        return cells
    rew = [replace(c, weight=asm.distribution.grid_weight(c.key, state)) for c in cells]
    return normalize_weights(rew)


def run_state(
    state: str, cells: list[PricingCell], asm: AssumptionSet, config: RunConfig,
    formulas: Optional[FormulaSet] = None,
) -> tuple[StateResult, dict]:
    """Price one state, solving rerates if configured."""
    sens = config.sensitivities
    cells = _state_cells(state, cells, asm)

    def projector(rerates: list[float]) -> StateResult:
        return _project_state(state, cells, asm, sens, rerates, formulas)

    solve = config.solve_rerates and asm.rerates.solve
    if solve:
        rerates, info = solve_rerates(cells, asm, sens, state, formulas=formulas)
    else:
        rerates = list(asm.rerates.rerates_for(state))
        info = {"status": "specified", "rerates": rerates}

    result = projector(rerates)
    floor = asm.rerates.in_year_lr_floor
    info["in_year_lr_floor_breaches"] = [
        i + 1 for i, lr in enumerate(result.series["in_year_lr"]) if 0 < lr < floor - 1e-6]
    info.setdefault("achieved_lifetime_lr", result.lifetime_lr)
    return result, info


def run(
    cells: list[PricingCell], asm: AssumptionSet, config: RunConfig,
    formulas: Optional[FormulaSet] = None,
) -> tuple[RunResult, dict[str, dict]]:
    """Run the model across all configured states.

    Returns the :class:`RunResult` and a per-state dict of solver diagnostics.
    """
    cells = normalize_weights(cells)
    by_state: dict[str, StateResult] = {}
    diagnostics: dict[str, dict] = {}
    for state in config.states:
        st, info = run_state(state, cells, asm, config, formulas)
        by_state[state] = st
        diagnostics[state] = info

    if len(by_state) > 1:
        combined = aggregate_states(by_state, asm)
    elif by_state:
        only = next(iter(by_state.values()))
        combined = only
    else:
        combined = None

    return RunResult(by_state=by_state, all_states=combined), diagnostics
