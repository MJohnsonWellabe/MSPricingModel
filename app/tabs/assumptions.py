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
        "Pull forward", "Distribution", "Premium", "Rerates",
        "Termination", "Morbidity", "Commission", "Economic assumptions",
    ])
    with sub[0]:
        _pull_forward(asm)
    with sub[1]:
        _distribution(asm)
    with sub[2]:
        _premium(asm)
    with sub[3]:
        _rerates(asm)
    with sub[4]:
        _termination(asm)
    with sub[5]:
        _morbidity(asm)
    with sub[6]:
        _commission(asm)
    with sub[7]:
        _economic(asm)


def _pull_forward(asm) -> None:
    pf = asm.pull_forward
    st.subheader("Pull experience forward to the pricing period")
    st.caption(
        "Current (experience-period) base claims and base premium are brought forward "
        "to the pricing period by a one-time factor (1 + trend) ^ duration. The "
        "pulled-forward level is the year-1 level; the year-by-year claims trend on the "
        "Morbidity tab then compounds from year 1 onward. The pull-forward claims trend "
        "need not equal the year-1 projection trend."
    )
    c = st.columns(3)
    pf.duration = c[0].number_input(
        "Duration (years to pull forward)", value=float(pf.duration), step=0.05,
        format="%.2f", help="Years from the experience period to the pricing period "
        "(was the hard-coded 1.75 trend exponent).")
    pf.claims_trend = c[1].number_input(
        "Claims trend (pull-forward)", value=float(pf.claims_trend), step=0.01,
        format="%.3f")
    pf.premium_trend = c[2].number_input(
        "Premium trend (pull-forward)", value=float(pf.premium_trend), step=0.01,
        format="%.3f")
    st.caption(
        f"→ claims bring-forward factor: (1 + {pf.claims_trend:.3f})^{pf.duration:.2f} = "
        f"{(1.0 + pf.claims_trend) ** pf.duration:.5f}  |  "
        f"premium bring-forward factor: (1 + {pf.premium_trend:.3f})^{pf.duration:.2f} = "
        f"{(1.0 + pf.premium_trend) ** pf.duration:.5f}")


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
    m.gender_cc_diff = st.number_input(
        "Male claim cost is higher than female by", value=float(m.gender_cc_diff),
        step=0.01, format="%.3f")
    gf = normalized_factors({"M": 1.0 + m.gender_cc_diff, "F": 1.0}, asm.distribution.gender)
    st.caption(f"→ derived factors: M = {gf['M']:.5f}, F = {gf['F']:.5f}")

    st.subheader("Projection trend by duration year")
    st.caption("Year-by-year claims trend, compounding from year 1 onward. The "
               "one-time pull-forward of current claims to the pricing period is set "
               "on the Pull forward tab.")
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

    def _diff(label, value, high, low, weights, key):
        v = st.number_input(label, value=float(value), step=0.01, format="%.3f", key=key)
        fac = normalized_factors({high: 1.0 + v, low: 1.0}, weights)
        st.caption(f"→ factors: {high} = {fac[high]:.4f}, {low} = {fac[low]:.4f}")
        return v

    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Plan relativities (G = 1.00)**")
        p.plan_rel = _dict_editor(p.plan_rel, "Relativity", "prem_plan")
        p.preferred_diff = _diff("Non-preferred premium higher by", p.preferred_diff,
                                 "N", "Y", d.preferred, "prem_pref")
    with cols[1]:
        p.gender_diff = _diff("Male premium higher than female by", p.gender_diff,
                              "M", "F", d.gender, "prem_gender")
        p.hhd_diff = _diff("Non-HHD premium higher by", p.hhd_diff,
                           "N", "Y", d.hhd, "prem_hhd")
    with cols[2]:
        st.markdown("**UW relativities**")
        p.uw_rel = _dict_editor(p.uw_rel, "Relativity", "prem_uw")
        ufac = normalized_factors(p.uw_rel, d.uw)
        st.caption("→ factors: " + ", ".join(f"{k} = {v:.4f}" for k, v in ufac.items()))
    st.markdown("**State factor** (raw)")
    p.state_factor = _dict_editor(p.state_factor, "Factor", "prem_state")
    st.caption("The one-time pull-forward of current premium to the pricing period is "
               "set on the Pull forward tab; future premium changes are driven by the "
               "rerate solver.")


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

    def _group(title, fields):
        st.markdown(f"**{title}**")
        cols = st.columns(3)
        for i, (key, label) in enumerate(fields):
            new = cols[i % 3].number_input(label, value=float(getattr(o, key)),
                                           format="%.4f", key=f"econ_{key}")
            setattr(o, key, new)

    _group("Discounting & investment", [
        ("discount_rate", "Discount rate"),
        ("nier", "NIER (investment return)"),
        ("inflation", "Inflation"),
    ])
    _group("Per-policy expenses ($)", [
        ("oper_acq", "Operating acquisition ($)"),
        ("marketing_acq", "Marketing acquisition ($)"),
        ("maintenance", "Maintenance ($)"),
    ])
    _group("Taxes & loadings", [
        ("premium_tax", "Premium tax"),
        ("tax_rate", "Tax rate"),
        ("ibnr_pct", "IBNR as % of claims"),
    ])
    _group("Capital (RBC)", [
        ("rbc_pct_of_prem", "RBC as % of premium"),
        ("rbc_factor", "RBC factor"),
        ("covariance", "Covariance"),
    ])
