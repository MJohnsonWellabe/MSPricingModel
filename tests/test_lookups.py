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
