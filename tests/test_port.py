from medigap_engine.engine import lookups as L
from medigap_engine.experience.port import apply_claims, apply_sales


def test_apply_sales_updates_weights_and_premium(asm, cells):
    sales = {
        "weights": {(65, "M", "G", "UW", "Y", "Y"): 1.0},
        "avg_premium": {(65, "M", "G", "UW", "Y", "Y"): 2500.0},
        "state_premiums": {(65, "M", "G", "UW", "Y", "Y"): {"TX": 2400.0}},
    }
    new_cells = apply_sales(cells, sales)
    target = [c for c in new_cells
              if (c.key.issue_age, c.key.gender, c.key.plan, c.key.uw_class,
                  c.key.preferred, c.key.hhd) == (65, "M", "G", "UW", "Y", "Y")]
    assert len(target) == 1
    assert target[0].weight == 1.0
    assert target[0].base_prem == 2500.0
    assert target[0].premium_for("TX") == 2400.0
    # other cells now carry zero weight
    assert all(c.weight == 0.0 for c in new_cells if c is not target[0])


def test_apply_claims_recalibrates_level_and_state(asm):
    cur_g_65 = L.base_claim_cost(asm, "M", 65, "G")
    claims = {
        "dur1_cc": {"G": {65: cur_g_65 * 1.2}},   # observe 20% higher (vs male table)
        "state_factors": {"CA": 1.5},
        "selection": {}, "aging_by_duration": {},
    }
    new = apply_claims(asm, claims)
    # plan G male table scaled up (factor uses gender-blend, so ~ within range)
    assert new.morbidity.base_cc_male["G"][0] > asm.morbidity.base_cc_male["G"][0]
    assert new.morbidity.state_factors["CA"] == 1.5
    # plan F untouched
    assert new.morbidity.base_cc_male["F"] == asm.morbidity.base_cc_male["F"]
