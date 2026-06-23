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
- **The duration-1 rerate applies in year 1** (unlike trend, which starts in year 2):
  `earned_prem_1 = base_prem × (1 + rerate_1)`. Enter a known upcoming rate action as the
  duration-1 rerate to reflect increases not captured in the experience. Rerates can be
  **overridden per state** on the Assumptions → Rerates tab (default = the shared schedule).

### Claims (morbidity)
`claims_d = base_cc × selection × trend_d × antiselection_d × state_factor × avg_lives`
- `base_cc` = gender/age/plan base cost × preferred factor (UW only) × household
  factor × morbidity sensitivity, **pulled forward** to the pricing period by
  `(1 + claims_trend)^duration` (the one-time bring-forward on the Pull forward tab).
- `selection` by (issue age, UW class, duration); carried forward beyond the
  table's last duration.
- `trend_d` (projection trend): the pulled-forward base **is** the year-1 level, so
  the cumulative trend factor is `1.0` in year 1 and compounds `(1 + trend_d)` from
  year 1→2 onward. The pull-forward claims trend need not equal the year-1 projection
  trend.
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

**Lifetime loss ratio vs the Claims % margin column.** On the Output tab the **lifetime LR**
is *undiscounted* — cumulative claims ÷ cumulative premium over the 30-year projection. The
**Claims %** in the source-of-margin walk is *NPV-discounted* — `NPV(claims) ÷ NPV(premium)`
at the discount rate. Because premium is relatively heavier in the (less-discounted) early
years while claims build by duration, the discounted Claims % sits **below** the
undiscounted lifetime LR; they are different views, not an inconsistency.

### Experience study (raw data → assumptions)
The study turns two raw files into pricing assumptions. Each piece is shown **current vs
experience vs adopted** and is adopted independently (or all at once); nothing changes
until you adopt.

**Exposure.** Claim cost per life-year uses **exposure = the `exposure` column if present,
else `cnt`** (which already carries annualized life-years). Premium per policy-year uses
`Σearned / Σcnt`. (An earlier `cnt/12` over-divided and inflated costs ~12×.)

**Sales data → distribution & premium** (`experience/sales.py aggregate_sales`,
`experience/port.py apply_sales`):
- A national **joint plan × issue-age × UW grid** plus gender / preferred / HHD marginals,
  and a **per-state grid** (mix varies by state). Each state's grid is credibility-blended
  toward the average of its **like type** — **Special Enrollment Period (SEP)** states
  (editable Yes/No on the Distribution tab) skew to open-enrolment; regular states skew
  underwritten.
- Premium **differentials are isolated by a multivariate fit** (each holds the others
  fixed), so e.g. the UW relativity reflects underwriting alone, not a confounded marginal
  (OE applicants are ~99% preferred, which would otherwise make OE look cheap).
- Adopting premiums also writes **per-cell premiums** from the sales averages (these
  dominate the priced premium), so adoption actually moves pricing.

**Claims data → morbidity** (`experience/claims.py derive_morbidity`,
`experience/port.py apply_claims`). The engine prices a cell's claim as
`base_cc(issue_age) × class_factors(pref,hhd) × selection(issue_age,uw,dur) × O_d(trend) ×
P_d(aging + antiselection) × state_factor`, so the study targets each of those pieces:
- **Base claim cost** = the **all-UW, duration-1 blended** claim cost per life-year by
  (plan, issue age). It is applied constant across duration in the engine — the duration
  shape lives in selection × aging — so it is the *first-year* level (matching a direct
  duration-1 pull from the data).
- **State factor** = the **isolated (mix-free) duration-1** state effect, from a
  multivariate fit over (state, plan, issue_age, gender, uw) normalised to a 1.0 mean.
  Because each state's own age/UW mix is already applied through its distribution grid, the
  state factor must be the pure per-state level — the raw state/national average would
  double-count the mix (a state skewed to young/UW cells looks cheap on average but runs
  above national cell-for-cell).
- **Selection** = a **duration-1 level** by (issue_age, uw), relative to the all-UW/dur1
  blend (so OE ramps up with issue age as it antiselects, UW < 1, GI > 1), times a
  **duration wear-off** taken from the well-populated (uw, duration) data, **net of the
  aging slope** so it is not double-counted with the engine's aging. Estimating the
  wear-off per (issue_age, uw, duration) cell was too thin and injected noise.
- **Aging** = an exposure-weighted **log-linear fit of ln(claim cost) on attained age** →
  one robust morbidity %/yr, applied as `(1 + rate)^(duration−1)`. Attained age is used
  (not policy duration) because the data has only ~6 durations; walking a noisy attained-age
  curve out from a single reference age previously caught a local blip.
- **Gender** differential is the **isolated** (multivariate) male-vs-female load.
- **Credibility:** each band is blended toward current pricing with
  `Z = min(1, √(exposure / standard))` (full-credibility standard is yours to set); thin
  bands (e.g. high durations) revert to pricing.

**AE analysis** compares actual claims to expected (best-estimate assumptions, excluding the
pricing antiselection load) at a granularity you choose.

