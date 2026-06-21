# Project Handoff — Medicare Supplement (Medigap) Pricing Model

_Last updated: 2026-06-21 · branch `claude/word-document-prompt-plan-5o6lus` (also on `main`) ·
HEAD `e2f50b2` · 68 tests passing · CI run #12 green · live at
https://mjohnsonwellabe.github.io/MSPricingModel/_

## 1. What this is
A from-scratch rebuild of an Excel Medigap pricing workbook
(`MS_Pricing_By_State_2026AEP_v5.xlsm`) as a **pure-Python actuarial engine** plus a **Streamlit
UI** that runs **entirely in the browser** via **stlite** (Pyodide/WebAssembly) and deploys as
**static files to GitHub Pages**. It is a maintainable reimplementation that *uses the workbook
formulas as reference* — not a literal cell-for-cell copy. The engine projects each pricing cell
30 years and keeps every line item inspectable.

Repo: `MJohnsonWellabe/MSPricingModel` (public). Owner email: mattjohnson912@gmail.com.

## 2. Current status
- All 8 build iterations are shipped, tested, and deployed. Working tree clean.
- `python -m pytest -q` → **68 passed**.
- GitHub Actions `test-and-deploy` is green; the site runs the whole model client-side.
- Each iteration was pushed to the feature branch **and** `main` (push-to-main was explicitly
  authorised for this engagement; confirm before assuming it continues).

## 3. Architecture & principles
- **Engine is pure Python** (`src/medigap_engine/`), zero Streamlit/IO deps, fully unit-tested
  headlessly, small under Pyodide. **numpy is the only runtime dependency.**
- **UI is a thin Streamlit layer** (`app/`) that may import the engine. UI uses pandas + altair
  for display only (both ship with Streamlit; the engine never imports them in its hot path).
- **Deterministic**: results depend only on assumptions + sensitivities + run config + formulas.
  Pricing cells are *derived* from the distribution assumptions, so they need not be stored.
- **Pyodide constraints**: no scipy / numpy_financial (IRR/NPV are hand-rolled in
  `engine/metrics.py`); single-threaded, so long loops are **rerun-chunked** (one state per
  `st.rerun()`) to keep the progress bar repainting.

## 4. Repository layout
```
src/medigap_engine/        Pure-Python engine (unit tested)
  models/                  Typed dataclasses:
    assumptions.py           AssumptionSet + 8 sub-objects incl. PullForwardAssumptions
    cell.py                  CellKey, PricingCell (key + weight)
    config.py                RunConfig (states, solve_rerates, sensitivities, use_experience_study)
    sensitivities.py         SensitivitySet (5 stress multipliers)
    formulas.py              FormulaStep, FormulaSet, category constants
    results.py               CellProjection/CellResult/StateResult/RunResult
  engine/
    lookups.py               INDEX/MATCH/SUMIFS-style lookups (premium_for_cell, base_claim_cost,…)
    formulas.py              Safe AST evaluator + default_formula_steps() (the editable engine)
    project.py               project_cell — per-cell 30-yr projection (formula-driven, scalars)
    forward_solver.py        precompute + front-load rerate solver + project_aggregate (numpy arrays)
    sensitivity.py           run_stochastic / simulate_state (Monte-Carlo IRR)
    aggregate.py             aggregate_cells / aggregate_states (sum dollars, re-derive ratios)
    metrics.py               hand-rolled irr() (bisection) + npv()
    run.py                   run / run_state orchestration; normalize_weights
  io/
    serialize.py             assumptions (de)serialise + legacy migration + formula (de)serialise
    model_io.py              FULL model export/import (assumptions+sens+config+formulas)
    defaults.py              bundled-seed loaders, build_cells(asm), available_states()
    tables.py                Excel-paste TSV<->array helpers
  data/
    default_assumptions.json seed AssumptionSet (app runs out of the box)
    default_cells.json       ONLY an input to tools/generate_seed.py (not loaded at runtime)
    templates/*.csv          sales/claims templates + browser-friendly samples
  experience/                raw data -> assumptions: schema, sales, claims, ae, port
app/
  streamlit_app.py           entrypoint; 8-tab router
  state.py                   session_state helpers (assumptions, formulas, run_config; JSON I/O)
  tabs/                      configuration, experience_study, assumptions, formulas, calculation,
                             output, sensitivity, documentation
web/index.html               stlite bootstrap (pinned @stlite/browser 0.76.0)
tests/                       pytest (engine only, headless) — 68 tests
tools/generate_seed.py       regenerate data/*.json from the source workbook (workbook NOT in repo)
tools/extract_samples.py     regenerate template/sample CSVs from the workbook
.github/workflows/deploy.yml CI: test -> build app.tar.gz -> deploy to Pages
```

