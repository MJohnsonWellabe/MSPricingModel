import json

from medigap_engine.io.defaults import default_assumptions
from medigap_engine.io.serialize import assumptions_from_dict, assumptions_to_dict


def test_round_trip_equains():
    a = default_assumptions()
    d = assumptions_to_dict(a)
    # must be JSON serialisable
    text = json.dumps(d)
    b = assumptions_from_dict(json.loads(text))
    assert b.other.discount_rate == a.other.discount_rate
    assert b.morbidity.ages == a.morbidity.ages
    assert b.morbidity.base_cc_male == a.morbidity.base_cc_male
    assert b.termination.base_lapse == a.termination.base_lapse
    assert b.rerates.antiselection_lambda == a.rerates.antiselection_lambda
    assert len(b.morbidity.selection_factors) == len(a.morbidity.selection_factors)


def test_default_assumptions_load_sane():
    a = default_assumptions()
    assert a.morbidity.plans == ["F", "G", "N"]
    assert len(a.morbidity.trend_by_year) >= 30
    assert 0 < a.other.tax_rate < 1
    assert a.rerates.antiselection_lambda == 0.5
