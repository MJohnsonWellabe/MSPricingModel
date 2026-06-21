from medigap_engine.engine.aggregate import aggregate_cells
from medigap_engine.engine.project import project_cell
from medigap_engine.engine.solver import build_rerate_vector, solve_rerates
from medigap_engine.models.assumptions import PROJECTION_YEARS


def _projector(asm, cells, sens, state):
    def project_state(rerates):
        results = [project_cell(c, asm, sens, state, rerates) for c in cells]
        return aggregate_cells(state, results, asm)
    return project_state


def test_rerate_vector_first_two_durations_specified(asm):
    vec = build_rerate_vector(asm, 10.0)
    assert vec[0] == asm.rerates.specified_rerates[0]
    assert vec[1] == asm.rerates.specified_rerates[1]
    assert len(vec) == PROJECTION_YEARS


def test_rerate_vector_respects_max(asm):
    vec = build_rerate_vector(asm, 30.0)
    # durations 3+ never exceed max_rerate
    assert all(v <= asm.rerates.max_rerate + 1e-12 for v in vec[2:])


def test_rerate_vector_consecutive_rule(asm):
    asm.rerates.consecutive_z = 0.05
    asm.rerates.consecutive_b = 2
    asm.rerates.max_rerate = 0.20
    vec = build_rerate_vector(asm, 30.0)
    z, b = asm.rerates.consecutive_z, asm.rerates.consecutive_b
    run = 0
    for v in vec:
        run = run + 1 if v > z else 0
        assert run <= b


def test_rerate_vector_tail_is_trend(asm):
    vec = build_rerate_vector(asm, 5.0)
    trend = asm.morbidity.trend_by_year
    # durations 7+ (well past switchover 5) should be trend-only
    for i in range(6, PROJECTION_YEARS):
        assert abs(vec[i] - trend[min(i + 1, len(trend)) - 1]) < 1e-9


def test_solver_converges_or_diagnoses(asm, cells, base_sens):
    asm.rerates.target_lifetime_lr = 0.70
    proj = _projector(asm, cells, base_sens, "All")
    vec, info = solve_rerates(proj, asm)
    assert info["status"] in {
        "converged", "target_met_without_rerate", "target_unreachable",
    }
    if info["status"] == "converged":
        assert abs(info["achieved_lifetime_lr"] - 0.70) < 1e-2


def test_more_rerate_lowers_lifetime_lr(asm, cells, base_sens):
    proj = _projector(asm, cells, base_sens, "All")
    lr_low = proj(build_rerate_vector(asm, 2.0)).lifetime_lr
    lr_high = proj(build_rerate_vector(asm, 30.0)).lifetime_lr
    assert lr_high <= lr_low
