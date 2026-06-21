"""Typed assumption model for the Medigap pricing engine.

This module is the single source of truth for all pricing assumptions. It has
zero Streamlit / IO dependencies so it can be unit-tested headlessly and stays
light inside Pyodide. Tables are held as plain Python lists/dicts (durations are
only 1..30, so vectorisation buys little and plain data serialises cleanly to
JSON).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PLANS = ("F", "G", "N")
UW_CLASSES = ("UW", "OE", "GI")
PROJECTION_YEARS = 30


@dataclass
class MorbidityAssumptions:
    ages: list[int]                          # attained-age axis for base claim costs
    plans: list[str]
    base_cc_male: dict[str, list[float]]     # plan -> claim cost by age
    base_cc_female: dict[str, list[float]]
    state_factors: dict[str, float]          # state -> claim cost factor
    selection_factors: list[dict]            # rows of {duration, issue_age, uw, factor}
    cc_aging_by_duration: list[float]        # antiselection (col P) aging factor by duration
    preferred_factor: dict[str, float]       # Y/N -> factor (applied for UW class only)
    hhd_factor: dict[str, float]             # Y/N -> factor
    trend_by_year: list[float]               # claims trend by duration year

    def base_cc(self, gender: str) -> dict[str, list[float]]:
        return self.base_cc_male if gender == "M" else self.base_cc_female


@dataclass
class RerateAssumptions:
    solve: bool
    specified_rerates: list[float]           # rerate % by duration (durations 1..30)
    aging_rerate_by_age_ages: list[int]      # attained-age axis for premium aging-rerate (col H)
    aging_rerate_by_age_factor: list[float]
    target_lifetime_lr: float
    target_irr: Optional[float]
    max_rerate: float                        # rule: no single rerate above this
    in_year_lr_floor: float                  # rule: in-year LR may never fall below this
    consecutive_z: float                     # rule: no consecutive rerates above z ...
    consecutive_b: int                       # ... for b years running
    antiselection_lambda: float              # the 0.5 in 0.5*(rerate - trend)


@dataclass
class DistributionAssumptions:
    gender: dict[str, float]                 # M/F -> weight
    preferred: dict[str, float]              # Y/N -> weight
    hhd: dict[str, float]                    # Y/N -> weight


@dataclass
class TerminationAssumptions:
    base_lapse: dict[str, list[float]]       # uw class -> lapse rate by duration
    state_factors: dict[str, float]          # state -> lapse factor
    mort_age: list[int]
    mort_qx: list[float]
    dur2_scaling: float                      # termination multiplier in duration 2
    dur3plus_scaling: float                  # termination multiplier in durations 3+

    def mortality(self, attained_age: int) -> float:
        a = min(attained_age, max(self.mort_age))
        try:
            return self.mort_qx[self.mort_age.index(a)]
        except ValueError:
            # nearest-not-exceeding fallback
            best = self.mort_age[0]
            for ag in self.mort_age:
                if ag <= a:
                    best = ag
            return self.mort_qx[self.mort_age.index(best)]


@dataclass
class CommissionAssumptions:
    by_state: dict[str, list[float]]         # state -> base commission rate by duration
    plan_n_schedule: list[float]             # plan N alternate schedule by duration
    nonn_schedule: list[float]               # non-N schedule by duration
    gi_flat: float                           # flat commission for GI business
    plan_f_offset: float                     # premium offset for plan F commission base
    age80_halving: bool                      # halve commission for issue age >= 80

    def rate(self, state: str, duration: int, plan: str) -> float:
        """Commission rate for a duration. Prefer the state schedule; the plan-N
        vs non-N split scales the state rate by the ratio of the two national
        schedules so both state and plan/duration variation are honoured."""
        d = duration - 1
        sched = self.by_state.get(state) or self.by_state.get("All")
        base = sched[d] if sched and d < len(sched) and sched[d] is not None else 0.0
        nat = self.nonn_schedule[d] if d < len(self.nonn_schedule) else None
        if plan == "N" and nat:
            alt = self.plan_n_schedule[d] if d < len(self.plan_n_schedule) else nat
            base = base * (alt / nat) if nat else base
        return base


@dataclass
class OtherAssumptions:
    discount_rate: float
    premium_tax: float
    oper_acq: float
    marketing_acq: float
    maintenance: float
    inflation: float
    rbc_factor: float
    covariance: float
    rbc_pct_of_prem: float
    nier: float
    tax_rate: float
    ibnr_pct: float


@dataclass
class AssumptionSet:
    morbidity: MorbidityAssumptions
    rerates: RerateAssumptions
    distribution: DistributionAssumptions
    termination: TerminationAssumptions
    commission: CommissionAssumptions
    other: OtherAssumptions
    schema_version: str = "1"
