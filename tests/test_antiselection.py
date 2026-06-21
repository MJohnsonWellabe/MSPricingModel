"""The column-P antiselection recurrence is central to the model, so it gets its
own focused test:

    P_1 = 1
    P_d = (1 + aging_d) * P_{d-1} + lambda * (rerate_d - trend_d)
"""
from medigap_engine.engine import lookups as L
from medigap_engine.engine.project import project_cell


def _expected_antiselection(asm, rerates, lam):
    n = 30
    trend = asm.morbidity.trend_by_year
    P = [0.0] * n
    P_prev = 1.0
    for i in range(n):
        d = i + 1
        if d == 1:
            P[i] = 1.0
        else:
            aging = L.cc_aging_duration(asm, d)
            P[i] = (1 + aging) * P_prev + lam * (rerates[i] - trend[min(d, len(trend)) - 1])
        P_prev = P[i]
    return P


def test_antiselection_matches_recurrence(asm, sample_cell, base_sens):
    rerates = list(asm.rerates.specified_rerates)
    lam = asm.rerates.antiselection_lambda_claims
    res = project_cell(sample_cell, asm, base_sens, "All", rerates)
    got = res.projection.series["antiselection"]
    exp = _expected_antiselection(asm, rerates, lam)
    for g, e in zip(got, exp):
        assert abs(g - e) < 1e-9


def test_antiselection_first_duration_is_one(asm, sample_cell, base_sens):
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    assert abs(res.projection.series["antiselection"][0] - 1.0) < 1e-12


def test_lambda_zero_removes_rerate_term(asm, sample_cell, base_sens):
    asm.rerates.antiselection_lambda_claims = 0.0
    res = project_cell(sample_cell, asm, base_sens, "All",
                       list(asm.rerates.specified_rerates))
    P = res.projection.series["antiselection"]
    # with lambda 0, P is a pure compounding of (1+aging) starting from 1
    P_prev = 1.0
    from medigap_engine.engine import lookups as L
    for i in range(1, 30):
        aging = L.cc_aging_duration(asm, i + 1)
        P_prev = (1 + aging) * P_prev
        assert abs(P[i] - P_prev) < 1e-9