## 5. Develop / run / test / deploy
```bash
pip install -e ".[dev]"                 # numpy + pytest + ruff
python -m pytest -q                     # engine test suite (headless)
streamlit run app/streamlit_app.py      # local UI (server-side, full speed) — needs streamlit
```
**Deploy:** push to `main`. CI runs pytest, bundles `app/` + `src/medigap_engine` into
`site/app.tar.gz` (engine + UI + seed data at the archive root), and publishes `web/index.html` +
the bundle to Pages. **GitHub Pages source must be "GitHub Actions"**, and the deploy job declares
`environment: github-pages` (deploy-pages@v4 fails without it). stlite version is pinned in
`web/index.html`; `requirements` there are `["numpy","pandas"]` (Streamlit pulls in altair).

## 6. The model (what the engine computes)
Pricing **cell** = (issue_age ∈ {65,68,73,77,83,85}, gender M/F, plan F/G/N, UW class UW/OE/GI,
preferred Y/N, household-discount Y/N) = **432 cells**, each projected over **30 durations**.
Per duration (see the in-app **Documentation** tab or `engine/formulas.py::_DEFAULT_STEPS` for the
exact formulas):
- **Inforce**: `lives_d = lives_{d-1}(1-term_d)`, `term_d = 1-(1-lapse)(1-mort)` with duration
  scaling (×dur2 in yr2, ×dur3+ in yr3+); antiselective lapse `1+λ_lapse(rerate-trend)`.
- **Premium**: cumulative rerate `G`, aging-rerate `H`, `earned = base_prem·G·H·avg_lives`.
- **Claims**: `base_cc·selection·O·P·state_factor·avg_lives`; `O` = cumulative projection trend
  (1.0 in yr1 — see pull-forward); `P` = antiselection column (`P_1=1`, then
  `(1+aging)P_{d-1}+λ_claims(rerate-trend)`).
- **Expenses/income/capital**: IBNR, NII, commission (GI flat; else rate×base×lives, halved ≥80),
  premium tax, one-time acq, inflating maintenance, pre/after-tax income, RBC, and the
  distributable cashflow `AH` the IRR runs on.
- **Aggregation**: sum dollar line items weighted by cell weight; **re-derive** ratios (LR/IRR/NPV)
  from aggregated cashflows (never average ratios).

**Factor models** (so inputs are minimal and meaningful):
- Premium = `base_by_issue_age (blend at plan G) × plan_rel (G=1.0) × mix-normalised
  gender/preferred/hhd differentials × uw_rel × raw state_factor`.
- Morbidity base_cc is the gender blend; gender/preferred/hhd are single differentials normalised
  by the business mix (`normalized_factors`, `derive_two_level` in `models/assumptions.py`).
- Distribution = 6 independent per-dimension weight factors (each sums to 1); a cell weight is
  their product, re-normalised at run time (`build_cells` in `io/defaults.py`).

