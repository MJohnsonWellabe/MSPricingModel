import copy

import pytest

from medigap_engine.io.defaults import default_assumptions, default_cells
from medigap_engine.models.cell import CellKey, PricingCell
from medigap_engine.models.sensitivities import SensitivitySet


@pytest.fixture
def asm():
    # deep copy so tests may mutate assumptions without affecting the cached default
    return copy.deepcopy(default_assumptions())


@pytest.fixture
def cells():
    return list(default_cells())


@pytest.fixture
def base_sens():
    return SensitivitySet()


@pytest.fixture
def sample_cell():
    key = CellKey(issue_age=65, gender="M", plan="G", uw_class="UW",
                  preferred="Y", hhd="Y")
    return PricingCell(key=key, weight=1.0)
