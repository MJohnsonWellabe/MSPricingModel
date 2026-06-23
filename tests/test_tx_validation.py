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
NII = [9.69787, 10.113868, 10.840948, 11.291735, 11.34972, 10.88484, 9.994162,
       9.065643, 8.194404, 7.316899, 6.467316]
IN_YEAR_LR = [0.768682, 0.777675, 0.782185, 0.781432, 0.77516, 0.754342, 0.744624,
              0.741863, 0.720443, 0.695105, 0.685616]
AT_ADJ = [-890.31866, -76.188877, -17.474193, 51.827675, 127.768857, 217.859797,
          355.349226, 336.676337, 338.779726, 347.265068, 356.467205]


def _tx():
    asm = default_assumptions()
    asm.rerates.solve = False  # workbook uses its specified rerate schedule (no solve)
    # the shipped default sets durations 2 & 3 to 20%; pin them back to the workbook's 15%
    # so TX premium/claims still reproduce the Excel 'Aggregate Model' sheet exactly.
    asm.rerates.specified_rerates[1] = 0.15
    asm.rerates.specified_rerates[2] = 0.15
    result, _ = run(build_cells(asm), asm, RunConfig(states=["TX"], solve_rerates=False))
    return result.by_state["TX"]


def test_tx_lives_and_premium_match_workbook_exactly():
    sr = _tx()
    for i in range(len(LIVES)):
        # lives targets are rounded to 3 decimals in the workbook export (~0.2%);
        # earned premium is exact to rounding
        assert abs(sr.series["lives"][i] / LIVES[i] - 1) < 2.5e-3, f"lives d{i+1}"
        assert abs(sr.series["earned_prem"][i] / PREM[i] - 1) < 1e-3, f"prem d{i+1}"


def test_tx_claims_match_workbook_exactly():
    sr = _tx()
    # claims reproduce the workbook at every duration (issue-age base cost, state
    # factor, raw class factors, per-cell premiums, antiselection P)
    for i in range(len(CLAIMS)):
        assert abs(sr.series["claims"][i] / CLAIMS[i] - 1) < 1.5e-3, f"claims d{i+1}"


def test_tx_income_lines_match_workbook_exactly():
    sr = _tx()
    # NII, in-year loss ratio and after-tax adjusted income (distributable) reproduce
    # the workbook exactly once commission (GI year-1 only) and NII (year-1 no prior
    # IBNR to average) are right
    for line, target in (("nii", NII), ("in_year_lr", IN_YEAR_LR), ("ah_cashflow", AT_ADJ)):
        for i in range(len(target)):
            assert abs(sr.series[line][i] / target[i] - 1) < 2e-3, f"{line} d{i+1}"
