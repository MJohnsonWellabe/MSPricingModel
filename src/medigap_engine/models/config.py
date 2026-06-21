"""Run configuration produced by the Configuration tab."""
from __future__ import annotations

from dataclasses import dataclass, field

from .sensitivities import SensitivitySet


@dataclass
class RunConfig:
    states: list[str]                         # states to run ("All" allowed)
    use_experience_study: bool = False
    sensitivities: SensitivitySet = field(default_factory=SensitivitySet)
    solve_rerates: bool = True                # may override the assumption-level flag
