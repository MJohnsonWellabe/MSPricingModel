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
class PullForwardAssumptions:
    """Brings the experience-period base claims and premium forward to the pricing
    period with a one-time factor ``(1 + trend) ** duration``. The pulled-forward
    level *is* the year-1 (duration-1) level; the year-by-year projection trend
    (``MorbidityAssumptions.trend_by_year``) then compounds from year 1->2 onward."""
    duration: float = 1.75          # years from the experience period to the pricing period
    claims_trend: float = 0.10      # annual claims trend used to pull current claims forward
    premium_trend: float = 0.05     # annual premium trend used to pull current premium forward


@dataclass
class MorbidityAssumptions:
    ages: list[int]                          # attained-age axis for base claim costs
    plans: list[str]
    base_cc: dict[str, list[float]]          # plan -> base (gender-blend) claim cost by age
    gender_cc_diff: float                    # claims: male is this % above female
    state_factors: dict[str, float]          # state -> claim cost factor
    selection_factors: list[dict]            # rows of {duration, issue_age, uw, factor}
    cc_aging_by_duration: list[float]        # antiselection (col P) aging factor by duration
    preferred_diff: float                    # claims: 'no preferred' exceeds 'preferred' by this %
    hhd_diff: float                          # claims: 'no hhd' exceeds 'hhd' by this %
    trend_by_year: list[float]               # claims trend by duration year (projection trend)


def normalized_factors(rel: dict, weights: dict) -> dict:
    """Normalise relativities so the mix-weighted mean factor is 1:
    ``f_v = rel_v / Σ_v weights_v * rel_v``. Levels missing from ``weights`` get
    equal weight. Keeps the blended base table unchanged on average."""
    denom = 0.0
    total_w = 0.0
    for v, r in rel.items():
        w = weights.get(v)
        if w is None:
            w = None  # resolve after we know how many are missing
        else:
            total_w += w
    # equal weight for any levels absent from `weights`
    missing = [v for v in rel if weights.get(v) is None]
    eq = (1.0 - total_w) / len(missing) if missing else 0.0
    for v, r in rel.items():
        w = weights.get(v, eq)
        denom += w * r
    if denom == 0:
        return {v: 1.0 for v in rel}
    return {v: r / denom for v, r in rel.items()}


def derive_two_level(weight_yes: float, diff: float) -> dict[str, float]:
    """Back out Y/N factors from a differential, normalised so the
    distribution-weighted mean is 1 (the base table already carries the blend):
    f_N = (1+diff) * f_Y, and w_Y*f_Y + w_N*f_N = 1."""
    w_y = max(0.0, min(1.0, weight_yes))
    return normalized_factors({"Y": 1.0, "N": 1.0 + diff}, {"Y": w_y, "N": 1.0 - w_y})


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
    """Premium as base × relativity factors:

        premium(cell, state) = base_by_issue_age[age] (blend at plan G)
            * plan_rel[plan]                         (G anchored at 1.0, not normalised)
            * normalized(gender_rel, gender mix)
            * normalized(preferred_rel, preferred mix)
            * normalized(hhd_rel, hhd mix)
            * normalized(uw_rel, uw mix)
            * state_factor[state]                    (raw)

    The premium() helper here is base × plan × raw-relativities (no mix
    normalisation); use ``lookups.premium_for_cell`` for the mix-normalised value.
    """
    base_by_issue_age: dict[int, float]
    plan_rel: dict[str, float]               # G anchored at 1.0 (not normalised)
    uw_rel: dict[str, float]                 # 3-level relativity (normalised by uw mix)
    gender_diff: float                       # premium: male this % above female
    preferred_diff: float                    # premium: non-preferred this % above preferred
    hhd_diff: float                          # premium: non-hhd this % above hhd
    state_factor: dict[str, float]

    def base_for_age(self, issue_age: int) -> float:
        base = self.base_by_issue_age.get(issue_age)
        if base is None:  # nearest issue-age band
            ages = sorted(self.base_by_issue_age)
            base = self.base_by_issue_age[min(ages, key=lambda a: abs(a - issue_age))]
        return base


@dataclass
class DistributionAssumptions:
    """Distribution as a JOINT plan x issue-age x UW weight grid (these vary
    together and are not separable) with independent gender / preferred / HHD
    marginals applied on top. The grid weights sum to 1 across all
    (plan, age, uw); each marginal sums to 1. A cell's weight is
    ``grid[plan][age][uw] * gender * preferred * hhd``.

    ``plan`` / ``by_issue_age`` / ``uw`` are exposed as derived marginal
    properties (sums over the grid) so factor-normalisation and cell enumeration
    keep using a per-dimension mix."""
    joint: dict[str, dict[str, dict[str, float]]]   # plan -> age(str) -> uw -> weight
    gender: dict[str, float]
    preferred: dict[str, float]
    hhd: dict[str, float]

    @property
    def plan(self) -> dict[str, float]:
        return {pl: sum(w for uws in ages.values() for w in uws.values())
                for pl, ages in self.joint.items()}

    @property
    def by_issue_age(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for ages in self.joint.values():
            for a, uws in ages.items():
                out[int(a)] = out.get(int(a), 0.0) + sum(uws.values())
        return dict(sorted(out.items()))

    @property
    def uw(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for ages in self.joint.values():
            for uws in ages.values():
                for u, w in uws.items():
                    out[u] = out.get(u, 0.0) + w
        return out

    def weight(self, key) -> float:
        jw = self.joint.get(key.plan, {}).get(str(key.issue_age), {}).get(key.uw_class, 0.0)
        return (
            jw
            * self.gender.get(key.gender, 0.0)
            * self.preferred.get(key.preferred, 0.0)
            * self.hhd.get(key.hhd, 0.0)
        )


@dataclass
class TerminationAssumptions:
    base_lapse: list[float]                   # blended lapse rate by duration (uw mix)
    uw_lapse_rel: list[float]                 # UW-vs-other lapse relativity by duration
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
    pull_forward: PullForwardAssumptions = field(default_factory=PullForwardAssumptions)
    schema_version: str = "1"
