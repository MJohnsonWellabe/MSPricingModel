from medigap_engine.engine import lookups as L
from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.models.assumptions import normalized_factors
from medigap_engine.models.cell import CellKey


def test_premium_is_factor_product(asm):
    p = asm.premium
    d = asm.distribution
    key = CellKey(65, "M", "G", "OE", "N", "N")
    pf = asm.pull_forward
    bring_forward = (1.0 + pf.premium_trend) ** pf.duration
    expected = (
        p.base_for_age(65)
        * p.plan_rel["G"]                                              # G anchored at 1.0
        * normalized_factors({"M": 1 + p.gender_diff, "F": 1.0}, d.gender)["M"]
        * normalized_factors(p.uw_rel, d.uw)["OE"]
        * normalized_factors({"N": 1 + p.preferred_diff, "Y": 1.0}, d.preferred)["N"]
        * normalized_factors({"N": 1 + p.hhd_diff, "Y": 1.0}, d.hhd)["N"]
        * p.state_factor["IA"]
        * bring_forward
    )
    assert abs(L.premium_for_cell(asm, key, "IA") - expected) < 1e-9


def test_premium_pull_forward_brings_forward(asm):
    key = CellKey(65, "M", "G", "OE", "N", "N")
    import copy
    exp = asm.pull_forward.duration
    untrended = copy.deepcopy(asm)
    untrended.pull_forward.premium_trend = 0.0
    base = L.premium_for_cell(untrended, key, "IA")
    asm.pull_forward.premium_trend = 0.05
    trended = L.premium_for_cell(asm, key, "IA")
    assert abs(trended - base * (1.05) ** exp) < 1e-9


def test_plan_anchored_at_g(asm):
    assert asm.premium.plan_rel["G"] == 1.0


def test_premium_diff_defaults(asm):
    assert abs(asm.premium.gender_diff - 0.15) < 1e-9
    assert abs(asm.premium.hhd_diff - 0.14) < 1e-9
    assert abs(asm.premium.preferred_diff - 0.10) < 1e-9


def test_normalized_factor_weighted_mean_is_one(asm):
    d = asm.distribution
    f = normalized_factors({"M": 1 + asm.premium.gender_diff, "F": 1.0}, d.gender)
    mean = sum(d.gender[k] * f[k] for k in f)
    assert abs(mean - 1.0) < 1e-9


def test_distribution_dimensions_sum_to_one(asm):
    d = asm.distribution
    for dim in (d.by_issue_age, d.gender, d.plan, d.uw, d.preferred, d.hhd):
        assert abs(sum(dim.values()) - 1.0) < 1e-4


def test_weight_is_product_of_marginals(asm):
    d = asm.distribution
    key = CellKey(73, "F", "N", "OE", "Y", "N")
    expected = (d.by_issue_age[73] * d.gender["F"] * d.plan["N"]
                * d.uw["OE"] * d.preferred["Y"] * d.hhd["N"])
    assert abs(d.weight(key) - expected) < 1e-12


def test_build_cells_full_grid_and_weights():
    asm = default_assumptions()
    cells = build_cells(asm)
    assert len(cells) == 6 * 2 * 3 * 3 * 2 * 2  # 432
    assert abs(sum(c.weight for c in cells) - 1.0) < 1e-4
