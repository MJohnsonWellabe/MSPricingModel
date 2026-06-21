from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.models.cell import CellKey


def test_premium_is_factor_product(asm):
    p = asm.premium
    key = CellKey(65, "M", "G", "OE", "N", "N")
    expected = (p.base_by_issue_age[65] * p.gender_factor["M"] * p.plan_factor["G"]
                * p.uw_factor["OE"] * p.preferred_factor["N"] * p.hhd_factor["N"]
                * p.state_factor["IA"])
    assert abs(p.premium(key, "IA") - expected) < 1e-9


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
