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


def _dict_editor(d, value_label, key, fmt="%.6f"):
    """Edit a {label: float} mapping as a one-column table; return the updated dict
    preserving the original key types."""
    types = {k: type(k) for k in d}
    df = pd.DataFrame({value_label: d})
    ed = st.data_editor(
        df, use_container_width=True, key=key,
        column_config={value_label: st.column_config.NumberColumn(format=fmt)})
    out = {}
    for idx, v in ed[value_label].items():
        cast = types.get(idx, type(idx))
        out[cast(idx) if cast in (int, float, str) else idx] = float(v)
    return out


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
        "Morbidity", "Premium", "Rerates", "Distribution",
        "Termination", "Commission", "Economic assumptions",
    ])
    with sub[0]:
        _morbidity(asm)
    with sub[1]:
        _premium(asm)
    with sub[2]:
        _rerates(asm)
    with sub[3]:
        _distribution(asm)
    with sub[4]:
        _termination(asm)
    with sub[5]:
        _commission(asm)
    with sub[6]:
        _economic(asm)


def _morbidity(asm) -> None:
    from medigap_engine.models.assumptions import derive_two_level, normalized_factors

    m = asm.morbidity
    st.subheader("Base claim costs by plan and attained age")
    st.caption("Base table is the gender blend; the gender relativity (normalised by the "
               "gender mix) sends male up and female down while preserving the blend.")
    dfb = pd.DataFrame(m.base_cc, index=m.ages)
    edb = st.data_editor(dfb, use_container_width=True, height=300, key="cc_base")
    for p in m.plans:
        if p in edb:
            m.base_cc[p] = edb[p].tolist()
    st.markdown("**Gender claim-cost relativity** (e.g. M = 1.15 means male 15% above female)")
    m.gender_cc_rel = _dict_editor(m.gender_cc_rel, "Relativity", "cc_gender", fmt="%.4f")
    gf = normalized_factors(m.gender_cc_rel, asm.distribution.gender)
    st.caption("→ derived factors: " + ", ".join(f"{k} = {v:.5f}" for k, v in gf.items()))

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
    m.state_factors = _dict_editor(m.state_factors, "Factor", "state_factors", fmt="%.5f")

    st.subheader("Household & preferred claim differentials")
    st.caption("Enter how much higher the 'No' level is than the 'Yes' level. The Y/N "
               "factors are derived so the distribution-weighted mean stays 1 (the base "
               "claim cost already carries the blend).")
    c = st.columns(2)
    with c[0]:
        m.preferred_diff = st.number_input(
            "Non-preferred is higher than preferred by", value=float(m.preferred_diff),
            step=0.01, format="%.3f", help="Applied for UW class only.")
        pf = derive_two_level(asm.distribution.preferred.get("Y", 0.5), m.preferred_diff)
        st.caption(f"→ derived factors: Y = {pf['Y']:.5f}, N = {pf['N']:.5f}")
    with c[1]:
        m.hhd_diff = st.number_input(
            "Non-HHD is higher than HHD by", value=float(m.hhd_diff),
            step=0.01, format="%.3f")
        hf = derive_two_level(asm.distribution.hhd.get("Y", 0.5), m.hhd_diff)
        st.caption(f"→ derived factors: Y = {hf['Y']:.5f}, N = {hf['N']:.5f}")

    st.subheader("Claim-cost aging by duration")
    st.caption("Incremental aging added to the antiselection (column P) recurrence each "
               "duration; varies by year.")
    adf = pd.DataFrame({"Aging": m.cc_aging_by_duration},
                       index=range(1, len(m.cc_aging_by_duration) + 1))
    aed = st.data_editor(adf, use_container_width=True, height=300, key="cc_aging",
                         column_config={"Aging": st.column_config.NumberColumn(format="%.4f")})
    m.cc_aging_by_duration = aed["Aging"].tolist()
    st.caption("Selection (antiselection) factors remain read-only here for now.")


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


