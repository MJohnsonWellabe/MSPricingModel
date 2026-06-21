"""Safe evaluator + default formulas for the projection.

The per-duration line items are editable expressions (see ``models/formulas``).
They are evaluated over a *namespace* the engine resolves each duration. The same
expression strings evaluate on **scalars** (``project_cell``) and on **numpy
arrays** (``forward_solver``) because the helpers (``minimum``/``maximum``/
``clamp``/``where``) are numpy-backed and Python's operators dispatch to numpy.

Security: expressions are parsed with ``ast`` and only a small node whitelist is
allowed (arithmetic, comparisons, ``if``/``else``, and calls to the whitelisted
helpers). No attribute access, no subscripting, no imports, no builtins. This runs
client-side in the user's own browser (Pyodide) but the whitelist keeps an
imported model from doing anything but arithmetic.

Namespace contract (resolved by the engine each duration; see ``project.py``):
  scalars/flags: d, rate_d, trend_d, trend_step, dur_scale, acq_active,
                 first_year, aging_p, state_cc
  per-cell:      base_prem, base_cc, selection, lapse_base, mort_d, aging_h,
                 comm_rate, is_gi, comm_age_mult, planf_offset_d, yr1_prem
  carry:         lives_prev, G_prev, H_prev, O_prev, P_prev, ibnr_prev, rbc_prev
  sensitivities: morbidity_scale, termination_scale, antiselective_lapse,
                 antiselective_claims
  scalars (asm): lam_lapse, lam_claims, ibnr_pct, nier, premium_tax_rate,
                 tax_rate, oper_acq_amt, marketing_amt, maintenance_amt,
                 inflation, rbc_pct, rbc_factor, covariance, gi_flat
"""
from __future__ import annotations

import ast
from functools import lru_cache

import numpy as np

from ..models.formulas import CORE_CATEGORIES, FormulaSet, FormulaStep


class FormulaError(ValueError):
    """Raised when a formula fails validation."""


# --- helpers exposed to formulas (work on scalars and numpy arrays) ----------
def _minimum(a, b):
    return np.minimum(a, b)


def _maximum(a, b):
    return np.maximum(a, b)


def _clamp(x, lo, hi):
    return np.minimum(np.maximum(x, lo), hi)


def _where(cond, a, b):
    if isinstance(cond, np.ndarray):
        return np.where(cond, a, b)
    return a if cond else b


_HELPERS = {
    "minimum": _minimum, "maximum": _maximum, "clamp": _clamp,
    "where": _where, "abs": abs,
}
_EVAL_GLOBALS = {"__builtins__": {}, **_HELPERS}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


