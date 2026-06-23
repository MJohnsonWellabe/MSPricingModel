"""Granular output tab: drill a selected state's results down by plan, issue age, and UW
class. Each subgroup is renormalised to a per-policy basis and re-aggregated, so the summary
metrics (PMPY, loss ratio, margin, IRR) are comparable across groups."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from app.state import get_assumptions
from medigap_engine.engine.aggregate import aggregate_cells


def _summary(state, cells, asm) -> dict:
    sub = sum(c.weight for c in cells) or 1.0
    rew = [replace(c, weight=c.weight / sub) for c in cells]   # renormalise subgroup to 1
    agg = aggregate_cells(state, rew, asm)
    s = agg.series
    al0 = (1.0 + s["lives"][0]) / 2.0 or 1.0   # first-year member-years (avg lives)
    prem0 = s["earned_prem"][0]
    return {
        "FY prem PMPY": round(prem0 / al0, 2),
        "FY claims PMPY": round(s["claims"][0] / al0, 2),
        "FY LR": round(s["claims"][0] / prem0, 4) if prem0 else 0.0,
        "Lifetime LR": round(agg.lifetime_lr, 4),
        "Pretax margin": round(agg.pretax_margin, 4),
        "IRR": round(agg.irr, 4),
        "Book weight": round(sub, 4),
    }


def render() -> None:
    st.header("Granular output")
    result = st.session_state.get("run_result")
    if not result:
        st.info("No results yet — run the model from the Configuration tab.")
        return
    asm = get_assumptions()
    state = st.selectbox("State", list(result.by_state.keys()), key="gran_state")
    cells = result.by_state[state].cells
    if not cells:
        st.info("No per-cell detail for this selection (the combined view aggregates states; "
                "pick an individual state).")
        return
    st.caption("Each row renormalises its subgroup to a per-policy basis. FY = first projection "
               "year; PMPY = per member per year; Lifetime LR is NPV-discounted. **Book weight** "
               "is the subgroup's share of the state's distribution.")

    for label, keyfn in (("Plan", lambda c: c.key.plan),
                         ("Issue age", lambda c: c.key.issue_age),
                         ("UW class", lambda c: c.key.uw_class)):
        groups: dict = {}
        for c in cells:
            groups.setdefault(keyfn(c), []).append(c)
        rows = {g: _summary(state, gc, asm)
                for g, gc in sorted(groups.items(), key=lambda kv: str(kv[0]))}
        st.markdown(f"#### By {label}")
        st.dataframe(pd.DataFrame(rows).T, use_container_width=True)
