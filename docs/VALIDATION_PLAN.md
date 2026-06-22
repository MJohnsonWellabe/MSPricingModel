# Multi-State Validation Plan

**Audience:** a team member finishing this build.
**Goal:** (A) produce an assumptions file that maps cleanly into our Excel pricing
workbook, then (B) validate the Python engine against the workbook **for every
state**, the way TX is already validated exactly.

Read this top-to-bottom once before starting. Everything here has been done for **TX**
already — your job is to generalize it to the rest of the states and lock it in with
tests.

---

## 0. Background you need first

- The Python engine (`medigap_engine`) reproduces the Excel workbook
  `*_MS_Pricing_By_State_*.xlsm`. For **TX** it matches the workbook's **Aggregate
  Model** sheet *exactly* on every line (lives, premium, NII, claims, commission,
  premium tax, expenses, pre/after-tax income, interest on capital, distributable
  income, loss ratio).
- The bundled assumptions in `src/medigap_engine/data/default_assumptions.json` are
  **regenerated from the workbook** by `tools/generate_seed.py`.
- The line-by-line comparison harness is `tools/compare_tx.py`; the regression guard
  is `tests/test_tx_validation.py`.
- Read `HANDOFF.md` **§8b** ("Distribution joint grid, exact per-cell inputs & TX
  calibration"), the `README.md` "Regenerating seed data" section, and the in-app
  **Documentation** tab. They are the source of truth for the model.

### Setup
```bash
pip install -e ".[dev]"
pytest -q                      # 80+ tests should pass, incl. test_tx_validation.py
streamlit run app/streamlit_app.py   # optional: the UI
```
Put the source workbook somewhere local (it is **not** committed). The harness
defaults to `/tmp/tx_model.xlsx`; pass your own path as the first argument.

### The exact-match facts (the "gotchas" that took the longest to find)
Keep these in mind — a new state will only match if the engine still honors them:
1. **Claims base cost is indexed by *issue* age** (constant across duration), not
   attained age. (`engine/project.py`, `engine/forward_solver.py` pass
   `key.issue_age` to `base_claim_cost`; mortality & aging-rerate stay attained-age.)
2. **GI commission is paid in year 1 only** (flat `gi_flat`, no lives factor); 0 after.
3. **Year-1 NII** uses the current IBNR (the workbook's `AVERAGE` skips the blank
   prior cell — no halving in year 1).
4. **Per-cell premiums** from the Input sheet are used verbatim (no premium
   pull-forward — the Input premium is already the pricing rate).
5. **Morbidity state factor = `Input!Z1`** — a *per-run scalar* that changes with the
   workbook's active state. This is the main per-state blocker (see Part B).
6. **Raw preferred/HHD claim factors** (workbook `Assumptions!AT`/`AU`), not
   mix-normalized.
7. **Distribution** is a true joint `plan × issue-age × UW` weight grid.
8. **Validate with solving OFF** — the workbook uses its *specified* rerate schedule
   (`Assumptions!` column F), not the engine's solver. In the app, the
   Configuration / Assumptions "Solve rerates" toggle must be **off**; in code set
   `asm.rerates.solve = False` and `RunConfig(solve_rerates=False)`.

---

## Part A — Build the assumptions file that maps into Excel

**Outcome:** a clean `assumptions.xlsx` the team can open beside the workbook and
diff block-by-block.

1. Regenerate the seed from the workbook:
   ```bash
   python tools/generate_seed.py /path/to/workbook.xlsx
   ```
   This overwrites `src/medigap_engine/data/default_assumptions.json` and
   `default_cells.json`. Review the diff.
2. Export the assumptions workbook — either click **Download Excel** on the app's
   **Assumptions** tab, or:
   ```python
   from medigap_engine.io.defaults import default_assumptions
   from medigap_engine.io.excel_export import assumptions_to_xlsx_bytes
   open("docs/tx_assumptions.xlsx", "wb").write(
       assumptions_to_xlsx_bytes(default_assumptions()))
   ```
   You get one sheet per category (Pull forward, Morbidity, Premium, Rerates,
   Distribution, Termination, Commission, Economic) plus a **Derived factors** sheet
   showing the engine's mix-normalized factors. Map each sheet back to the workbook's
   `Assumptions`/`Input` tabs.
3. **Know the round-trip gaps.** The `.xlsx` export/import
   (`io/excel_export.py` ↔ `io/excel_import.py`) does **not** carry:
   - `cell_premiums` (exact per-cell premiums by state) — these live in the workbook
     **Input** sheet (columns in `STATE_COLS`, `tools/generate_seed.py`);
   - raw `preferred_factors`/`hhd_factors` — these live in workbook
     `Assumptions!AT4:AU5`.
   Document where each of those comes from so a reviewer mapping the file into Excel
   knows the factor model on the Premium sheet is only the *fallback*; the real
   premiums are per-cell on the Input sheet. (These two blocks **do** round-trip in
   the JSON export, just not the Excel one.)

**Deliverable:** committed `docs/tx_assumptions.xlsx` (already present) plus a short
note in this folder mapping each export sheet → workbook location.

---

## Part B — Validate every state

The workbook is a **single combined file**: per-state premium columns live on the
Input sheet, per-state commission on the Assumptions sheet, but only **one active
state** at a time drives `Input!Z1` (the morbidity factor) and the **Aggregate Model**
recalculation.

### B1. For each state, capture three things from the workbook
Set the workbook's **state selector** to the target state, let Excel fully recalc,
then record:
1. **Aggregate Model targets** — the per-duration vectors for every line (these are
   your truth; durations 1–30, columns F onward). Note the sheet stores present
   values in column C; compare per-duration values, not column C.
2. **`Input!Z1`** — the morbidity state factor for that state.
3. **Specified rerate schedule** (`Assumptions!` column F) — check whether it changes
   with the state. If it does, capture it per state.

> First, find the state-selector cell. Open `Input!Z1` and trace its formula
> (`openpyxl` with `data_only=False`, or in Excel) back to the cell that picks the
> state — likely a dropdown near the top of `Input`. That cell is what you toggle.

### B2. Run the engine for that state and diff
Generalize the TX harness. Copy `tools/compare_tx.py` to a state-parameterized version
(or add a `--state`/`--z1` argument). The only per-state inputs it must inject are the
**morbidity state factor** (`asm.morbidity.state_factors[STATE] = Z1`) and, if it
varies, the specified rerate schedule. Then it should:
```python
asm.rerates.solve = False
run(build_cells(asm), asm, RunConfig(states=[STATE], solve_rerates=False))
```
and print the same per-line / per-duration percentage diff `compare_tx.py` prints.
Per-cell premiums for the state already come through automatically (they are stored in
`cell_premiums` keyed by state from `STATE_COLS`), as do per-state commission and the
premium state factor.

Sanity checks before diffing:
- `available_states()` (`io/defaults.py`) lists the state.
- `cell_premiums` has entries for the state, and `commission.by_state` has the state.

### B3. Acceptance criteria (match TX tolerances)
A state is "validated" when every Aggregate Model line is within tolerance at every
material duration:
- earned premium, claims, NII, loss ratio, income lines: **< 1.5e-3** relative;
- lives: **< 2.5e-3** (workbook exports lives at 3 decimals);
- ignore near-zero tails (durations where lives ≈ 0 make relative error explode on
  trivial dollars).

---

## Part C — Reconcile residuals (the debugging playbook)

If a line is off, localize it with the per-cell **Output** sheet (one row per cell;
30-duration blocks per variable — Lives @ col W, Premium @ BA, Claims @ CE,
Commission @ DI, …). For a handful of cells, compare the engine's per-cell projection
(`engine.project.project_cell`) to the Output row, then classify the diff:

- **Constant % across all durations** → a level input: base claim cost (issue-age
  table), preferred/HHD/UW class factor, morbidity state factor, or per-cell premium.
- **Grows/shrinks with duration** → a time-shaped factor: trend `O`, antiselection
  `P`, selection by duration, commission schedule, or the lives curve
  (lapse/mortality).
- **Identical pattern across UW/OE/GI for the same issue age** → it's age-driven
  (base cost), not underwriting-driven (selection).

This is exactly how TX was closed (issue-age base cost, GI commission, year-1 NII).
When you find the cause, fix the responsible assumption (via `generate_seed.py`) or
formula (`engine/formulas.py`), keeping both engine paths (`project.py` and
`forward_solver.py`) in step — `tests/test_forward_equivalence.py` guards that.

---

## Part D — Lock it in

1. **Per-state regression test.** Parametrize `tests/test_tx_validation.py` (or add a
   sibling) with hardcoded Aggregate Model target vectors per validated state and the
   state's `Z1`. Keep the same tolerances. This prevents future regressions.
2. **Keep it green.** `pytest -q` and `ruff check` must pass.
3. **Update docs** (standing rule): `HANDOFF.md` §8b (list validated states + any
   per-state quirks found) and the in-app Documentation tab.
4. **Commit** to the working branch (`claude/export-assumptions-excel-jwdyd3` or a new
   branch). Push to `main` only with explicit sign-off. Do **not** commit the
   workbook (it is proprietary / large).

---

## Per-state blockers checklist

| Item | Source | Status / action |
|---|---|---|
| Per-cell premiums | Input `STATE_COLS` columns | Auto-captured if the state's column exists — **verify** |
| Premium state factor | derived from per-cell premiums | Auto |
| Commission schedule | `Assumptions!BX:CY` (one column per state) | Auto if present — **verify** |
| **Morbidity state factor** | **`Input!Z1` (per active state)** | **Manual — capture per state via the selector** |
| Specified rerate schedule | `Assumptions!` col F | **Verify whether it varies by state**; capture if so |
| Termination lapse state factor | defaults to 1.0 | Confirm the workbook applies none per state |
| Aggregate Model targets | recalculated per active state | **Manual — capture per state** |

## Definition of done
Every state in `available_states()` has: captured workbook targets, a passing
parametrized validation test within tolerance, and any per-state quirks documented.
The team can regenerate the seed and reproduce every state's Aggregate Model from the
Python engine.
