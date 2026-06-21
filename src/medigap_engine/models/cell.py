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
    """A pricing cell. Premium is no longer stored here — it is derived from the
    premium factor model (``AssumptionSet.premium``) per cell and state."""
    key: CellKey
    weight: float = 1.0
