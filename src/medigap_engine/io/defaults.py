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


@lru_cache(maxsize=1)
def default_assumptions() -> AssumptionSet:
    return assumptions_from_dict(_load_json("default_assumptions.json"))


@lru_cache(maxsize=1)
def default_cells() -> tuple[PricingCell, ...]:
    raw = _load_json("default_cells.json")
    cells = []
    for r in raw:
        key = CellKey(
            issue_age=int(r["issue_age"]), gender=r["gender"], plan=r["plan"],
            uw_class=r["uw"], preferred=r["preferred"], hhd=r["hhd"],
        )
        cells.append(PricingCell(
            key=key, base_prem=float(r["premium"]), weight=float(r["weight"]),
            state_premiums=r.get("state_premiums") or {},
        ))
    return tuple(cells)


def available_states() -> list[str]:
    """States offered by the model (from the bundled cell premiums + the All book)."""
    cells = default_cells()
    states: set[str] = set()
    for c in cells:
        if c.state_premiums:
            states.update(c.state_premiums.keys())
    ordered = ["All"] + sorted(s for s in states if s != "All")
    return ordered
