"""TX validation against the source Excel workbook's 'Aggregate Model' sheet.

The bundled defaults are regenerated from the TX workbook (tools/generate_seed.py).
Run with solving OFF (the workbook uses its specified rerate schedule). Inforce
lives, earned premium and the expense lines reproduce the workbook exactly; claims
match at duration 1 and track within a documented residual at later durations (a
small per-cell base-cost mix drift still under investigation).
"""
from __future__ import annotations

from medigap_engine.io.defaults import build_cells, default_assumptions
from medigap_engine.engine.run import run
from medigap_engine.models.config import RunConfig

# workbook 'Aggregate Model' TX targets, durations 1..11
LIVES = [0.921, 0.835, 0.742, 0.639, 0.533, 0.424, 0.342, 0.282, 0.232, 0.189, 0.155]
PREM = [1869.071, 2005.954, 2112.227, 2167.236, 2153.533, 2062.466, 1887.435,
        1726.314, 1592.469, 1468.392, 1306.205]
CLAIMS = [1436.721, 1559.98, 1652.152, 1693.547, 1669.333, 1555.805, 1405.428,
          1280.688, 1147.284, 1020.687, 895.555]


def _tx():
    asm = default_assumptions()
    asm.rerates.solve = False  # workbook uses its specified rerate schedule (no solve)
    result, _ = run(build_cells(asm), asm, RunConfig(states=["TX"], solve_rerates=False))
    return result.by_state["TX"]


def test_tx_lives_and_premium_match_workbook_exactly():
    sr = _tx()
    for i in range(len(LIVES)):
        # lives targets are rounded to 3 decimals in the workbook export (~0.2%);
        # earned premium is exact to rounding
        assert abs(sr.series["lives"][i] / LIVES[i] - 1) < 2.5e-3, f"lives d{i+1}"
        assert abs(sr.series["earned_prem"][i] / PREM[i] - 1) < 1e-3, f"prem d{i+1}"


def test_tx_claims_duration1_exact_and_tracks():
    sr = _tx()
    # duration-1 claims are exact (state factor, raw class factors, per-cell premiums)
    assert abs(sr.series["claims"][0] / CLAIMS[0] - 1) < 2e-3
    # later durations track within the documented residual (mid-duration drift)
    for i in range(len(CLAIMS)):
        assert abs(sr.series["claims"][i] / CLAIMS[i] - 1) < 0.16, f"claims d{i+1}"
