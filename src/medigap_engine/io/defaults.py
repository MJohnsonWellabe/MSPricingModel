"""Load the bundled seed assumptions and pricing-cell universe.

Uses importlib.resources so it works from an installed wheel and from the
Pyodide virtual filesystem alike.
"""
from __future__ import annotations

import json
from functools import lru_cache

try:
    from importlib.resources import files as _files  # Python 3.9+
except ImportError:  # pragma: no cover
    _files = None

from ..models.assumptions import AssumptionSet
from ..models.cell import CellKey, PricingCell
from .serialize import assumptions_from_dict


def _load_json(name: str) -> object:
    if _files is not None:
        data = _files("medigap_engine.data").joinpath(name).read_text(encoding="utf-8")
        return json.loads(data)
    import os  # pragma: no cover
    here = os.path.join(os.path.dirname(__file__), "..", "data", name)
    with open(here, encoding="utf-8") as fh:  # pragma: no cover
        return json.load(fh)


def load_template_csv(name: str) -> str:
    """Return the text of a bundled template/sample CSV under data/templates/.

    ``name`` is e.g. 'sales_template.csv', 'claims_sample.csv'."""
    if _files is not None:
        return _files("medigap_engine.data.templates").joinpath(name).read_text(encoding="utf-8")
    import os  # pragma: no cover
    here = os.path.join(os.path.dirname(__file__), "..", "data", "templates", name)
    with open(here, encoding="utf-8") as fh:  # pragma: no cover
        return fh.read()


@lru_cache(maxsize=1)
def default_assumptions() -> AssumptionSet:
    return assumptions_from_dict(_load_json("default_assumptions.json"))


def build_cells(asm: AssumptionSet) -> tuple[PricingCell, ...]:
    """Generate the full pricing-cell cross-product, weighting each cell by the
    product of the distribution factors. Cell dimensions come from the assumption
    tables so they stay in sync with edits."""
    dist = asm.distribution
    ages = sorted(dist.by_issue_age) or list(asm.morbidity.ages)
    genders = list(dist.gender) or ["M", "F"]
    plans = list(dist.plan) or list(asm.morbidity.plans)
    uws = list(dist.uw) or ["UW", "OE", "GI"]
    prefs = list(dist.preferred) or ["Y", "N"]
    hhds = list(dist.hhd) or ["Y", "N"]
    cells = []
    for a in ages:
        for g in genders:
            for pl in plans:
                for uw in uws:
                    for pr in prefs:
                        for h in hhds:
                            key = CellKey(issue_age=int(a), gender=g, plan=pl,
                                          uw_class=uw, preferred=pr, hhd=h)
                            cells.append(PricingCell(key=key, weight=dist.weight(key)))
    return tuple(cells)


def default_cells() -> tuple[PricingCell, ...]:
    """Convenience: build cells from the bundled default assumptions."""
    return build_cells(default_assumptions())


def available_states() -> list[str]:
    """States offered by the model (from the premium state-factor table)."""
    states = set(default_assumptions().premium.state_factor)
    ordered = ["All"] + sorted(s for s in states if s != "All")
    return ordered
