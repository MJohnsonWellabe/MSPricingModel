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
