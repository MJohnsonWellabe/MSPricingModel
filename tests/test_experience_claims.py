import csv
import io

from medigap_engine.experience.claims import derive_morbidity
from medigap_engine.io.defaults import load_template_csv


def _row(state, plan, age, gender, uw, dur, cnt, adj):
    return {"state": state, "plan": plan, "issue_age": age, "gender": gender,
            "uw_class": uw, "duration": dur, "cnt": cnt, "earned": 100.0,
            "annualized_prem": 1200.0, "adj_claims": adj}


def test_derive_morbidity_dur1_cc():
    # 12 lives-months = 1 life-year; 1200 claims -> 1200/life-year
    rows = [_row("All", "G", 65, "M", "UW", 1, 12, 1200.0)]
    m = derive_morbidity(rows)
    assert abs(m["dur1_cc"]["G"][65] - 1200.0) < 1e-6


def test_state_factor_relative_to_all():
    rows = [
        _row("All", "G", 65, "M", "UW", 1, 12, 1000.0),
        _row("CA", "G", 65, "M", "UW", 1, 12, 2000.0),
    ]
    m = derive_morbidity(rows)
    # overall cc = 3000/2 = 1500; CA = 2000 -> factor 2000/1500
    assert abs(m["state_factors"]["CA"] - (2000.0 / 1500.0)) < 1e-6


def test_aging_by_duration_ratio():
    rows = [
        _row("All", "G", 65, "M", "UW", 1, 12, 1000.0),
        _row("All", "G", 65, "M", "UW", 5, 12, 1500.0),
    ]
    m = derive_morbidity(rows)
    assert abs(m["aging_by_duration"][1] - 1.0) < 1e-9
    assert abs(m["aging_by_duration"][5] - 1.5) < 1e-9


def test_exposure_uses_earned_fraction_not_assumed_monthly():
    # an ANNUAL row (earned == annualized_prem) is a full life-year per life, not 1/12.
    # With the old cnt/12 basis this would report 12x too high ("absurdly high").
    rows = [{"state": "All", "plan": "G", "issue_age": 65, "gender": "M",
             "uw_class": "UW", "duration": 1, "cnt": 10, "earned": 1200.0,
             "annualized_prem": 1200.0, "adj_claims": 12000.0}]
    m = derive_morbidity(rows)
    assert abs(m["dur1_cc"]["G"][65] - 1200.0) < 1e-6           # 12000 / 10 life-years
    assert abs(m["total_exposure"] - 10.0) < 1e-9


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
