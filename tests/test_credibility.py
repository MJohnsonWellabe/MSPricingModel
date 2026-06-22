from medigap_engine.experience.credibility import blend, credibility_z


def test_z_sqrt_rule():
    assert credibility_z(0.0, 1000.0) == 0.0
    assert abs(credibility_z(250.0, 1000.0) - 0.5) < 1e-9     # sqrt(0.25)
    assert credibility_z(1000.0, 1000.0) == 1.0
    assert credibility_z(5000.0, 1000.0) == 1.0               # capped at 1
    assert credibility_z(123.0, 0.0) == 1.0                   # 0 standard -> full credibility


def test_blend():
    assert blend(100.0, 200.0, 0.0) == 200.0    # no credibility -> pricing
    assert blend(100.0, 200.0, 1.0) == 100.0    # full credibility -> experience
    assert blend(100.0, 200.0, 0.25) == 175.0