**Pull-forward** (`PullForwardAssumptions`: duration, claims_trend, premium_trend): current
experience-period base claims and premium are brought forward once by `(1+trend)^duration`. The
pulled level **is** the year-1 level; the projection trend (`morbidity.trend_by_year`) compounds
from year 1→2 onward. Defaults (`claims_trend=trend_by_year[0]`, `duration=1.75`) reproduce the
old `(1+trend)^1.75` year-1 behaviour exactly. Lives in `lookups.base_claim_cost` /
`premium_for_cell`; engine year-1 `O=1.0`.

**Rerate solver** (`forward_solver.solve_with_precompute`): front-loads the largest rerate each
year that keeps the in-year LR ≥ floor (capped by max_rerate and the consecutive-rerate rule),
then rides at trend; bisects the number of front-loaded years (continuous K) to hit the lifetime-LR
target. Best-effort with a status if unreachable. Each state solves independently.

**Stochastic sensitivity** (`engine/sensitivity.py`): draws the 5 sensitivity factors ~Normal,
re-solves rerates per draw, projects IRR via the numpy `project_aggregate`; returns per-state IRR
mean/median/CI + % target met.

## 7. The editable Formula Engine (the most novel piece — read before changing the engine)
Every per-duration line item is an **editable expression** (`models/formulas.py::FormulaStep`).
`engine/formulas.py` resolves a per-duration **namespace** (lookups + prior-duration carry +
assumption scalars + sensitivities) and evaluates the steps **in order**. The same expression
strings evaluate on **scalars** (`project_cell`) and on **numpy arrays** (`forward_solver`) because
the helpers (`minimum/maximum/clamp/where/abs`) are numpy-backed and Python operators dispatch to
numpy. So the projection, the solver, and the stochastic engine all honour edited formulas and stay
consistent.
- **Safety**: expressions are parsed with `ast` against a strict node whitelist (arithmetic,
  comparisons, `if/else`, calls to the helpers only). No attribute access / subscripts / imports /
  other calls. `validate_formula` / `validate_formula_set` power the Formulas tab "Validate" button.
- **Performance**: steps are split into `CORE_CATEGORIES` (Inforce/Premium/Claims — all the solver
  needs) vs downstream (Expenses/Income/Capital). The solver evaluates only core; `project_cell`
  and `project_aggregate` evaluate the full set. Custom formulas are heavier than the old pure-numpy
  path but compile once.
- **Threading**: `formulas: FormulaSet|None=None` (default = built-in set) is passed through
  `project_cell`, `run_state`/`run`, `solve_rerates`/`solve_with_precompute`, `project_aggregate`,
  `run_stochastic`/`simulate_state`. The app passes the session FormulaSet from `state.get_formulas()`.
- **To add/change engine math**: edit `_DEFAULT_STEPS` (and the resolver in `project.py` /
  `forward_solver._make_ns` if a new input variable is needed). The golden + equivalence tests are
  the regression guard — keep them passing.

## 8. Full model export / import (`io/model_io.py`)
`model_to_dict` / `model_from_dict` capture assumptions + sensitivities + run config + formulas in
one JSON (schema-versioned). Download/Upload buttons live on the **Configuration** tab; importing a
model and re-running reproduces results exactly (covered by `tests/test_model_io.py`). There is also
an assumptions-only JSON on the Assumptions tab.

## 9. UI tabs
Configuration (scope, sensitivities, solve toggle, **full model export/import**, Run) ·
Experience Study (sales→distribution/premium, claims→morbidity, **editable suggested differentials**,
Adopt, A/E) · Assumptions (sub-tabs: **Pull forward**, Distribution, Premium, Rerates, Termination,
Morbidity, Commission, Economic) · **Formulas** (grouped editable expressions + Validate + Reset) ·
Calculation (rerun-chunked run + raw projection inspector) · Output (summary, income statement,
trend & rerates) · Sensitivity (stochastic IRR table + altair histogram) · Documentation.
**Every interactive widget has an explicit `key=`** — Streamlit renders all tabs each run, so
duplicate auto-IDs raise `StreamlitDuplicateElementId`; keep new widgets keyed.

