"""Editable formula model.

The per-duration arithmetic of the projection is expressed as an ordered list of
named expressions (``FormulaStep``). The engine resolves a namespace of lookup
values + prior-duration carry + assumption scalars, then evaluates each step in
order. Defaults reproduce the hard-coded projection exactly; users can edit the
expressions on the Formulas tab.

This module is pure data (no Streamlit / numpy); the evaluator lives in
``engine/formulas.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Categories needed to produce earned premium and claims (and therefore the loss
# ratio the rerate solver targets). The solver only evaluates these for speed.
CORE_CATEGORIES = ("Inforce", "Premium", "Claims")
DOWNSTREAM_CATEGORIES = ("Expenses", "Income", "Capital")
CATEGORIES = CORE_CATEGORIES + DOWNSTREAM_CATEGORIES


@dataclass
class FormulaStep:
    name: str          # variable assigned (also the stored series name)
    category: str      # one of CATEGORIES
    expr: str          # Python expression over the resolved namespace
    doc: str = ""      # human-readable description


@dataclass
class FormulaSet:
    steps: list[FormulaStep] = field(default_factory=list)

    def names(self) -> list[str]:
        return [s.name for s in self.steps]

    def by_category(self) -> dict[str, list[FormulaStep]]:
        out: dict[str, list[FormulaStep]] = {}
        for s in self.steps:
            out.setdefault(s.category, []).append(s)
        return out
