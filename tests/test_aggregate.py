from medigap_engine.engine.aggregate import aggregate_cells, aggregate_states
from medigap_engine.engine.project import project_cell


def test_aggregate_sums_weighted_dollars(asm, cells, base_sens):
    subset = cells[:20]
    rerates = list(asm.rerates.specified_rerates)
    results = [project_cell(c, asm, base_sens, "All", rerates) for c in subset]
    agg = aggregate_cells("All", results, asm)
    # year-1 earned premium equals weighted sum of cell earned premiums
    expected = sum(r.weight * r.projection.series["earned_prem"][0] for r in results)
    assert abs(agg.series["earned_prem"][0] - expected) < 1e-6


def test_aggregate_lifetime_lr_is_discounted(asm, cells, base_sens):
    from medigap_engine.engine.metrics import npv
    subset = cells[:20]
    rerates = list(asm.rerates.specified_rerates)
    results = [project_cell(c, asm, base_sens, "All", rerates) for c in subset]
    agg = aggregate_cells("All", results, asm)
    rate = asm.other.discount_rate
    expected = npv(rate, agg.series["claims"]) / npv(rate, agg.series["earned_prem"])
    assert abs(agg.lifetime_lr - expected) < 1e-9


def test_aggregate_includes_lives(asm, cells, base_sens):
    subset = cells[:20]
    rerates = list(asm.rerates.specified_rerates)
    results = [project_cell(c, asm, base_sens, "All", rerates) for c in subset]
    agg = aggregate_cells("All", results, asm)
    lives = agg.series["lives"]
    # weighted inforce: present, positive, and non-increasing over the projection
    assert len(lives) == len(asm.morbidity.trend_by_year)
    assert lives[0] > 0
    expected0 = sum(r.weight * r.projection.series["lives"][0] for r in results)
    assert abs(lives[0] - expected0) < 1e-9
    assert lives[-1] <= lives[0]


def test_aggregate_carries_rerate_vector(asm, cells, base_sens):
    rerates = [0.0, 0.1] + [0.05] * 28
    results = [project_cell(c, asm, base_sens, "All", rerates) for c in cells[:5]]
    agg = aggregate_cells("All", results, asm)
    assert agg.rerates[:3] == rerates[:3]
    assert len(agg.rerates) == len(rerates)


def test_aggregate_states_combines(asm, cells, base_sens):
    subset = cells[:10]
    rerates = list(asm.rerates.specified_rerates)
    per_state = {}
    for s in ("TX", "FL"):
        results = [project_cell(c, asm, base_sens, s, rerates) for c in subset]
        per_state[s] = aggregate_cells(s, results, asm)
    combined = aggregate_states(per_state, asm)
    expected = (per_state["TX"].series["claims"][0]
                + per_state["FL"].series["claims"][0])
    assert abs(combined.series["claims"][0] - expected) < 1e-6
