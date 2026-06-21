"""Documentation tab — methodology and formula reference."""
from __future__ import annotations

import streamlit as st

_DOC = r"""
## Medicare Supplement Pricing Model — Methodology

This model rebuilds the MS pricing workbook as a pure-Python engine
(`medigap_engine`) with a Streamlit front-end. It projects each pricing **cell**
— (issue age, gender, plan F/G/N, UW class UW/OE/GI, preferred Y/N, household
discount Y/N) — over **30 durations** and aggregates to state and all-state
income statements.

### Inforce roll-forward
- `lives_d = lives_{d-1} × (1 − total_term_d)`, starting from 1 life at issue.
- `total_term_d = 1 − (1 − lapse_d)(1 − mortality_d)`, with duration scaling
  (×1.05 in duration 2, ×1.10 in durations 3+, capped at 1).
- Lapse is looked up by (duration, UW class); mortality by attained age.
- **Antiselective lapse:** lapse is multiplied by `1 + λ × (rerate_d − trend_d)`
  (× the antiselective-lapse sensitivity).

### Premium & rerates
- Cumulative rerate `G_d = G_{d-1} × (1 + rerate_d)`.
- Cumulative aging-rerate `H_d = H_{d-1} × (1 + aging_rerate(age))`, `H_1 = 1`.
- `earned_prem_d = base_prem × G_d × H_d × avg_lives_d`.
- Achieved rerate = recommended rerate × rerate-effectiveness sensitivity.

### Claims (morbidity)
`claims_d = base_cc × selection × trend_d × antiselection_d × state_factor × avg_lives`
- `base_cc` = gender/age/plan base cost × preferred factor (UW only) × household
  factor × morbidity sensitivity.
- `selection` by (issue age, UW class, duration); carried forward beyond the
  table's last duration.
- `trend_d`: `(1 + trend)^1.75` in year 1, then compounding.
- **Antiselection (column P):** `P_1 = 1`;
  `P_d = (1 + aging_d) × P_{d-1} + λ × (rerate_d − trend_d)` (× antiselective-claims
  sensitivity). **λ defaults to 0.5** and is editable on the Rerates tab.

### Expenses, capital & income
- IBNR = ibnr% × claims; NII = avg(IBNR) × NIER.
- Commission: GI flat; else rate(state, duration) × (year-1 premium − $240 if
  plan F) × avg lives, halved for issue age ≥ 80.
- Premium tax = rate × earned premium; acquisition costs at issue; maintenance
  inflates each year.
- Pre-tax = premium + NII − claims − expenses; after-tax applies the tax rate.
- RBC = rbc% × premium × rbc factor × covariance.
- Distributable cashflow `AH_d = RBC_{d-1} − RBC_d + int_on_RBC_d + tax_on_int_d
  + after_tax_income_d`; **IRR** is computed on this stream.

### Rerate solver
When solving, the model takes rerates (as large as the rules allow) until the
projected **lifetime loss ratio** reaches the target, then trend-only rerates for
the remainder. Rules: max single rerate; no more than *b* consecutive rerates
above *z*; an in-year LR floor (reported as a diagnostic). The solver bisects a
continuous switchover point because lifetime LR is monotone in it.

### Aggregation
Dollar line items are summed across cells weighted by each cell's distribution
weight; ratio metrics (loss ratio, IRR) are re-derived from the aggregated
cashflows. States are combined into an all-states view.

### Notes / deliberate choices
- Selection factors are carried forward past the source table's 5 durations.
- Acquisition costs are treated as one-time at issue; maintenance recurs.
- The in-year LR floor is currently a diagnostic, not a hard re-solve constraint.
"""


def render() -> None:
    st.header("Documentation")
    st.markdown(_DOC)
