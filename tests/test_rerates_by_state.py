"""Per-state rerate overrides: round-trip and duration-1 timing in the engine."""
from __future__ import annotations

import copy

from medigap_engine.engine.run import RunConfig, run
from medigap_engine.io.defaults import default_assumptions, default_cells
from medigap_engine.io.serialize import assumptions_from_dict, assumptions_to_dict


def test_rerates_by_state_round_trips():
    a = copy.deepcopy(default_assumptions())   # lru_cached — never mutate in place
    a.rerates.by_state["TX"] = [0.05] + list(a.rerates.specified_rerates[1:])
    b = assumptions_from_dict(assumptions_to_dict(a))
    assert b.rerates.by_state["TX"][0] == 0.05
    assert b.rerates.rerates_for("TX")[0] == 0.05
    assert b.rerates.rerates_for("AZ") == list(a.rerates.specified_rerates)  # no override


def test_duration1_rerate_raises_first_year_premium():
    a = copy.deepcopy(default_assumptions())   # lru_cached — never mutate in place
    a.rerates.solve = False
    cfg = RunConfig(states=["TX", "AZ"])
    base, _ = run(default_cells(), copy.deepcopy(a), cfg)
    a.rerates.by_state["TX"] = [0.05] + list(a.rerates.specified_rerates[1:])
    new, _ = run(default_cells(), a, cfg)
    # TX first-year earned premium is 5% higher; AZ (no override) is unchanged
    assert abs(new.by_state["TX"].series["earned_prem"][0]
               / base.by_state["TX"].series["earned_prem"][0] - 1.05) < 1e-4
    assert abs(new.by_state["AZ"].series["earned_prem"][0]
               - base.by_state["AZ"].series["earned_prem"][0]) < 1e-6
