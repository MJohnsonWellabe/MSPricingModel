"""Sensitivity scenario definitions.

Each multiplier defaults to a no-op (1.0). The Configuration tab lets the user
dial these to stress the model:

* morbidity_scale       -> scales base claim costs (cc * 1.xx)
* termination_scale     -> scales termination/lapse rates (wx * 1.xx)
* rerate_effectiveness  -> scales achieved rerates (recommended rerates * 0.xx)
* antiselective_lapse   -> extra multiplier on the rerate-driven lapse antiselection
* antiselective_claims  -> extra multiplier on the rerate-driven claims antiselection
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SensitivitySet:
    morbidity_scale: float = 1.0
    termination_scale: float = 1.0
    rerate_effectiveness: float = 1.0
    antiselective_lapse: float = 1.0
    antiselective_claims: float = 1.0

    @property
    def is_base(self) -> bool:
        return (
            self.morbidity_scale == 1.0
            and self.termination_scale == 1.0
            and self.rerate_effectiveness == 1.0
            and self.antiselective_lapse == 1.0
            and self.antiselective_claims == 1.0
        )
