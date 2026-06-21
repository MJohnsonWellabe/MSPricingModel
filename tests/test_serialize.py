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
    assert b.morbidity.base_cc == a.morbidity.base_cc
    assert b.morbidity.gender_cc_diff == a.morbidity.gender_cc_diff
    assert b.premium.gender_diff == a.premium.gender_diff
    assert b.premium.hhd_diff == a.premium.hhd_diff
    assert b.morbidity.preferred_diff == a.morbidity.preferred_diff
    assert b.termination.uw_lapse_rel == a.termination.uw_lapse_rel
    assert b.termination.base_lapse == a.termination.base_lapse
    assert b.rerates.antiselection_lambda_claims == a.rerates.antiselection_lambda_claims
    assert b.rerates.antiselection_lambda_lapse == a.rerates.antiselection_lambda_lapse
    assert b.morbidity.trend_first_year_exponent == a.morbidity.trend_first_year_exponent
    assert len(b.morbidity.selection_factors) == len(a.morbidity.selection_factors)
    assert b.premium.base_by_issue_age == a.premium.base_by_issue_age
    assert b.premium.plan_rel == a.premium.plan_rel
    assert b.distribution.gender == a.distribution.gender
    assert b.distribution.by_issue_age == a.distribution.by_issue_age


def test_default_assumptions_load_sane():
    a = default_assumptions()
    assert a.morbidity.plans == ["F", "G", "N"]
    assert len(a.morbidity.trend_by_year) >= 30
    assert 0 < a.other.tax_rate < 1
    # distribution weight factors each sum to 1
    for dim in (a.distribution.by_issue_age, a.distribution.gender, a.distribution.plan,
                a.distribution.uw, a.distribution.preferred, a.distribution.hhd):
        assert abs(sum(dim.values()) - 1.0) < 1e-4
    assert a.rerates.max_rerate == 0.20
    assert a.rerates.consecutive_z == 0.15
    assert a.rerates.consecutive_b == 5
    assert a.rerates.antiselection_lambda_claims == 0.5
    assert a.rerates.antiselection_lambda_lapse == 0.5
    assert a.morbidity.trend_first_year_exponent == 1.75
    assert a.rerates.target_lifetime_lr == 0.78
    assert a.rerates.in_year_lr_floor == 0.65
