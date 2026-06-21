"""Pricing cell definitions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CellKey:
    issue_age: int
    gender: str        # "M" / "F"
    plan: str          # "F" / "G" / "N"
    uw_class: str      # "UW" / "OE" / "GI"
    preferred: str     # "Y" / "N"
    hhd: str           # "Y" / "N"

    def label(self) -> str:
        return (
            f"{self.issue_age}{self.gender}-{self.plan}-{self.uw_class}"
            f"-P{self.preferred}-H{self.hhd}"
        )


@dataclass(frozen=True)
class PricingCell:
    key: CellKey
    base_prem: float
    weight: float = 1.0
    # optional per-state premium overrides (state -> annual premium)
    state_premiums: dict = None

    def premium_for(self, state: str) -> float:
        if self.state_premiums and state in self.state_premiums:
            return self.state_premiums[state]
        return self.base_prem
