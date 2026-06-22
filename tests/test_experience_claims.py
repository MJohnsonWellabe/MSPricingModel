import csv
import io

from medigap_engine.experience.claims import derive_morbidity
from medigap_engine.io.defaults import load_template_csv


def _row(state, plan, age, gender, uw, dur, cnt, adj):
    # cnt is the exposure in life-years; earned/annualized_prem are unused for exposure
    return {"state": state, "plan": plan, "issue_age": age, "gender": gender,
            "uw_class": uw, "duration": dur, "cnt": cnt, "earned": 100.0,
            "annualized_prem": 1200.0, "adj_claims": adj}


def test_derive_morbidity_dur1_cc():
    # exposure = cnt life-years; 1200 claims over 1 life-year -> 1200/life
    rows = [_row("All", "G", 65, "M", "UW", 1, 1, 1200.0)]
    m = derive_morbidity(rows)
    assert abs(m["dur1_cc"]["G"][65] - 1200.0) < 1e-6


def test_state_factor_relative_to_all():
    rows = [
        _row("All", "G", 65, "M", "UW", 1, 1, 1000.0),
        _row("CA", "G", 65, "M", "UW", 1, 1, 2000.0),
    ]
    m = derive_morbidity(rows)
    # overall cc = 3000/2 = 1500; CA = 2000 -> factor 2000/1500
    assert abs(m["state_factors"]["CA"] - (2000.0 / 1500.0)) < 1e-6


def test_aging_by_duration_ratio():
    rows = [
        _row("All", "G", 65, "M", "UW", 1, 1, 1000.0),
        _row("All", "G", 65, "M", "UW", 5, 1, 1500.0),
    ]
    m = derive_morbidity(rows)
    assert abs(m["aging_by_duration"][1] - 1.0) < 1e-9
    assert abs(m["aging_by_duration"][5] - 1.5) < 1e-9


def test_exposure_is_the_count_column_not_monthly():
    # cnt IS the exposure (life-years); 12000 claims over 10 life-years -> 1200/life.
    # The old cnt/12 basis reported this 12x too high ("absurdly high").
    rows = [_row("All", "G", 65, "M", "UW", 1, 10, 12000.0)]
    m = derive_morbidity(rows)
    assert abs(m["dur1_cc"]["G"][65] - 1200.0) < 1e-6
    assert abs(m["total_exposure"] - 10.0) < 1e-9


def test_explicit_exposure_column_overrides_cnt():
    rows = [{"state": "All", "plan": "G", "issue_age": 65, "gender": "M",
             "uw_class": "UW", "duration": 1, "cnt": 999, "exposure": 4.0,
             "adj_claims": 8000.0}]
    m = derive_morbidity(rows)
    assert abs(m["dur1_cc"]["G"][65] - 2000.0) < 1e-6           # 8000 / 4 life-years


def test_base_cc_keyed_by_issue_age():
    # duration 3 at issue age 65 still keys the base level under issue age 65
    rows = [_row("All", "G", 65, "M", "UW", 3, 12, 1500.0)]
    m = derive_morbidity(rows)
    assert 65 in m["base_cc_by_issue_age"]["G"]
    assert "base_cc_by_age" not in m


def test_claims_sample_loads():
    text = load_template_csv("claims_sample.csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    m = derive_morbidity(rows)
    assert m["n_rows"] > 0
    assert m["overall_cc"] > 0


def test_aging_from_attained_age_monotone():
    # claims rise with ATTAINED age; duration is flat. Aging must come out increasing.
    rows = []
    for issue in (65, 70):
        for dur in range(1, 6):
            att = issue + dur - 1
            cc = 1000.0 + 40.0 * (att - 65)        # +4%/yr by attained age
            rows.append(_row("All", "G", issue, "M", "UW", dur, 100, cc * 100 / 1.0))
    m = derive_morbidity(rows)
    ac = m["aging_curve"]
    assert ac[1] == 1.0
    assert all(ac[d] >= ac[d - 1] - 1e-9 for d in range(2, 31))   # monotone
    assert ac[10] > 1.05                                          # genuinely ages up


def test_isotonic_monotone():
    from medigap_engine.experience.claims import _isotonic
    out = _isotonic([1.0, 3.0, 2.0, 5.0], [1, 1, 1, 1])
    assert all(out[i] <= out[i + 1] + 1e-9 for i in range(len(out) - 1))
