from medigap_engine.engine import lookups as L
from medigap_engine.experience.port import apply_claims, apply_sales


def test_apply_sales_updates_distribution_and_premium(asm):
    # two cells differing only by gender; sales says 75% male, 25% female
    k_m = (65, "M", "G", "UW", "Y", "Y")
    k_f = (65, "F", "G", "UW", "Y", "Y")
    sales = {
        "counts": {k_m: 75.0, k_f: 25.0},
        "weights": {k_m: 0.75, k_f: 0.25},
        "avg_premium": {k_m: 2300.0, k_f: 2000.0},
        "state_premiums": {k_m: {"TX": 2208.0}, k_f: {"TX": 1920.0}},
    }
    new = apply_sales(asm, sales)
    # distribution gender marginal reflects the 75/25 split
    assert abs(new.distribution.gender["M"] - 0.75) < 1e-6
    assert abs(new.distribution.gender["F"] - 0.25) < 1e-6
    # premium for a male cell exceeds the female cell (male factor higher)
    from medigap_engine.models.cell import CellKey
    km = CellKey(65, "M", "G", "UW", "Y", "Y")
    kf = CellKey(65, "F", "G", "UW", "Y", "Y")
    assert new.premium.premium(km, "All") > new.premium.premium(kf, "All")
    # TX premium ~ 4% below the All/composite for both (2208/2300)
    assert new.premium.state_factor["TX"] < 1.0


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
