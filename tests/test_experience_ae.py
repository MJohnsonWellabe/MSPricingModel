from medigap_engine.experience.ae import actual_to_expected


def _row(state, plan, age, gender, uw, dur, cnt, adj):
    return {"state": state, "plan": plan, "issue_age": age, "gender": gender,
            "uw_class": uw, "duration": dur, "cnt": cnt, "earned": 100.0,
            "annualized_prem": 1200.0, "adj_claims": adj}


def test_ae_groups_by_state(asm):
    rows = [
        _row("TX", "G", 65, "M", "UW", 1, 12, 1000.0),
        _row("FL", "G", 65, "M", "UW", 1, 12, 500.0),
    ]
    out = actual_to_expected(rows, asm, by=("state",))
    states = {r["state"] for r in out}
    assert states == {"TX", "FL"}
    for r in out:
        assert r["expected"] > 0
        assert r["ae"] == r["actual"] / r["expected"]


def test_ae_rolls_up(asm):
    rows = [
        _row("TX", "G", 65, "M", "UW", 1, 12, 1000.0),
        _row("FL", "G", 65, "M", "UW", 1, 12, 500.0),
    ]
    per_state = actual_to_expected(rows, asm, by=("state",))
    allup = actual_to_expected(rows, asm, by=())
    assert len(allup) == 1
    assert abs(allup[0]["actual"] - sum(r["actual"] for r in per_state)) < 1e-6


def test_ae_expected_excludes_pull_forward_and_trend(asm):
    # expected is best-estimate (experience level): base_cc x selection x state factor,
    # WITHOUT the pull-forward bring-forward or projection trend. With a non-zero claims
    # pull-forward, expected must NOT be inflated by it (which previously pushed all A/E < 1).
    from medigap_engine.engine import lookups as L
    asm.pull_forward.claims_trend = 0.10
    asm.pull_forward.duration = 1.75
    rows = [_row("TX", "G", 65, "M", "OE", 1, 100, 9999.0)]
    out = actual_to_expected(rows, asm, by=("issue_age",))
    exp_per_life = out[0]["expected"] / out[0]["exposure"]
    best_estimate = (L.base_claim_cost(asm, "M", 65, "G", bring_forward=False)
                     * L.selection_factor(asm, 65, "OE", 1)
                     * asm.morbidity.state_factors.get("TX",
                       asm.morbidity.state_factors.get("All", 1.0)))
    assert abs(exp_per_life - best_estimate) < 1e-6
    # and it is strictly below the pulled-forward level (so the fix actually changed it)
    pulled = L.base_claim_cost(asm, "M", 65, "G", bring_forward=True)
    assert best_estimate < pulled - 1e-9
