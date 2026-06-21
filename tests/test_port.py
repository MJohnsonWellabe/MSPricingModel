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
    # the joint grid captures the (plan, age, uw) mix: both cells are G/65/UW -> 1.0
    assert abs(new.distribution.joint["G"]["65"]["UW"] - 1.0) < 1e-6
    assert abs(sum(w for ages in new.distribution.joint.values()
                   for uws in ages.values() for w in uws.values()) - 1.0) < 1e-6
    # plan relativity is anchored at G = 1.0
    assert abs(new.premium.plan_rel["G"] - 1.0) < 1e-9
    # premium for a male cell exceeds the female cell (male relativity higher)
    from medigap_engine.engine import lookups as L
    from medigap_engine.models.cell import CellKey
    km = CellKey(65, "M", "G", "UW", "Y", "Y")
    kf = CellKey(65, "F", "G", "UW", "Y", "Y")
    assert L.premium_for_cell(new, km, "All") > L.premium_for_cell(new, kf, "All")
    # TX premium ~ 4% below the All/composite for both (2208/2300)
    assert new.premium.state_factor["TX"] < 1.0


def test_apply_claims_adopts_base_gender_state_selection(asm):
    ages = asm.morbidity.ages
    claims = {
        "base_cc_by_age": {"G": {a: 1000.0 for a in ages}},   # flat observed G curve
        "gender_diff": 0.20,
        "state_factors": {"CA": 1.5},
        "selection_rows": [{"issue_age": 65, "uw": "UW", "duration": 1, "factor": 0.8}],
        "aging_by_duration": {},
    }
    new = apply_claims(asm, claims)
    assert new.morbidity.base_cc["G"] == [1000.0] * len(ages)   # adopted age curve
    assert new.morbidity.base_cc["F"] == asm.morbidity.base_cc["F"]  # plan F untouched
    assert new.morbidity.gender_cc_diff == 0.20
    assert new.morbidity.state_factors["CA"] == 1.5
    assert new.morbidity.selection_factors == [
        {"issue_age": 65, "uw": "UW", "duration": 1, "factor": 0.8}]
