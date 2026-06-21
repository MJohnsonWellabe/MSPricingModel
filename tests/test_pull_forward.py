import copy

from medigap_engine.engine import lookups as L
from medigap_engine.engine.project import project_cell


def test_base_claim_cost_includes_pull_forward(asm):
    pf = asm.pull_forward
    expected_factor = (1.0 + pf.claims_trend) ** pf.duration
    no_pf = copy.deepcopy(asm)
    no_pf.pull_forward.claims_trend = 0.0
    no_pf.pull_forward.duration = 0.0
    base = L.base_claim_cost(no_pf, "M", 70, "G")
    pulled = L.base_claim_cost(asm, "M", 70, "G")
    assert abs(pulled / base - expected_factor) < 1e-9


def test_year1_trend_factor_is_one(asm, sample_cell, base_sens):
    # pulled base is the year-1 level, so the cumulative trend factor O is 1.0 in year 1
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    trend = res.projection.series["trend"]
    assert abs(trend[0] - 1.0) < 1e-12
    # year 2 compounds one year of projection trend
    assert abs(trend[1] - (1.0 + L.trend_year(asm, 2))) < 1e-9


def test_pull_forward_claims_trend_independent_of_projection_trend(asm, sample_cell, base_sens):
    rerates = list(asm.rerates.specified_rerates)
    base = project_cell(sample_cell, asm, base_sens, "All", rerates)
    asm.pull_forward.claims_trend += 0.05   # change pull-forward only
    changed = project_cell(sample_cell, asm, base_sens, "All", rerates)
    # year-1 claims move with the pull-forward...
    assert changed.projection.series["claims"][0] != base.projection.series["claims"][0]
    # ...but the projection-trend step (year2/year1 ratio of the trend factor) is unchanged
    b = base.projection.series["trend"]
    c = changed.projection.series["trend"]
    assert abs((c[1] / c[0]) - (b[1] / b[0])) < 1e-12
