"""Derive distribution weights and average premiums by cell from sales data."""
from __future__ import annotations

from .schema import normalize_sales

# cell key tuple: (issue_age, gender, plan, uw_class, preferred, hhd)
CellKeyTuple = tuple


def aggregate_sales(rows) -> dict:
    """Aggregate raw sales rows into per-cell distribution weights and premiums.

    Returns a dict with:
      * ``weights``         cell-key -> distribution weight (sums to 1)
      * ``avg_premium``     cell-key -> average entered premium (overall)
      * ``state_premiums``  cell-key -> {state: average premium}
      * ``counts``          cell-key -> total application count
      * ``n_rows`` / ``total_count`` summary figures
    """
    canon = normalize_sales(rows)
    counts: dict[CellKeyTuple, float] = {}
    prem_sum: dict[CellKeyTuple, float] = {}
    state_count: dict[CellKeyTuple, dict[str, float]] = {}
    state_prem: dict[CellKeyTuple, dict[str, float]] = {}

    for r in canon:
        key = (r["issue_age"], r["gender"], r["plan"], r["uw_class"],
               r["preferred"], r["hhd"])
        c = r["application_count"]
        p = r["entered_premium"]
        counts[key] = counts.get(key, 0.0) + c
        prem_sum[key] = prem_sum.get(key, 0.0) + p
        st = r["state"]
        state_count.setdefault(key, {})[st] = state_count.get(key, {}).get(st, 0.0) + c
        state_prem.setdefault(key, {})[st] = state_prem.get(key, {}).get(st, 0.0) + p

    total = sum(counts.values()) or 1.0
    weights = {k: v / total for k, v in counts.items()}
    avg_premium = {k: (prem_sum[k] / counts[k] if counts[k] else 0.0) for k in counts}
    state_premiums = {
        k: {s: (state_prem[k][s] / state_count[k][s] if state_count[k][s] else 0.0)
            for s in state_count[k]}
        for k in counts
    }
    return {
        "weights": weights,
        "avg_premium": avg_premium,
        "state_premiums": state_premiums,
        "state_counts": state_count,    # cell-key -> {state: application count}
        "counts": counts,
        "n_rows": len(canon),
        "total_count": total,
    }
