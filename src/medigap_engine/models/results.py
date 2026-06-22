"""Result containers. Every projected line item is retained so the engine's
inner workings stay inspectable (a locked requirement)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .cell import CellKey

# Line items kept on every projection (each is a length-30 list, duration 1..30).
LINE_ITEMS = (
    "lives",
    "lapse",
    "mortality",
    "total_term",
    "rerate_used",        # the rerate % actually applied each duration
    "total_rerate",       # cumulative rerate factor (incl. aging)
    "earned_prem",
    "ibnr",
    "nii",
    "base_cc",
    "selection",
    "trend",
    "antiselection",      # column P
    "claims",
    "commission",
    "premium_tax",
    "oper_acq",
    "marketing",
    "maintenance",
    "pretax_income",
    "tax",
    "at_income",
    "rbc",
    "int_on_rbc",
    "tax_on_int",
    "ah_cashflow",        # distributable cashflow used for IRR
    "in_year_lr",
    "lifetime_lr",
)


@dataclass
class CellProjection:
    """All length-30 arrays keyed by line-item name."""
    series: dict[str, list[float]] = field(default_factory=dict)

    def __getattr__(self, name):
        # convenience attribute access: projection.claims -> projection.series["claims"]
        series = self.__dict__.get("series", {})
        if name in series:
            return series[name]
        raise AttributeError(name)


@dataclass
class CellResult:
    key: CellKey
    weight: float
    projection: CellProjection
    irr: float
    lifetime_lr: float
    npv_pretax: float


@dataclass
class StateResult:
    state: str
    # aggregated (distribution-weighted) dollar series across all cells in the state
    series: dict[str, list[float]]
    irr: float
    lifetime_lr: float
    npv_pretax: float
    npv_premium: float
    rerates: list[float] = field(default_factory=list)   # rerate % used by duration
    cells: list[CellResult] = field(default_factory=list)
    npv_by_line: dict = field(default_factory=dict)       # income-statement line -> NPV

    @property
    def pretax_margin(self) -> float:
        return self.npv_pretax / self.npv_premium if self.npv_premium else 0.0


@dataclass
class RunResult:
    by_state: dict[str, StateResult] = field(default_factory=dict)
    all_states: StateResult | None = None    # combined across every requested state
