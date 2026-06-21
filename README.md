# Medicare Supplement Pricing Model

A from-scratch rebuild of the MS pricing workbook as a **pure-Python actuarial
engine** with a **Streamlit** front-end that runs entirely in the browser via
[stlite](https://github.com/whitphx/stlite) (WebAssembly / Pyodide) and deploys
as static files to **GitHub Pages**.

The engine reproduces the workbook's `Model`/`Aggregate Model` logic but is not a
literal copy — assumptions are re-derivable and the model projects a full 30
years.

## Layout

```
src/medigap_engine/      Pure-Python engine (no Streamlit / IO deps) — unit tested
  models/                Typed assumption & result dataclasses
  engine/                project_cell, aggregate, solver, metrics, lookups
  io/                    JSON (de)serialisation, bundled-default loaders, paste helpers
  data/                  Seed assumptions + cell universe (JSON)
  experience/            Experience-study derivation (Phase 2)
app/                     Streamlit UI (Configuration, Experience Study, Assumptions,
                         Calculation, Output, Documentation)
web/index.html           stlite bootstrap (static, GitHub Pages)
tests/                   pytest suite (engine only, headless)
tools/generate_seed.py   Regenerate seed data from the source workbook
.github/workflows/       CI: test -> build -> deploy to Pages
```

## Develop

```bash
pip install -e ".[dev]"
pytest                                  # run the engine test suite
streamlit run app/streamlit_app.py      # local UI (server-side, full speed)
```

## Deploy (GitHub Pages)

Push to `main`. CI runs the tests, bundles `app/` + `medigap_engine/` into
`app.tar.gz`, and publishes `web/index.html` + the bundle to Pages. Enable Pages
with the **GitHub Actions** source. The published site runs the whole model in
the visitor's browser — no server.

> The stlite version is pinned in `web/index.html`; bump it there if the CDN
> asset paths change.

## Model overview

Each pricing **cell** = (issue age, gender, plan F/G/N, UW class UW/OE/GI,
preferred Y/N, household discount Y/N) is projected over 30 durations:
inforce roll-forward (lapse + mortality with antiselective lapse), premium with
compounding rerates and aging-rerates, claims (base cost × selection × trend ×
antiselection × state factor), expenses, capital/RBC, income, and an IRR on the
distributable cashflow. When solving, rerates are taken until the projected
lifetime loss ratio hits the target (subject to rules), then trend-only. See the
in-app **Documentation** tab for the full formula reference.

## Phases

1. **Engine + assumptions + output** (this release): engine, solver, six
   assumption tabs, multi-state output with per-state income statements.
2. **Experience study + AE analysis**: derive assumptions from pre-aggregated
   claims uploads; actual-to-expected analysis.
3. **Polish**: charts, richer sensitivities, full documentation, performance.

## Regenerating seed data

```bash
python tools/generate_seed.py path/to/MS_Pricing_By_State_2026AEP_v5.xlsm.xlsx
```
