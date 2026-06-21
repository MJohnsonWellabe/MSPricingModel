import math

from medigap_engine.engine.metrics import irr, npv


def test_npv_matches_manual():
    cfs = [100, 100, 100]
    r = 0.1
    expected = 100 / 1.1 + 100 / 1.1**2 + 100 / 1.1**3
    assert math.isclose(npv(r, cfs), expected, rel_tol=1e-12)


def test_irr_simple_project():
    # -1000 now, +600, +600 -> known IRR ~ 13.07%
    cfs = [-1000, 600, 600]
    rate = irr(cfs)
    # verify it zeroes the (t=0) NPV
    val = sum(cf / (1 + rate) ** t for t, cf in enumerate(cfs))
    assert abs(val) < 1e-6
    assert 0.12 < rate < 0.14


def test_irr_all_positive_is_nan():
    assert math.isnan(irr([10, 20, 30]))


def test_irr_handles_large_cashflows():
    # should not overflow
    cfs = [-1e6] + [5e5] * 30
    rate = irr(cfs)
    assert not math.isnan(rate)