## 10. Conventions & constraints (carry these forward)
- Develop on `claude/word-document-prompt-plan-5o6lus`; create it if missing. Pushing to `main` was
  explicitly authorised this engagement — re-confirm before relying on it.
- End commit messages with the harness-provided `Co-Authored-By:` and `Claude-Session:` footers.
- Do **not** put any model identifier in commits/PRs/code/artifacts.
- Do **not** open PRs unless explicitly asked.
- GitHub access is via the **GitHub MCP tools** only (`mcp__github__*`); the `gh` CLI is not
  available. Session repo scope is `MJohnsonWellabe/MSPricingModel`.
- Workflow each change: edit → `pytest -q` green → verify the stlite bundle imports from an archive
  root (copy `app/` + `src/medigap_engine` to a tmp dir, import) → commit → push → confirm the Pages
  deploy goes green via the Actions MCP tools.

## 11. Testing
68 tests in `tests/`. Regression guards to keep green when touching the engine:
- `test_project_cell.py` — golden structure of a 30-yr cell projection.
- `test_sensitivity.py` — **engine equivalence**: `project_aggregate == project_cell` and
  `solve_with_precompute == solve_rerates` at base sensitivities (this is what proves the
  formula-driven refactor reproduces results exactly).
- `test_pull_forward.py`, `test_formulas.py`, `test_model_io.py`, `test_serialize.py` (incl. legacy
  migration), `test_lookups.py`, `test_premium_distribution.py`, `test_antiselection.py`,
  `test_solver.py`, `test_aggregate.py`, `test_metrics.py`, `test_experience_*`.

## 12. Known watch-outs / tech debt
- `app/tabs/sensitivity.py` imports `altair`, which is **not** listed in `web/index.html`
  requirements — it works because Streamlit bundles altair. If a future stlite/Streamlit drops it,
  add `"altair"` to the requirements list.
- `io/defaults.default_assumptions()` is `lru_cache`d — deep-copy before mutating (tests do via the
  `asm` fixture; `state.init_state` deep-copies for the session).
- Regenerating seed data (`tools/generate_seed.py`, `tools/extract_samples.py`) requires the source
  `.xlsm`, which is **not** in the repo. Keep `data/default_assumptions.json` and the seed tools in
  sync if you change assumption shapes.
- `data/default_cells.json` is only a derivation input for the seed tool; it is not loaded at runtime.
- stlite caches the app bundle in the browser; after a deploy, a hard refresh (Ctrl/Cmd-Shift-R) may
  be needed to see changes.
- `README.md` predates the Formulas/Sensitivity tabs and the formula engine — the in-app
  **Documentation** tab and this file are the current sources of truth.
- Custom formulas slow the solver/stochastic loop vs the original pure-numpy path (expected).

## 13. Iteration history (what each delivered)
1. Engine + assumptions + Output + stlite deploy (Phase 1).
2. Assumption fixes (two λ, targets, hard LR floor, trend exponent) + experience study (Phase 2).
3. Factor-based premium & distribution; progress bar; trend/rerates on Output.
4. Bug fixes (sample load, rerate table) + base/factor refinements; margin column.
5. Unified relativity→normalized factors; **front-load rerate solver**; AE matplotlib fix.
6. Single-differential factors; fuller experience study; **stochastic sensitivity**.
7. Sales load suggests factors; grouped Economic tab; ordered histogram; **premium trend**.
8. **Editable Formula Database**; **Pull-forward** refactor + tab reorder; **full model
   export/import**; editable experience-study differentials. (+ follow-ups: keyed all widgets to
   fix `StreamlitDuplicateElementId`.)

## 14. Deeper context
- In-app **Documentation** tab — full methodology/formula reference.
- The build/plan file used across iterations (outside the repo) captures the rationale for each
  decision; this `HANDOFF.md` is the self-contained summary.
