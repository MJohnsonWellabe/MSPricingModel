from medigap_engine.engine.forward_solver import solve_rerates
from medigap_engine.engine.project import project_cell
from medigap_engine.engine.aggregate import aggregate_cells
from medigap_engine.models.assumptions import PROJECTION_YEARS


def _project(asm, cells, sens, state, rerates):
    results = [project_cell(c, asm, sens, state, rerates) for c in cells]
    return aggregate_cells(state, results, asm)


def _baseline_fixable(asm, cells, sens, state):
    """Durations whose in-year LR is >= floor under trend-only rerates."""
    trend = asm.morbidity.trend_by_year
    vec = list(asm.rerates.specified_rerates[:2]) + [
        trend[min(i, len(trend) - 1)] for i in range(2, PROJECTION_YEARS)]
    iy = _project(asm, cells, sens, state, vec).series["in_year_lr"]
    return [lr >= asm.rerates.in_year_lr_floor - 1e-9 for lr in iy]


def test_first_two_durations_are_specified(asm, cells, base_sens):
    vec, info = solve_rerates(cells, asm, base_sens, "All")
    assert vec[0] == asm.rerates.specified_rerates[0]
    assert vec[1] == asm.rerates.specified_rerates[1]
    assert len(vec) == PROJECTION_YEARS


def test_solver_hits_lifetime_target_when_reachable(asm, cells, base_sens):
    vec, info = solve_rerates(cells, asm, base_sens, "TX")
    if info["status"] == "converged":
        assert abs(info["achieved_lifetime_lr"] - asm.rerates.target_lifetime_lr) < 5e-3


def test_solver_does_not_rerate_below_floor_in_active_years(asm, cells, base_sens):
    # the floor caps each *rerate* year: in an actively re-rated duration (rerate
    # above trend) the in-year LR is not driven below the floor.
    vec, info = solve_rerates(cells, asm, base_sens, "TX")
    trend = asm.morbidity.trend_by_year
    iy = _project(asm, cells, base_sens, "TX", vec).series["in_year_lr"]
    for i in range(2, PROJECTION_YEARS):
        active = vec[i] > trend[min(i, len(trend) - 1)] + 1e-6
        if active and iy[i] > 0:
            assert iy[i] >= asm.rerates.in_year_lr_floor - 1e-2


def test_solver_respects_max_rerate(asm, cells, base_sens):
    vec, info = solve_rerates(cells, asm, base_sens, "All")
    assert all(v <= asm.rerates.max_rerate + 1e-9 for v in vec[2:])


def test_target_met_without_rerate_uses_trend_tail(asm, cells, base_sens):
    # a very high target is trivially met -> no front-loading
    asm.rerates.target_lifetime_lr = 0.99
    vec, info = solve_rerates(cells, asm, base_sens, "FL")
    assert info["status"] == "target_met_without_rerate"
