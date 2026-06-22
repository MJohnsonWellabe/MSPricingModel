"""Output tab: per-state summary (lifetime LR & IRR) with drill-down into a
state's full income statement."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from medigap_engine.models.assumptions import PROJECTION_YEARS

# income-statement lines shown on drill-down, in presentation order
_INCOME_ROWS = [
    ("lives", "Lives"),
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


def _experience_dur1_lr():
    """Per-state duration-1 actual loss ratio (Σ adj_claims / Σ earned for duration 1) from
    the loaded claims experience, plus an "__all__" book figure. None if no experience."""
    records = st.session_state.get("claims_records")
    if not records:
        return None
    acc: dict = {}
    tot_c = tot_e = 0.0
    for r in records:
        try:
            if int(float(r.get("duration", 0))) != 1:
                continue
            c = float(r.get("adj_claims", 0.0) or 0.0)
            e = float(r.get("earned", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        s = str(r.get("state", "")).strip().upper()
        a = acc.setdefault(s, [0.0, 0.0])
        a[0] += c
        a[1] += e
        tot_c += c
        tot_e += e
    out = {s: (cc / ee if ee else float("nan")) for s, (cc, ee) in acc.items()}
    out["__all__"] = tot_c / tot_e if tot_e else float("nan")
    return out


def render() -> None:
    st.header("Output")
    result = st.session_state.get("run_result")
    if not result:
        st.info("No results yet. Configure a run and compute it on the Calculation tab.")
        return

    st.subheader("Summary by state")

    # duration-1 experience loss ratio per state from the loaded claims experience
    exp_lr = _experience_dur1_lr()

    # income-statement lines shown as NPV ÷ NPV premium (a source-of-margin walk)
    _MARGIN_LINES = [
        ("nii", "NII %"), ("claims", "Claims %"), ("commission", "Commission %"),
        ("premium_tax", "Premium tax %"), ("oper_acq", "Oper acq %"),
        ("marketing", "Marketing %"), ("maintenance", "Maintenance %"),
        ("pretax_income", "Pre-tax %"),
    ]

    def _row(name, r):
        # FY premium/claims as PMPY (per member per year): the engine computes both as
        # rate x avg_lives, so dividing by year-1 member-years recovers the per-policy-year
        # rate that lines up with a Σclaims/Σcnt pull from the data. avg_lives[0] =
        # (lives_prev + lives_d)/2 and lives_prev is 1.0 at issue (book starts at weight 1).
        exposure1 = (1.0 + r.series["lives"][0]) / 2.0
        prem1 = r.series["earned_prem"][0] / exposure1 if exposure1 else 0.0
        clm1 = r.series["claims"][0] / exposure1 if exposure1 else 0.0
        row = {
            "State": name,
            "FY premium": round(prem1, 2),
            "FY claims": round(clm1, 2),
            "FY LR": round(clm1 / prem1, 4) if prem1 else 0.0,
        }
        if exp_lr is not None:
            row["Exp LR (d1)"] = round(exp_lr.get(name, exp_lr.get("__all__", float("nan"))), 4)
        row["Lifetime LR"] = round(r.lifetime_lr, 4)
        row["Pretax margin"] = round(r.pretax_margin, 4)
        row["IRR"] = round(r.irr, 4)
        row["NPV pre-tax income"] = round(r.npv_pretax, 2)
        row["NPV premium"] = round(r.npv_premium, 2)
        denom = r.npv_premium or 0.0
        for key, label in _MARGIN_LINES:
            v = r.npv_by_line.get(key) if r.npv_by_line else None
            row[label] = round(v / denom, 4) if (v is not None and denom) else 0.0
        return row

    rows = [_row(state, r) for state, r in result.by_state.items()]
    if result.all_states and len(result.by_state) > 1:
        rows.append(_row("Combined", result.all_states))
    summary = pd.DataFrame(rows)
    st.dataframe(summary, hide_index=True, use_container_width=True)
    st.caption("FY = first projection year (duration 1); **FY premium and FY claims are "
               "PMPY** (per member per year — divided by first-year member-years), so they "
               "compare like-for-like with a Σclaims/Σcnt pull from the data. The trailing "
               "**%** columns are the NPV of each income-statement line ÷ NPV of premium — a "
               "source-of-margin walk (premium 100% + NII − claims − expenses = pre-tax %). "
               "Exp LR (d1) is the duration-1 actual loss ratio from the loaded claims "
               "experience, if any.")
    st.download_button("Download summary (CSV)", summary.to_csv(index=False),
                       "summary.csv", "text/csv", key="out_download")

    st.divider()
    st.subheader("State income statement")
    state = st.selectbox("Select a state to drill into", list(result.by_state.keys()),
                         key="out_state")
    series = result.by_state[state].series
    st.caption(
        "Per policy issued: the book is normalised to a starting weight of 1, so "
        "**Lives** is the surviving inforce per issued policy and the dollar lines "
        "are amounts per issued policy."
    )
    data = {label: series[key] for key, label in _INCOME_ROWS}
    df = pd.DataFrame(data).T
    df.columns = [f"Yr {i}" for i in range(1, PROJECTION_YEARS + 1)]
    # st.table keeps the income-statement row order fixed (no interactive re-sort)
    st.table(df.style.format("{:,.2f}"))

    st.line_chart(pd.DataFrame({
        "In-year LR": series["in_year_lr"],
        "Lifetime LR": series["lifetime_lr"],
    }))

    st.divider()
    st.subheader("Trend & rerates by year")
    from app.state import get_assumptions
    asm = get_assumptions()
    trend = asm.morbidity.trend_by_year
    rerate = result.by_state[state].rerates or [0.0] * PROJECTION_YEARS
    tr = pd.DataFrame({
        "Duration": list(range(1, PROJECTION_YEARS + 1)),
        "Trend": [trend[min(i, len(trend) - 1)] for i in range(PROJECTION_YEARS)],
        "Rerate used": [rerate[i] if i < len(rerate) else 0.0
                        for i in range(PROJECTION_YEARS)],
    })
    st.dataframe(tr, hide_index=True, use_container_width=True, height=320)
    st.line_chart(tr.set_index("Duration")[["Trend", "Rerate used"]])
