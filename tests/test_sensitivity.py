import numpy as np

from medigap_engine.engine.aggregate import aggregate_cells
from medigap_engine.engine.forward_solver import (
    precompute, project_aggregate, solve_rerates, solve_with_precompute,
)
from medigap_engine.engine.project import project_cell
from medigap_engine.engine.run import normalize_weights
from medigap_engine.engine.sensitivity import run_stochastic


def test_precompute_reuse_matches_direct_solve(asm, cells, base_sens):
    cells = normalize_weights(cells)
    direct, _ = solve_rerates(cells, asm, base_sens, "TX")
    P = precompute(cells, asm, "TX")
    viaP, _ = solve_with_precompute(P, asm, base_sens)
    assert direct == viaP


def test_project_aggregate_matches_project_cell(asm, cells, base_sens):
    cells = normalize_weights(cells)
    P = precompute(cells, asm, "TX")
    vec, _ = solve_with_precompute(P, asm, base_sens)
    irr_np, lr_np = project_aggregate(P, asm, base_sens, vec)
    agg = aggregate_cells("TX", [project_cell(c, asm, base_sens, "TX", vec) for c in cells], asm)
    assert abs(irr_np - agg.irr) < 1e-9
    assert abs(lr_np - agg.lifetime_lr) < 1e-9


def test_run_stochastic_reproducible_and_summarised(asm, cells):
    specs = {"morbidity_scale": (1.0, 0.05), "termination_scale": (1.0, 0.05),
             "rerate_effectiveness": (1.0, 0.05), "antiselective_lapse": (1.0, 0.10),
             "antiselective_claims": (1.0, 0.10)}
    out1 = run_stochastic(cells, asm, ["TX"], specs, n_sims=15, seed=42)
    out2 = run_stochastic(cells, asm, ["TX"], specs, n_sims=15, seed=42)
    assert out1["TX"]["irrs"] == out2["TX"]["irrs"]   # seeded reproducibility
    s = out1["TX"]
    assert s["n"] == 15
    assert s["irr_lo"] <= s["irr_median"] <= s["irr_hi"]
    assert 0.0 <= s["pct_target_met"] <= 1.0


def test_zero_std_gives_constant_irr(asm, cells):
    specs = {f: (1.0, 0.0) for f in
             ("morbidity_scale", "termination_scale", "rerate_effectiveness",
              "antiselective_lapse", "antiselective_claims")}
    out = run_stochastic(cells, asm, ["TX"], specs, n_sims=5, seed=1)
    irrs = out["TX"]["irrs"]
    assert max(irrs) - min(irrs) < 1e-9   # no randomness -> identical


def test_project_aggregate_series_matches_deterministic(asm, cells, base_sens):
    from medigap_engine.engine.project import project_cell
    cells = normalize_weights(cells)
    P = precompute(cells, asm, "TX")
    vec, _ = solve_with_precompute(P, asm, base_sens)
    irr_np, lr_np, series = project_aggregate(P, asm, base_sens, vec, return_series=True)
    agg = aggregate_cells("TX", [project_cell(c, asm, base_sens, "TX", vec) for c in cells], asm)
    # the aggregated income-statement lines match the per-cell deterministic aggregate
    for k in ("earned_prem", "claims", "pretax_income", "ah_cashflow", "oper_acq"):
        for a, b in zip(series[k], agg.series[k]):
            assert abs(a - b) < 1e-6


def test_pooled_portfolio_irr_matches_deterministic_combined(asm, cells):
    from medigap_engine.engine.run import RunConfig, run
    from medigap_engine.engine.sensitivity import simulate_portfolio
    states = ["TX", "CA", "DE"]
    res, _ = run(cells, asm, RunConfig(states=states))
    specs = {f: (1.0, 0.0) for f in
             ("morbidity_scale", "termination_scale", "rerate_effectiveness",
              "antiselective_lapse", "antiselective_claims")}
    out = simulate_portfolio(normalize_weights(cells), asm, states, specs, 2, (5.0, 95.0),
                             np.random.default_rng(0))
    # at the point estimate the pooled distribution collapses to the deterministic combined IRR
    assert abs(out["irr_mean"] - res.all_states.irr) < 1e-6
    assert len(out["pti_mean"]) == len(res.all_states.series["pretax_income"])
