"""Top-level run orchestration: price a set of states from cells + assumptions."""
from __future__ import annotations

from ..models.assumptions import AssumptionSet
from ..models.cell import PricingCell
from ..models.config import RunConfig
from ..models.results import RunResult, StateResult
from .aggregate import aggregate_cells, aggregate_states
from .project import project_cell
from .solver import solve_rerates


def _project_state(
    state: str, cells: list[PricingCell], asm: AssumptionSet,
    sens, rerates: list[float],
) -> StateResult:
    results = [project_cell(c, asm, sens, state, rerates) for c in cells]
    return aggregate_cells(state, results, asm)


def run_state(
    state: str, cells: list[PricingCell], asm: AssumptionSet, config: RunConfig,
) -> tuple[StateResult, dict]:
    """Price one state, solving rerates if configured."""
    sens = config.sensitivities

    def projector(rerates: list[float]) -> StateResult:
        return _project_state(state, cells, asm, sens, rerates)

    solve = config.solve_rerates and asm.rerates.solve
    if solve:
        rerates, info = solve_rerates(projector, asm)
    else:
        rerates = list(asm.rerates.specified_rerates)
        info = {"status": "specified", "rerates": rerates}

    return projector(rerates), info


def run(
    cells: list[PricingCell], asm: AssumptionSet, config: RunConfig,
) -> tuple[RunResult, dict[str, dict]]:
    """Run the model across all configured states.

    Returns the :class:`RunResult` and a per-state dict of solver diagnostics.
    """
    by_state: dict[str, StateResult] = {}
    diagnostics: dict[str, dict] = {}
    for state in config.states:
        st, info = run_state(state, cells, asm, config)
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