def _premium(asm) -> None:
    from medigap_engine.models.assumptions import normalized_factors

    p = asm.premium
    d = asm.distribution
    st.subheader("Premium = base (blend at plan G) × relativities")
    st.caption("Enter relativities (how much premium goes up/down). Gender/preferred/hhd/uw "
               "are normalised by the business mix so the blend is preserved; PLAN is anchored "
               "at G = 1.00 (F/N relative to G). State is a raw factor.")
    st.markdown("**Base premium by issue age** (plan-G blend)")
    p.base_by_issue_age = _dict_editor(p.base_by_issue_age, "Base premium",
                                       "prem_base", fmt="%.2f")

    def _rel_block(label, rel, weights, key, normalize=True):
        st.markdown(f"**{label}**")
        new = _dict_editor(rel, "Relativity", key)
        if normalize:
            fac = normalized_factors(new, weights)
            st.caption("→ factors: " + ", ".join(f"{k} = {v:.4f}" for k, v in fac.items()))
        else:
            st.caption("→ factors = relativities (G anchored at 1.00)")
        return new

    cols = st.columns(3)
    with cols[0]:
        p.plan_rel = _rel_block("Plan (G = 1.00)", p.plan_rel, d.plan, "prem_plan",
                                normalize=False)
        p.preferred_rel = _rel_block("Preferred", p.preferred_rel, d.preferred, "prem_pref")
    with cols[1]:
        p.gender_rel = _rel_block("Gender", p.gender_rel, d.gender, "prem_gender")
        p.hhd_rel = _rel_block("HHD", p.hhd_rel, d.hhd, "prem_hhd")
    with cols[2]:
        p.uw_rel = _rel_block("UW", p.uw_rel, d.uw, "prem_uw")
    st.markdown("**State factor** (raw)")
    p.state_factor = _dict_editor(p.state_factor, "Factor", "prem_state")


def _distribution(asm) -> None:
    d = asm.distribution
    st.subheader("Distribution weight factors")
    st.caption("Each dimension's weights should sum to 1; a cell's weight is the "
               "product across dimensions. Re-normalised at run time.")

    def _dim(label, mapping, key):
        new = _dict_editor(mapping, "Weight", key, fmt="%.5f")
        st.caption(f"{label} sums to {sum(new.values()):.4f}")
        return new

    st.markdown("**By issue age**")
    d.by_issue_age = _dim("Issue age", d.by_issue_age, "w_age")
    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Gender**"); d.gender = _dim("Gender", d.gender, "w_gender")
        st.markdown("**Preferred**"); d.preferred = _dim("Preferred", d.preferred, "w_pref")
    with cols[1]:
        st.markdown("**Plan**"); d.plan = _dim("Plan", d.plan, "w_plan")
        st.markdown("**HHD**"); d.hhd = _dim("HHD", d.hhd, "w_hhd")
    with cols[2]:
        st.markdown("**UW**"); d.uw = _dim("UW", d.uw, "w_uw")


def _termination(asm) -> None:
    from medigap_engine.models.assumptions import normalized_factors

    t = asm.termination
    st.subheader("Base lapse (blend) and UW relativity by duration")
    st.caption("Base lapse is the uw-mix blend. UW relativity (e.g. 1.5 = UW 1.5× as likely to "
               "lapse as other) is normalised by the uw mix, so the applied UW factor is below "
               "the relativity (the blend already includes UW exposure).")
    ldf = pd.DataFrame(
        {"Base lapse (blend)": t.base_lapse, "UW relativity": t.uw_lapse_rel},
        index=range(1, PROJECTION_YEARS + 1))
    led = st.data_editor(
        ldf, use_container_width=True, height=320, key="lapse",
        column_config={
            "Base lapse (blend)": st.column_config.NumberColumn(format="%.5f"),
            "UW relativity": st.column_config.NumberColumn(format="%.4f"),
        })
    t.base_lapse = led["Base lapse (blend)"].tolist()
    t.uw_lapse_rel = led["UW relativity"].tolist()
    fac = normalized_factors({"UW": t.uw_lapse_rel[0], "OE": 1.0, "GI": 1.0}, asm.distribution.uw)
    st.caption(f"→ duration-1 applied factors: UW = {fac['UW']:.4f}, other = {fac['OE']:.4f}")

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


def _economic(asm) -> None:
    o = asm.other
    st.subheader("Economic assumptions")
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
