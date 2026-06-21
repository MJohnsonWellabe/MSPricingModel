"""The assumptions Excel export round-trips back through the importer: exporting
then re-importing reproduces the assumptions (and the model results)."""
from __future__ import annotations

import copy
import io

from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.io.excel_export import assumptions_to_xlsx_bytes
from medigap_engine.io.excel_import import assumptions_from_workbook
from medigap_engine.io.serialize import assumptions_from_dict


def _round_trip(a):
    data = assumptions_to_xlsx_bytes(a)
    doc = assumptions_from_workbook(io.BytesIO(data))
    return assumptions_from_dict(doc)


def test_round_trip_scalars_and_tables():
    a = default_assumptions()
    b = _round_trip(a)
    assert b.pull_forward.duration == a.pull_forward.duration
    assert b.premium.base_by_issue_age == a.premium.base_by_issue_age
    assert b.premium.plan_rel == a.premium.plan_rel
    assert b.morbidity.base_cc == a.morbidity.base_cc
    assert b.commission.by_state == a.commission.by_state
    assert b.termination.mort_age == a.termination.mort_age
    assert b.termination.mort_qx == a.termination.mort_qx
    assert b.rerates.solve == a.rerates.solve
    assert b.commission.age80_halving == a.commission.age80_halving
    assert b.other.discount_rate == a.other.discount_rate


def test_round_trip_distribution_joint():
    a = default_assumptions()
    b = _round_trip(a)
    # the joint grid (and derived marginals) survive the round trip
    for pl in a.distribution.joint:
        for age in a.distribution.joint[pl]:
            for uw, w in a.distribution.joint[pl][age].items():
                assert abs(b.distribution.joint[pl][age][uw] - w) < 1e-9
    assert b.distribution.gender == a.distribution.gender


def test_round_trip_non_separable_grid():
    # a hand-built non-separable grid must come back intact (not collapsed to marginals)
    a = copy.deepcopy(default_assumptions())
    a.distribution.joint = {
        "G": {"65": {"UW": 0.5, "OE": 0.05, "GI": 0.0},
              "73": {"UW": 0.0, "OE": 0.15, "GI": 0.05}},
        "N": {"65": {"UW": 0.1, "OE": 0.0, "GI": 0.0},
              "73": {"UW": 0.0, "OE": 0.1, "GI": 0.0}},
    }
    b = _round_trip(a)
    assert abs(b.distribution.joint["G"]["65"]["UW"] - 0.5) < 1e-9
    assert abs(b.distribution.joint["N"]["73"]["OE"] - 0.1) < 1e-9


def test_round_trip_preserves_cell_weights():
    a = default_assumptions()
    b = _round_trip(a)
    wa = {c.key.label(): c.weight for c in build_cells(a)}
    wb = {c.key.label(): c.weight for c in build_cells(b)}
    assert wa.keys() == wb.keys()
    for k in wa:
        assert abs(wa[k] - wb[k]) < 1e-9