def validate_formula(expr: str) -> str | None:
    """Return an error message if ``expr`` is not a safe arithmetic expression,
    else ``None``."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:  # noqa: BLE001
        return f"syntax error: {exc.msg}"
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return f"disallowed expression element: {type(node).__name__}"
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _HELPERS:
                fn = getattr(node.func, "id", type(node.func).__name__)
                return f"only {', '.join(sorted(_HELPERS))} may be called (got {fn})"
    return None


@lru_cache(maxsize=1024)
def _compile(expr: str):
    err = validate_formula(expr)
    if err:
        raise FormulaError(err)
    return compile(expr, "<formula>", "eval")


def compile_steps(fset: FormulaSet) -> tuple[list, list]:
    """Return (core_compiled, full_compiled) — each a list of (name, code)."""
    full = [(s.name, _compile(s.expr)) for s in fset.steps]
    core = [(s.name, _compile(s.expr)) for s in fset.steps if s.category in CORE_CATEGORIES]
    return core, full


def eval_steps(compiled: list, ns: dict) -> dict:
    """Evaluate compiled (name, code) steps in order, writing results into ``ns``."""
    for name, code in compiled:
        ns[name] = eval(code, _EVAL_GLOBALS, ns)  # noqa: S307 - whitelisted AST
    return ns


# --- default formula set (mirrors project.py exactly) ------------------------
_DEFAULT_STEPS = [
    # Inforce ----------------------------------------------------------------
    ("lapse_antisel", "Inforce",
     "1 + lam_lapse * (rate_d - trend_d) * antiselective_lapse",
     "Rerate-driven antiselective lapse load."),
    ("lapse_d", "Inforce",
     "clamp(lapse_base * termination_scale * lapse_antisel, 0.0, 1.0)",
     "Lapse rate after scale and antiselection, clamped to [0,1]."),
    ("term_raw", "Inforce",
     "1 - (1 - lapse_d) * (1 - mort_d)",
     "Combined lapse-or-mortality termination before duration scaling."),
    ("term_d", "Inforce",
     "minimum(term_raw * dur_scale, 1.0)",
     "Total termination after the duration-2 / 3+ scaling."),
    ("lives_d", "Inforce",
     "lives_prev * (1 - term_d)",
     "Inforce lives at end of the duration."),
    ("avg_lives", "Inforce",
     "(lives_prev + lives_d) / 2",
     "Average lives exposed during the duration."),
    # Premium ----------------------------------------------------------------
    ("G_d", "Premium",
     "G_prev * (1 + rate_d)",
     "Cumulative rerate factor."),
    ("H_d", "Premium",
     "H_prev * (1 + aging_h)",
     "Cumulative aging-rerate factor (aging_h is 0 in year 1)."),
    ("total_rerate", "Premium",
     "G_d * H_d",
     "Combined rerate factor applied to base premium."),
    ("earned_prem", "Premium",
     "base_prem * total_rerate * avg_lives",
     "Earned premium."),
    # Claims -----------------------------------------------------------------
    ("O_d", "Claims",
     "O_prev * (1 + trend_step)",
     "Cumulative projection-trend factor (trend_step is 0 in year 1; base is "
     "already pulled forward to the year-1 level)."),
    ("P_d", "Claims",
     "where(first_year, 1.0, (1 + aging_p) * P_prev "
     "+ lam_claims * (rate_d - trend_d) * antiselective_claims)",
     "Antiselection (column P): 1 in year 1, then the aging + rerate-vs-trend "
     "recurrence."),
    ("base_cc_eff", "Claims",
     "base_cc * morbidity_scale",
     "Base claim cost (incl. class factors and pull-forward) times the "
     "morbidity sensitivity."),
    ("claims", "Claims",
     "base_cc_eff * selection * O_d * P_d * state_cc * avg_lives",
     "Incurred claims."),
    # Expenses ---------------------------------------------------------------
    ("ibnr", "Expenses",
     "ibnr_pct * claims",
     "Incurred-but-not-reported reserve."),
    ("nii", "Expenses",
     "(ibnr_prev + ibnr) / 2 * nier",
     "Net investment income on average IBNR."),
    ("comm_base", "Expenses",
     "yr1_prem - planf_offset_d",
     "Commission base premium (year-1 premium less the plan-F offset)."),
    ("commission", "Expenses",
     "where(is_gi, gi_flat * avg_lives, "
     "comm_age_mult * comm_rate * comm_base * avg_lives)",
     "Commission: flat for GI, else rate x base x lives (halved for age >= 80)."),
    ("premium_tax", "Expenses",
     "premium_tax_rate * earned_prem",
     "Premium tax."),
    ("oper_acq", "Expenses",
     "oper_acq_amt * acq_active",
     "Operating acquisition cost (year 1 only)."),
    ("marketing", "Expenses",
     "marketing_amt * acq_active",
     "Marketing acquisition cost (year 1 only)."),
    ("maintenance", "Expenses",
     "maintenance_amt * avg_lives * (1 + inflation) ** d",
     "Maintenance expense, inflating each year."),
    # Income -----------------------------------------------------------------
    ("pretax", "Income",
     "earned_prem + nii - claims - commission - premium_tax "
     "- oper_acq - marketing - maintenance",
     "Pre-tax income."),
    ("tax", "Income",
     "-tax_rate * pretax",
     "Income tax (negative = cost)."),
    ("at_income", "Income",
     "pretax + tax",
     "After-tax income."),
    # Capital ----------------------------------------------------------------
    ("rbc", "Capital",
     "rbc_pct * earned_prem * rbc_factor * covariance",
     "Required risk-based capital."),
    ("int_on_rbc", "Capital",
     "rbc * nier",
     "Investment income on held capital."),
    ("tax_on_int", "Capital",
     "-tax_rate * int_on_rbc",
     "Tax on the capital investment income."),
    ("ah", "Capital",
     "rbc_prev - rbc + int_on_rbc + tax_on_int + at_income",
     "Distributable cashflow (the IRR is computed on this stream)."),
]


def default_formula_steps() -> list[FormulaStep]:
    return [FormulaStep(name=n, category=c, expr=e, doc=d) for (n, c, e, d) in _DEFAULT_STEPS]


def default_formula_set() -> FormulaSet:
    return FormulaSet(steps=default_formula_steps())


def sample_namespace() -> dict:
    """A representative namespace for validating a formula set without a full run."""
    return {
        "d": 3, "rate_d": 0.05, "trend_d": 0.07, "trend_step": 0.07,
        "dur_scale": 1.10, "acq_active": 0.0, "first_year": 0.0,
        "aging_p": 0.01, "state_cc": 1.0,
        "base_prem": 2000.0, "base_cc": 1500.0, "selection": 1.0,
        "lapse_base": 0.08, "mort_d": 0.02, "aging_h": 0.01,
        "comm_rate": 0.05, "is_gi": False, "comm_age_mult": 1.0,
        "planf_offset_d": 0.0, "yr1_prem": 2000.0,
        "lives_prev": 0.8, "G_prev": 1.1, "H_prev": 1.05, "O_prev": 1.07,
        "P_prev": 1.0, "ibnr_prev": 10.0, "rbc_prev": 50.0,
        "morbidity_scale": 1.0, "termination_scale": 1.0,
        "antiselective_lapse": 1.0, "antiselective_claims": 1.0,
        "lam_lapse": 0.5, "lam_claims": 0.5, "ibnr_pct": 0.1, "nier": 0.04,
        "premium_tax_rate": 0.02, "tax_rate": 0.21, "oper_acq_amt": 100.0,
        "marketing_amt": 50.0, "maintenance_amt": 40.0, "inflation": 0.03,
        "rbc_pct": 0.4, "rbc_factor": 1.0, "covariance": 0.8, "gi_flat": 25.0,
    }


def validate_formula_set(fset: FormulaSet, ns: dict | None = None) -> list[tuple[str, str]]:
    """Validate every step (parse + test-evaluate in order on a sample namespace).
    Returns a list of (formula_name, error) — empty when all formulas are valid."""
    errors: list[tuple[str, str]] = []
    ns = dict(ns or sample_namespace())
    for step in fset.steps:
        err = validate_formula(step.expr)
        if err:
            errors.append((step.name, err))
            continue
        try:
            ns[step.name] = eval(_compile(step.expr), _EVAL_GLOBALS, ns)  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            errors.append((step.name, f"evaluation error: {exc}"))
    return errors
