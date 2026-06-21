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
    base_cc: dict[str, list[float]]          # plan -> base claim cost by age (reference gender)
    gender_cc_factor: dict[str, float]       # M/F -> claim cost factor on the base table
    state_factors: dict[str, float]          # state -> claim cost factor
    selection_factors: list[dict]            # rows of {duration, issue_age, uw, factor}
    cc_aging_by_duration: list[float]        # antiselection (col P) aging factor by duration
    preferred_diff: float                    # claims: 'no preferred' exceeds 'preferred' by this %
    hhd_diff: float                          # claims: 'no hhd' exceeds 'hhd' by this %
    trend_by_year: list[float]               # claims trend by duration year
    trend_first_year_exponent: float = 1.75  # power applied to (1+trend) in duration 1


def derive_two_level(weight_yes: float, diff: float) -> dict[str, float]:
    """Back out Y/N factors from a differential, normalised so the
    distribution-weighted mean is 1 (the base table already carries the blend):
    f_N = (1+diff) * f_Y, and w_Y*f_Y + w_N*f_N = 1."""
    w_y = max(0.0, min(1.0, weight_yes))
    w_n = 1.0 - w_y
    f_y = 1.0 / (w_y + w_n * (1.0 + diff)) if (w_y + w_n * (1.0 + diff)) else 1.0
    return {"Y": f_y, "N": f_y * (1.0 + diff)}


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
    antiselection_lambda_claims: float       # the 0.5 in 0.5*(rerate - trend) for claims (col P)
    antiselection_lambda_lapse: float        # the 0.5 in 0.5*(rerate - trend) for the lapse load


@dataclass
class PremiumAssumptions:
    """Premium as a multiplicative factor model:

        premium(cell, state) = base_by_issue_age[age]
            * gender_factor[g] * plan_factor[plan] * uw_factor[uw]
            * preferred_factor[pref] * hhd_factor[hhd] * state_factor[state]
    """
    base_by_issue_age: dict[int, float]
    gender_factor: dict[str, float]
    plan_factor: dict[str, float]
    uw_factor: dict[str, float]
    preferred_factor: dict[str, float]
    hhd_factor: dict[str, float]
    state_factor: dict[str, float]

    def premium(self, key, state: str) -> float:
        base = self.base_by_issue_age.get(key.issue_age)
        if base is None:  # nearest issue-age band
            ages = sorted(self.base_by_issue_age)
            base = self.base_by_issue_age[min(ages, key=lambda a: abs(a - key.issue_age))]
        sf = self.state_factor.get(state, self.state_factor.get("All", 1.0))
        return (
            base
            * self.gender_factor.get(key.gender, 1.0)
            * self.plan_factor.get(key.plan, 1.0)
            * self.uw_factor.get(key.uw_class, 1.0)
            * self.preferred_factor.get(key.preferred, 1.0)
            * self.hhd_factor.get(key.hhd, 1.0)
            * sf
        )


@dataclass
class DistributionAssumptions:
    """Distribution as independent per-dimension weight factors. Each dimension's
    weights sum to 1; a cell's weight is the product across dimensions."""
    by_issue_age: dict[int, float]
    gender: dict[str, float]
    plan: dict[str, float]
    uw: dict[str, float]
    preferred: dict[str, float]
    hhd: dict[str, float]

    def weight(self, key) -> float:
        return (
            self.by_issue_age.get(key.issue_age, 0.0)
            * self.gender.get(key.gender, 0.0)
            * self.plan.get(key.plan, 0.0)
            * self.uw.get(key.uw_class, 0.0)
            * self.preferred.get(key.preferred, 0.0)
            * self.hhd.get(key.hhd, 0.0)
        )


@dataclass
class TerminationAssumptions:
    base_lapse: list[float]                   # OE/GI ("other") lapse rate by duration
    uw_lapse_factor: list[float]              # UW lapse = base_lapse * this, by duration
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
    premium: PremiumAssumptions
    rerates: RerateAssumptions
    distribution: DistributionAssumptions
    termination: TerminationAssumptions
    commission: CommissionAssumptions
    other: OtherAssumptions
    schema_version: str = "1"
