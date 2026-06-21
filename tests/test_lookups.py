from medigap_engine.engine import lookups as L


def test_mortality_increases_with_age(asm):
    q70 = asm.termination.mortality(70)
    q90 = asm.termination.mortality(90)
    assert 0 < q70 < q90 < 1


def test_mortality_caps_at_table_max(asm):
    top = max(asm.termination.mort_age)
    assert asm.termination.mortality(150) == asm.termination.mortality(top)


def test_selection_carries_forward_beyond_table(asm):
    # table only defines durations 1..5; later durations should reuse the last
    f5 = L.selection_factor(asm, 65, "OE", 5)
    f10 = L.selection_factor(asm, 65, "OE", 10)
    assert f10 == f5


def test_base_claim_cost_plan_ordering(asm):
    # for a given age, plan F (richest benefit) should cost more than plan N
    f = L.base_claim_cost(asm, "M", 70, "F")
    n = L.base_claim_cost(asm, "M", 70, "N")
    assert f > n > 0


def test_claim_class_factors_preferred_only_for_uw(asm):
    uw = L.claim_class_factors(asm, "UW", "Y", "N")
    oe = L.claim_class_factors(asm, "OE", "Y", "N")
    # preferred factor applies only for UW, so the two differ by the preferred factor
    assert uw != oe


def test_base_claim_cost_gender_factor(asm):
    # male = base x gender factor; female = base (reference) when F factor is 1
    m = L.base_claim_cost(asm, "M", 70, "G")
    f = L.base_claim_cost(asm, "F", 70, "G")
    assert abs(m / f - asm.morbidity.gender_cc_factor["M"]) < 1e-9


def test_derive_two_level_reproduces_workbook():
    from medigap_engine.models.assumptions import derive_two_level
    # 90% preferred, 'no' 10% higher -> 0.990099 / 1.089109
    f = derive_two_level(0.9, 0.10)
    assert abs(f["Y"] - 0.990099) < 1e-5
    assert abs(f["N"] - 1.089109) < 1e-5
    # distribution-weighted mean is 1
    assert abs(0.9 * f["Y"] + 0.1 * f["N"] - 1.0) < 1e-9


def test_uw_lapse_factor_applied(asm):
    base = L.lapse_rate(asm, "OE", 1)
    uw = L.lapse_rate(asm, "UW", 1)
    assert abs(uw / base - asm.termination.uw_lapse_factor[0]) < 1e-9
    # OE and GI both use the base (factor 1)
    assert L.lapse_rate(asm, "GI", 1) == base
