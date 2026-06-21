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
- Lapse = blended base lapse (uw mix) × UW-vs-other relativity normalised by the uw
  mix (so the blend is preserved); mortality by attained age.
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
- `trend_d`: `(1 + trend)^E` in year 1 (E = **first-year trend exponent**, an input
  defaulting to 1.75), then compounding.
- **Antiselection (column P):** `P_1 = 1`;
  `P_d = (1 + aging_d) × P_{d-1} + λ_claims × (rerate_d − trend_d)` (× antiselective-claims
  sensitivity). The lapse load uses a separate `λ_lapse`. **Both λ default to 0.5** and are
  editable on the Rerates tab.

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

### Rerate solver (front-load to floor, target lifetime LR)
When solving, the model **front-loads** rerates: each early year it takes the
largest rerate that does **not** push the in-year loss ratio below the floor
(default **65%**), capped by the max single rerate and the consecutive-rerate
rule (no more than *b* consecutive rerates above *z*). It front-loads enough years
to bring the projected **lifetime loss ratio** to its target (default **78%**),
then rides at trend; the number of front-loaded years is found by bisection (the
lifetime LR is monotone in it). If the target can't be reached within the floor
and rules, the solver does its best and reports the status. Late durations riding
at trend can drift below the in-year floor as the premium aging-rerate outpaces
age-capped claims — these are reported as diagnostics on the Calculation tab.
Each state solves independently. Per the sensitivities, rerate effectiveness
haircuts the achieved rerates after the solve (so a stressed run under-achieves
the recommended rerates).

### Aggregation
Dollar line items are summed across cells weighted by each cell's distribution
weight (re-normalised to 1 at run time); ratio metrics (loss ratio, IRR) are
re-derived from the aggregated cashflows. States are combined into an all-states
view.

### Experience study (raw data → assumptions)
- **Sales data** (raw rows) is aggregated to per-cell distribution weights and
  average premiums (overall and by state); *Adopt* writes them into the cell
  universe, overriding the defaults.
- **Claims data** (raw rows, cols A:Q) yields observed claim cost per life
  (`Σ adj_claims / Σ (cnt/12)` life-years), state factors, UW selection by
  duration, and claim-cost aging by duration. *Adopt* recalibrates the base
  claim-cost level (per plan) and state factors; selection/aging are surfaced for
  judgement.
- **AE analysis** compares actual claims to expected (best-estimate assumptions,
  excluding the pricing antiselection load) at selectable granularity.

### Premium & distribution (factor models)
- **Premium** = `base_by_issue_age (blend at plan G) × plan_rel × gender × uw ×
  preferred × hhd × state`. Two-level dims (gender, preferred, hhd) are entered as a
  single **differential** (e.g. male +15%, non-HHD +14%, non-preferred +10%) and the
  Y/N factors are derived, normalised by the business mix so the blend is preserved;
  **plan is anchored at G = 1.00**; uw is a relativity table; state is a raw factor.
  The premium is then **brought forward to the pricing period** once by
  `(1 + premium_trend)^E` (E = the same first-year trend exponent used for claims),
  mirroring how current claims are trended forward; subsequent premium changes over the
  projection are driven by the rerate solver, not by continued premium trend.
- **Morbidity** works the same way: gender claim cost is a single differential
  (+15%) on the gender-blend base table; preferred/hhd are differentials.
- **Distribution** = independent per-dimension weight factors that each sum to 1;
  a cell's weight is their product, re-normalised at run time.

### Sensitivity (stochastic)
The Sensitivity tab draws the five sensitivity factors from Normal(mean, std) each
simulation, re-solves rerates to the same lifetime-LR target, and projects an IRR.
It reports per-state IRR mean/median/confidence-interval and the share of sims that
reached the target, plus an IRR histogram. The per-state precompute is reused across
sims (numpy) so hundreds of simulations run in seconds.

### Experience study coverage
Sales data → distribution weights and the premium factor model. Claims data → base
claim cost by plan & attained age, the gender differential, state morbidity factors,
and UW selection by duration (claim-cost aging is a diagnostic). Lapse, mortality,
trend, commission and economic assumptions are not in the data and stay manual.

### Notes / deliberate choices
- Every input is an assumption — premium factors, distribution weight factors, the
  two antiselection λ (claims & lapse), and the first-year trend exponent are all
  editable; nothing pricing-relevant is hard-coded.
- Selection factors are carried forward past the source table's 5 durations.
- Acquisition costs are treated as one-time at issue; maintenance recurs.
- The in-year LR floor is a **hard** rule (rerates scaled back to respect it);
  structurally sub-floor durations are exempt and reported.
"""


def render() -> None:
    st.header("Documentation")
    st.markdown(_DOC)
