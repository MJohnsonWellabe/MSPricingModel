"""Output tab: per-state summary (lifetime LR & IRR) with drill-down into a
state's full income statement."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from medigap_engine.models.assumptions import PROJECTION_YEARS

# income-statement lines shown on drill-down, in presentation order
_INCOME_ROWS = [
    ("earned_prem", "Earned premium"),
    ("nii", "Net investment income"),
    ("claims", "Claims"),
    ("commission", "Commission"),
    ("premium_tax", "Premium tax"),
    ("oper_acq", "Operating acquisition"),
    ("marketing", "Marketing acquisition"),
    ("maintenance", "Maintenance"),
    ("pretax_income", "Pre-tax income"),
    ("tax", "Tax"),
    ("at_income", "After-tax income"),
    ("rbc", "RBC"),
    ("ah_cashflow", "Distributable cashflow"),
    ("in_year_lr", "In-year loss ratio"),
    ("lifetime_lr", "Lifetime loss ratio"),
]


def render() -> None:
    st.header("Output")
    result = st.session_state.get("run_result")
    if not result:
        st.info("No results yet. Configure a run and compute it on the Calculation tab.")
        return

    st.subheader("Summary by state")
    rows = []
    for state, st_res in result.by_state.items():
        rows.append({
            "State": state,
            "Lifetime LR": round(st_res.lifetime_lr, 4),
            "IRR": round(st_res.irr, 4),
            "NPV pre-tax income": round(st_res.npv_pretax, 2),
            "NPV premium": round(st_res.npv_premium, 2),
        })
    if result.all_states and len(result.by_state) > 1:
        cs = result.all_states
        rows.append({
            "State": "Combined", "Lifetime LR": round(cs.lifetime_lr, 4),
            "IRR": round(cs.irr, 4), "NPV pre-tax income": round(cs.npv_pretax, 2),
            "NPV premium": round(cs.npv_premium, 2),
        })
    summary = pd.DataFrame(rows)
    st.dataframe(summary, hide_index=True, use_container_width=True)
    st.download_button("Download summary (CSV)", summary.to_csv(index=False),
                       "summary.csv", "text/csv")

    st.divider()
    st.subheader("State income statement")
    state = st.selectbox("Select a state to drill into", list(result.by_state.keys()))
    series = result.by_state[state].series
    data = {label: series[key] for key, label in _INCOME_ROWS}
    df = pd.DataFrame(data).T
    df.columns = [f"Yr {i}" for i in range(1, PROJECTION_YEARS + 1)]
    st.dataframe(df, use_container_width=True, height=560)

    st.line_chart(pd.DataFrame({
        "In-year LR": series["in_year_lr"],
        "Lifetime LR": series["lifetime_lr"],
    }))

    st.divider()
    st.subheader("Trend & rerates by year")
    from app.state import get_assumptions
    asm = get_assumptions()
    trend = asm.morbidity.trend_by_year
    rerate = series.get("rerate_used", [0.0] * PROJECTION_YEARS)
    tr = pd.DataFrame({
        "Duration": list(range(1, PROJECTION_YEARS + 1)),
        "Trend": [trend[min(i, len(trend) - 1)] for i in range(PROJECTION_YEARS)],
        "Rerate used": rerate,
    })
    st.dataframe(tr, hide_index=True, use_container_width=True, height=320)
    st.line_chart(tr.set_index("Duration")[["Trend", "Rerate used"]])
