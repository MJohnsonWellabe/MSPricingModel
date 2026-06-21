"""Assumptions tab with six subtabs. Editable scalars and tables write back to
the AssumptionSet held in session state. Supports JSON download/upload so
configurations persist without a server."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import (
    assumptions_json,
    get_assumptions,
    load_assumptions_json,
    reset_assumptions,
)
from medigap_engine.models.assumptions import PROJECTION_YEARS


def render() -> None:
    st.header("Assumptions")

    top = st.columns([1, 1, 2])
    with top[0]:
        st.download_button("Download JSON", assumptions_json(),
                           "assumptions.json", "application/json")
    with top[1]:
        if st.button("Reset to defaults"):
            reset_assumptions()
            st.rerun()
    with top[2]:
        up = st.file_uploader("Upload assumptions JSON", type=["json"])
        if up is not None:
            load_assumptions_json(up.getvalue().decode("utf-8"))
            st.success("Assumptions loaded.")

    asm = get_assumptions()
    sub = st.tabs([
        "Morbidity", "Rerates", "Distribution",
        "Termination", "Commission", "Other",
    ])
    with sub[0]:
        _morbidity(asm)
    with sub[1]:
        _rerates(asm)
    with sub[2]:
        _distribution(asm)
    with sub[3]:
        _termination(asm)
    with sub[4]:
        _commission(asm)
    with sub[5]:
        _other(asm)


def _morbidity(asm) -> None:
    m = asm.morbidity
    st.subheader("Base claim costs by plan and attained age")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Male**")
        dfm = pd.DataFrame(m.base_cc_male, index=m.ages)
        edm = st.data_editor(dfm, use_container_width=True, height=300, key="cc_male")
        for p in m.plans:
            m.base_cc_male[p] = edm[p].tolist()
    with cols[1]:
        st.markdown("**Female**")
        dff = pd.DataFrame(m.base_cc_female, index=m.ages)
        edf = st.data_editor(dff, use_container_width=True, height=300, key="cc_female")
        for p in m.plans:
            m.base_cc_female[p] = edf[p].tolist()

    st.subheader("Trend by duration year")
    m.trend_first_year_exponent = st.number_input(
        "First-year trend exponent (applied to (1+trend) in duration 1)",
        value=float(m.trend_first_year_exponent), step=0.05, format="%.2f",
        help="Reflects time from pricing to the midpoint of the first duration. "
             "Was hard-coded to 1.75 in the workbook; now an input.")
    tdf = pd.DataFrame({"Trend": m.trend_by_year}, index=range(1, len(m.trend_by_year) + 1))
    ted = st.data_editor(tdf, use_container_width=True, height=240, key="trend")
    m.trend_by_year = ted["Trend"].tolist()

    st.subheader("State morbidity factors")
    sdf = pd.DataFrame({"Factor": m.state_factors})
    sed = st.data_editor(sdf, use_container_width=True, height=240, key="state_factors")
    m.state_factors = sed["Factor"].to_dict()

    st.subheader("Household & preferred claim factors")
    c = st.columns(2)
    c[0].caption("Preferred (applied for UW class only)")
    c[0].write(m.preferred_factor)
    c[1].caption("Household discount")
    c[1].write(m.hhd_factor)
    st.caption("Selection (antiselection) factors and claim-cost aging are shown "
               "read-only here; they will become editable in a later phase.")


def _rerates(asm) -> None:
    r = asm.rerates
    st.subheader("Rerate strategy")
    r.solve = st.toggle("Solve rerates to hit target lifetime loss ratio",
                        value=r.solve)
    c = st.columns(3)
    r.target_lifetime_lr = c[0].number_input("Target lifetime LR", value=float(r.target_lifetime_lr),
                                             step=0.01, format="%.3f")
    r.target_irr = c[1].number_input("Target IRR (reported)", value=float(r.target_irr or 0.0),
                                     step=0.01, format="%.3f")
    c2 = st.columns(2)
    r.antiselection_lambda_claims = c2[0].number_input(
        "Antiselection λ — claims", value=float(r.antiselection_lambda_claims),
        step=0.05, format="%.2f",
        help="The factor in λ×(rerate−trend) added to the claims antiselection (column P).")
    r.antiselection_lambda_lapse = c2[1].number_input(
        "Antiselection λ — lapse", value=float(r.antiselection_lambda_lapse),
        step=0.05, format="%.2f",
        help="The factor in λ×(rerate−trend) applied to the UW lapse antiselection.")

    st.subheader("Rules")
    c2 = st.columns(4)
    r.max_rerate = c2[0].number_input("Max single rerate", value=float(r.max_rerate),
                                      step=0.01, format="%.3f")
    r.in_year_lr_floor = c2[1].number_input("In-year LR floor", value=float(r.in_year_lr_floor),
                                            step=0.01, format="%.3f")
    r.consecutive_z = c2[2].number_input("Consecutive rule: z", value=float(r.consecutive_z),
                                         step=0.01, format="%.3f")
    r.consecutive_b = int(c2[3].number_input("Consecutive rule: b (years)",
                                             value=int(r.consecutive_b), step=1))

    st.subheader("Specified rerates by duration")
    st.caption("Durations 1–2 are always used; the rest are used when solving is off.")
    rdf = pd.DataFrame({"Rerate": r.specified_rerates},
                       index=range(1, len(r.specified_rerates) + 1))
    red = st.data_editor(rdf, use_container_width=True, height=300, key="spec_rerate")
    r.specified_rerates = red["Rerate"].tolist()


def _distribution(asm) -> None:
    import pandas as pd
    from medigap_engine.models.cell import CellKey, PricingCell

    st.subheader("Distribution of business — per-cell weights & premiums")
    st.caption("Every pricing cell's distribution weight and base premium is an input. "
               "Edit directly, or adopt from the Experience Study (Sales) tab. Weights "
               "are re-normalised when the model runs.")
    cells = st.session_state.cells
    df = pd.DataFrame([{
        "Issue age": c.key.issue_age, "Gender": c.key.gender, "Plan": c.key.plan,
        "UW": c.key.uw_class, "Pref": c.key.preferred, "HHD": c.key.hhd,
        "Weight": c.weight, "Base premium": c.base_prem,
    } for c in cells])
    edited = st.data_editor(
        df, use_container_width=True, height=420, key="cells_editor",
        disabled=["Issue age", "Gender", "Plan", "UW", "Pref", "HHD"])
    total_w = float(edited["Weight"].sum())
    st.caption(f"Weights sum to {total_w:.4f} (re-normalised to 1 at run time).")
    # write edits back, preserving per-state premium overrides
    new_cells = []
    for orig, (_, row) in zip(cells, edited.iterrows()):
        key = CellKey(issue_age=int(row["Issue age"]), gender=row["Gender"],
                      plan=row["Plan"], uw_class=row["UW"],
                      preferred=row["Pref"], hhd=row["HHD"])
        new_cells.append(PricingCell(
            key=key, base_prem=float(row["Base premium"]), weight=float(row["Weight"]),
            state_premiums=orig.state_premiums))
    st.session_state.cells = new_cells


def _termination(asm) -> None:
    t = asm.termination
    st.subheader("Base lapse rates by duration and UW class")
    ldf = pd.DataFrame(t.base_lapse, index=range(1, PROJECTION_YEARS + 1))
    led = st.data_editor(ldf, use_container_width=True, height=320, key="lapse")
    for k in t.base_lapse:
        if k in led:
            t.base_lapse[k] = led[k].tolist()

    st.subheader("Termination duration scaling")
    c = st.columns(2)
    t.dur2_scaling = c[0].number_input("Duration 2 scaling", value=float(t.dur2_scaling),
                                       step=0.01, format="%.3f")
    t.dur3plus_scaling = c[1].number_input("Duration 3+ scaling", value=float(t.dur3plus_scaling),
                                           step=0.01, format="%.3f")

    st.subheader("Mortality table")
    mdf = pd.DataFrame({"Age": t.mort_age, "qx": t.mort_qx})
    st.dataframe(mdf, hide_index=True, use_container_width=True, height=240)


def _commission(asm) -> None:
    c = asm.commission
    st.subheader("Commission rate by state and duration")
    cdf = pd.DataFrame(c.by_state, index=range(1, PROJECTION_YEARS + 1))
    ced = st.data_editor(cdf, use_container_width=True, height=320, key="comm")
    for k in list(c.by_state.keys()):
        if k in ced:
            c.by_state[k] = ced[k].tolist()
    cc = st.columns(3)
    c.gi_flat = cc[0].number_input("GI flat commission", value=float(c.gi_flat), step=1.0)
    c.plan_f_offset = cc[1].number_input("Plan F premium offset", value=float(c.plan_f_offset),
                                         step=10.0)
    c.age80_halving = cc[2].toggle("Halve commission for issue age ≥ 80",
                                   value=c.age80_halving)


def _other(asm) -> None:
    o = asm.other
    st.subheader("Other assumptions")
    fields = [
        ("discount_rate", "Discount rate"),
        ("premium_tax", "Premium tax"),
        ("oper_acq", "Operating acquisition ($)"),
        ("marketing_acq", "Marketing acquisition ($)"),
        ("maintenance", "Maintenance ($)"),
        ("inflation", "Inflation"),
        ("rbc_factor", "RBC factor"),
        ("covariance", "Covariance"),
        ("rbc_pct_of_prem", "RBC as % of premium"),
        ("nier", "NIER (investment return)"),
        ("tax_rate", "Tax rate"),
        ("ibnr_pct", "IBNR as % of claims"),
    ]
    cols = st.columns(3)
    for i, (key, label) in enumerate(fields):
        val = float(getattr(o, key))
        new = cols[i % 3].number_input(label, value=val, format="%.4f")
        setattr(o, key, new)
