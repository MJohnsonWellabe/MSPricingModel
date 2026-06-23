"""The Excel assumptions round-trip (export -> import) must reproduce priced results
exactly, matching the JSON round-trip. Regression for the lossy hand-parser that dropped
per-cell premiums, per-state distribution grids/marginals, weights, and rerate overrides."""
import copy
import io

from medigap_engine.engine.run import run
from medigap_engine.experience.claims import derive_morbidity
from medigap_engine.experience.port import apply_claims, apply_sales
from medigap_engine.experience.sales import aggregate_sales
from medigap_engine.io.defaults import default_assumptions, default_cells
from medigap_engine.io.excel_export import assumptions_to_xlsx_bytes
from medigap_engine.io.excel_import import assumptions_from_workbook
from medigap_engine.io.serialize import assumptions_from_dict, assumptions_to_dict
from medigap_engine.models.config import RunConfig

# a small synthetic experience set so the adopted assumptions carry per-state overrides,
# per-cell premiums, weights and marginals (the fields the Excel parser used to drop)
_CLAIMS = [
    {"state": "TX", "plan": "G", "issue_age": "65", "uw": "UW", "gender": "M",
     "duration": "1", "exposure": "1000", "claims": "1200"},
    {"state": "AZ", "plan": "N", "issue_age": "73", "uw": "OE", "gender": "F",
     "duration": "2", "exposure": "800", "claims": "1500"},
]
_SALES = [
    {"state": "TX", "plan": "G", "issue_age": "65", "uw": "UW", "gender": "M",
     "preferred": "Y", "hhd": "Y", "count": "500"},
    {"state": "AZ", "plan": "N", "issue_age": "73", "uw": "OE", "gender": "F",
     "preferred": "N", "hhd": "N", "count": "300"},
]


def _adopted():
    a = copy.deepcopy(default_assumptions())
    a = apply_sales(a, aggregate_sales(_SALES), parts=("distribution", "premium"))
    a = apply_claims(a, derive_morbidity(_CLAIMS), credibility_standard=2000.0)
    a.rerates.by_state["TX"] = [0.05] + list(a.rerates.specified_rerates[1:])
    a.rerates.target_lifetime_lr_by_state["AZ"] = 0.72
    return a


def _price(a):
    cfg = RunConfig(states=["TX", "AZ"], solve_rerates=False)
    res, _ = run(default_cells(), a, cfg)
    return {s: res.by_state[s].series["earned_prem"] + res.by_state[s].series["claims"]
            for s in ("TX", "AZ")}


def test_excel_round_trip_reproduces_priced_results():
    a = _adopted()
    target = _price(a)

    # JSON round-trip (known good) ...
    json_back = assumptions_from_dict(assumptions_to_dict(a))
    assert _price(json_back) == target

    # ... and the Excel round-trip must match it exactly
    xlsx = assumptions_to_xlsx_bytes(a)
    xl_back = assumptions_from_dict(assumptions_from_workbook(io.BytesIO(xlsx)))
    got = _price(xl_back)
    for s in ("TX", "AZ"):
        assert got[s] == target[s], f"{s} differs after Excel round-trip"