### Premium & distribution (factor models)
- **Premium** = `base_by_issue_age (blend at plan G) × plan_rel × gender × uw ×
  preferred × hhd × state`. Two-level dims (gender, preferred, hhd) are entered as a
  single **differential** (e.g. male +15%, non-HHD +14%, non-preferred +10%) and the
  Y/N factors are derived, normalised by the business mix so the blend is preserved;
  **plan is anchored at G = 1.00**; uw is a relativity table; state is a raw factor.
  The premium is then **pulled forward to the pricing period** once by
  `(1 + premium_trend)^duration` (the Pull forward tab; same `duration` as claims),
  mirroring how current claims are pulled forward; subsequent premium changes over the
  projection are driven by the rerate solver, not by continued premium trend.
- **Morbidity** works the same way: gender claim cost is a single differential
  (+15%) on the gender-blend base table; preferred/hhd are differentials.
- **Distribution** = independent per-dimension weight factors that each sum to 1;
  a cell's weight is their product, re-normalised at run time.

### Sensitivity (stochastic)
The Sensitivity tab draws the five sensitivity factors from Normal(mean, std) each
simulation, re-solves rerates to the same lifetime-LR target, and projects. It reports
IRR mean/median/confidence-interval, the share of sims that reached the target, an IRR
histogram, and the **pre-tax-income range by year** (P-lo / expected / P-hi). Two modes:
- **Per state** — each state's own IRR distribution (equal book per state).
- **Portfolio (pooled per-state)** — each draw prices every state with its own factors and
  **pools the cashflows** into one IRR, so the distribution centres on the deterministic
  combined-book run. (The 'National (All)' single projection reads higher because it ignores
  the per-state morbidity/premium/commission loadings — the per-state pool is the true book.)

Drilling into a result re-projects a chosen scenario (P5 / median / P95 IRR draw) to its
**full income statement**. The per-state precompute is reused across sims (numpy).

### Experience study coverage
Sales data → distribution weights and the premium factor model. Claims data → base
claim cost by plan & issue age, the gender differential, state morbidity factors,
and UW selection by duration (claim-cost aging is a diagnostic). Each table can be
adopted separately or all at once; the suggested differentials are editable before
adopting. Lapse, mortality, trend, commission and economic assumptions are not in the
data and stay manual.

### Formula Database (editable engine)
Every per-duration line item — lives, lapse, premium, claims, expenses, income and
capital — is an **editable expression** over a resolved variable namespace
(lookups + prior-duration carry + assumption scalars). The same expressions evaluate
on scalars (the per-cell projection) and on numpy arrays (the rerate solver and the
stochastic engine), so editing a formula stays consistent everywhere. Expressions are
parsed against a strict whitelist (arithmetic, comparisons, `if/else`, and the helpers
`minimum/maximum/clamp/where/abs`) — no attribute access, imports or other calls. The
**Validate** button parses and test-evaluates the whole set on a sample namespace
before a run. Loss ratio, IRR and NPV remain derived metrics. Defaults reproduce the
workbook math exactly.

### Matching the source workbook exactly (per-cell inputs)
The assumptions can be regenerated from the source Excel workbook
(`tools/generate_seed.py`). To reproduce the workbook's per-state Aggregate Model
exactly, three inputs override the factor approximations when present: **per-cell
premiums** (used verbatim, no premium pull-forward — the entered premium is already
the pricing rate), **raw preferred/HHD claim factors** (the workbook's AT/AU columns;
preferred applies for the UW class only), and the **morbidity state factor** (a
per-run scalar). Claims antiselection is `P = (1+aging)·P + 0.5·(rerate − trend)`;
the lapse has no antiselective load. The **claims base cost is indexed by issue age**
(constant across duration), matching the workbook Output/Aggregate; mortality and
aging-rerate use attained age. **GI commission** is paid in year 1 only, and
**year-1 NII** uses the current IBNR (no prior to average). The distribution is a
joint plan × issue-age × UW grid. Run with **solving off** to match the workbook (it
uses its specified rerate schedule); other states keep solving on by default. With
these, the engine reproduces the workbook's per-state Aggregate Model exactly on
every line (lives, premium, claims, commission, expenses, income, loss ratio).

### Full model export / import
The Configuration tab can download and upload a single JSON capturing the **entire
model** — assumptions, sensitivities, state scope, solve toggle and formulas. Pricing
cells are derived from the distribution, so they need not be stored. Importing a model
and re-running reproduces the original results exactly.

### Notes / deliberate choices
- Every input is an assumption — premium factors, distribution weight factors, the
  two antiselection λ (claims & lapse), the pull-forward (claims/premium trend &
  duration), and the projection trend are all editable; even the **formulas** are
  editable, and nothing pricing-relevant is hard-coded.
- Selection factors are carried forward past the source table's 5 durations.
- Acquisition costs are treated as one-time at issue; maintenance recurs.
- The in-year LR floor is a **hard** rule (rerates scaled back to respect it);
  structurally sub-floor durations are exempt and reported.
"""


def render() -> None:
    st.header("Documentation")
    st.markdown(_DOC)
