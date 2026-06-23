from medigap_engine.engine.project import project_cell
from medigap_engine.models.assumptions import PROJECTION_YEARS


def test_projection_length(asm, sample_cell, base_sens):
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    for series in res.projection.series.values():
        assert len(series) == PROJECTION_YEARS


def test_lives_monotone_decreasing(asm, sample_cell, base_sens):
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    lives = res.projection.series["lives"]
    assert all(lives[i] >= lives[i + 1] for i in range(len(lives) - 1))
    assert 0 < lives[0] <= 1.0


def test_lifetime_lr_is_discounted(asm, sample_cell, base_sens):
    from medigap_engine.engine.metrics import npv
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    p = res.projection.series
    rate = asm.other.discount_rate
    expected = npv(rate, p["claims"]) / npv(rate, p["earned_prem"])
    assert abs(res.lifetime_lr - expected) < 1e-9


def test_morbidity_sensitivity_scales_claims(asm, sample_cell, base_sens):
    from medigap_engine.models.sensitivities import SensitivitySet
    base = project_cell(sample_cell, asm, base_sens, "All",
                        list(asm.rerates.specified_rerates))
    up = project_cell(sample_cell, asm, SensitivitySet(morbidity_scale=1.10), "All",
                      list(asm.rerates.specified_rerates))
    # claims should scale up ~10% in year 1 (before antiselection feedback differences)
    assert up.projection.series["claims"][0] > base.projection.series["claims"][0]
    ratio = up.projection.series["claims"][0] / base.projection.series["claims"][0]
    assert abs(ratio - 1.10) < 1e-6


def test_pull_forward_duration_changes_year1_claims(asm, sample_cell, base_sens):
    rerates = list(asm.rerates.specified_rerates)
    base = project_cell(sample_cell, asm, base_sens, "All", rerates)
    asm.pull_forward.duration = 1.0
    changed = project_cell(sample_cell, asm, base_sens, "All", rerates)
    # the claims pull-forward uses the duration, so year-1 claims must change
    assert (base.projection.series["claims"][0]
            != changed.projection.series["claims"][0])


def test_state_factor_changes_claims(asm, sample_cell, base_sens):
    res_all = project_cell(sample_cell, asm, base_sens, "All",
                           list(asm.rerates.specified_rerates))
    # CA has a higher morbidity factor than the All baseline
    res_ca = project_cell(sample_cell, asm, base_sens, "CA",
                          list(asm.rerates.specified_rerates))
    fa = asm.morbidity.state_factors.get("All", 1.0)
    fc = asm.morbidity.state_factors.get("CA", 1.0)
    if fc != fa:
        assert (res_ca.projection.series["claims"][0]
                > res_all.projection.series["claims"][0]) == (fc > fa)
