"""Assumptions tab with six subtabs. Editable scalars and tables write back to
the AssumptionSet held in session state. Supports JSON download/upload so
configurations persist without a server."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import (
    assumptions_json,
    assumptions_xlsx,
    get_assumptions,
    load_assumptions_json,
    load_assumptions_xlsx,
    reset_assumptions,
    solve_toggle,
)
from medigap_engine.io.defaults import available_states
from medigap_engine.models.assumptions import PROJECTION_YEARS

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    top = st.columns([1, 1, 1, 2])
    with top[0]:
        st.download_button("Download JSON", assumptions_json(),
                           "assumptions.json", "application/json", key="asm_download")
    with top[1]:
        st.download_button("Download Excel", assumptions_xlsx(),
                           "assumptions.xlsx", _XLSX_MIME, key="asm_xlsx_download",
                           help="All assumptions plus the engine's derived factors, "
                           "one sheet per category — for verifying the model in Excel.")
    with top[2]:
        if st.button("Reset to defaults", key="asm_reset"):
            reset_assumptions()
            st.rerun()
    with top[3]:
        up = st.file_uploader("Upload assumptions (JSON or Excel)", type=["json", "xlsx"],
                              key="asm_upload")
        if up is not None:
            try:
                if up.name.lower().endswith(".xlsx"):
                    load_assumptions_xlsx(up.getvalue())
                else:
                    load_assumptions_json(up.getvalue().decode("utf-8"))
                st.success("Assumptions loaded.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not load assumptions: {exc}")

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
    st.subheader("Base claim costs by plan and issue age")
    st.caption("Claim base cost is indexed by **issue age** (held across durations; "
               "duration effects come from trend, selection and antiselection), so only "
               "the issue ages the book prices appear here. The base table is the gender "
               "blend; the gender relativity (normalised by the gender mix) sends male up "
               "and female down while preserving the blend.")
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

    st.subheader("UW selection factors")
    st.caption("Multiplier on base claim cost by (issue age, UW class, duration), referenced "
               "to OE / duration-1 = 1.0 (claim = base_cc × selection). Edited per UW class "
               "as an issue-age × duration grid; carried forward beyond the last duration.")
    rows = m.selection_factors
    issue_ages = sorted({r["issue_age"] for r in rows})
    durs = sorted({r["duration"] for r in rows})
    lookup = {(r["issue_age"], r["uw"], r["duration"]): r["factor"] for r in rows}
    uw_pick = st.radio("UW class", ["UW", "OE", "GI"], horizontal=True, key="sel_uw_pick")
    sdf = pd.DataFrame(
        {f"d{d}": [float(lookup.get((a, uw_pick, d), 1.0)) for a in issue_ages] for d in durs},
        index=issue_ages)
    sed = st.data_editor(
        sdf, use_container_width=True, key=f"sel_grid_{uw_pick}",
        column_config={f"d{d}": st.column_config.NumberColumn(format="%.4f") for d in durs})
    for r in rows:
        if r["uw"] == uw_pick and f"d{r['duration']}" in sed.columns:
            r["factor"] = float(sed.loc[r["issue_age"], f"d{r['duration']}"])


def _rerates(asm) -> None:
    r = asm.rerates
    st.subheader("Rerate strategy")
    solve_toggle("rr_solve", "Solve rerates to hit target lifetime loss ratio",
                 help="Linked to the Run toggle on the Configuration tab.")
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
    st.info(
        "**The duration-1 rerate applies in the first projection year** — first-year earned "
        "premium = base premium × (1 + rerate₁). Use it to load a known upcoming rate increase "
        "that isn't in the experience data. Durations 1–2 are always used (even when solving "
        "is on); durations 3+ are used only when solving is off."
    )
    rdf = pd.DataFrame({"Rerate": r.specified_rerates},
                       index=range(1, len(r.specified_rerates) + 1))
    red = st.data_editor(rdf, use_container_width=True, height=300, key="spec_rerate")
    r.specified_rerates = red["Rerate"].tolist()

    states = [s for s in available_states() if s != "All"]

    st.markdown("**Per-state rerate overrides** — grid of duration (rows) × state (columns)")
    st.caption("Select the states to override; each starts from the shared schedule above. "
               "Edit a column to set that state's rerate by duration; deselect to remove the "
               "override. States without an override use the shared schedule.")
    rr_states = st.multiselect("States with a rerate override", states,
                               default=sorted(r.by_state), key="rr_ovr_states")
    for s in rr_states:
        r.by_state.setdefault(s, list(r.specified_rerates))
    for s in [s for s in r.by_state if s not in rr_states]:
        del r.by_state[s]
    if rr_states:
        gdf = pd.DataFrame({s: r.by_state[s] for s in rr_states},
                           index=range(1, PROJECTION_YEARS + 1))
        ged = st.data_editor(gdf, use_container_width=True, height=320, key="rr_grid",
                             column_config={s: st.column_config.NumberColumn(format="%.4f")
                                            for s in rr_states})
        for s in rr_states:
            if s in ged:
                r.by_state[s] = ged[s].tolist()

    st.markdown("**Per-state target lifetime loss ratio** — overrides the shared target above")
    st.caption("The rerate solver targets this lifetime LR for the state; unlisted states use "
               "the shared target.")
    tgt_states = st.multiselect("States with a target-LR override", states,
                                default=sorted(r.target_lifetime_lr_by_state), key="rr_tgt_states")
    for s in tgt_states:
        r.target_lifetime_lr_by_state.setdefault(s, float(r.target_lifetime_lr))
    for s in [s for s in r.target_lifetime_lr_by_state if s not in tgt_states]:
        del r.target_lifetime_lr_by_state[s]
    if tgt_states:
        tdf = pd.DataFrame({"Target lifetime LR": [r.target_lifetime_lr_by_state[s] for s in tgt_states]},
                           index=tgt_states)
        ted = st.data_editor(tdf, use_container_width=True, key="rr_tgt_grid",
                             column_config={"Target lifetime LR":
                                            st.column_config.NumberColumn(format="%.3f")})
        for s in tgt_states:
            r.target_lifetime_lr_by_state[s] = float(ted.loc[s, "Target lifetime LR"])


def _premium(asm) -> None:
    from medigap_engine.models.assumptions import normalized_factors

    p = asm.premium
    d = asm.distribution
    st.subheader("Premium factor model")
    st.caption("Used when a cell has no per-cell premium below. Relativities say how much "
               "premium goes up/down; gender/preferred/hhd/uw are normalised by the business "
               "mix so the blend is preserved; PLAN is anchored at G = 1.00. State is raw.")

    def _diff(label, value, high, low, weights, key):
        v = st.number_input(label, value=float(value), step=0.01, format="%.3f", key=key)
        fac = normalized_factors({high: 1.0 + v, low: 1.0}, weights)
        st.caption(f"→ factors: {high} = {fac[high]:.4f}, {low} = {fac[low]:.4f}")
        return v

    # Row 1 — differentials (consistent heights, each with its derived factors)
    st.markdown("**Relativity differentials**")
    dc = st.columns(3)
    with dc[0]:
        p.gender_diff = _diff("Male premium higher than female by", p.gender_diff,
                              "M", "F", d.gender, "prem_gender")
    with dc[1]:
        p.preferred_diff = _diff("Non-preferred premium higher by", p.preferred_diff,
                                 "N", "Y", d.preferred, "prem_pref")
    with dc[2]:
        p.hhd_diff = _diff("Non-HHD premium higher by", p.hhd_diff,
                           "N", "Y", d.hhd, "prem_hhd")

    # Row 2 — base-by-age, plan/uw and state-factor tables (equal-height columns)
    tc = st.columns([2, 1, 1])
    with tc[0]:
        st.markdown("**Base premium by issue age** (plan-G blend)")
        p.base_by_issue_age = _dict_editor(p.base_by_issue_age, "Base premium",
                                           "prem_base", fmt="%.2f")
    with tc[1]:
        st.markdown("**Plan rel. (G=1.00)**")
        p.plan_rel = _dict_editor(p.plan_rel, "Relativity", "prem_plan")
        st.markdown("**UW relativities**")
        p.uw_rel = _dict_editor(p.uw_rel, "Relativity", "prem_uw")
        ufac = normalized_factors(p.uw_rel, d.uw)
        st.caption("→ " + ", ".join(f"{k} = {v:.4f}" for k, v in ufac.items()))
    with tc[2]:
        st.markdown("**State factor** (raw)")
        p.state_factor = _dict_editor(p.state_factor, "Factor", "prem_state")
    st.caption("The one-time pull-forward of current premium to the pricing period is set "
               "on the Pull forward tab; future premium changes are driven by the rerate solver.")

    _cell_premiums(p)


def _cell_premiums(p) -> None:
    """Per-cell premiums (exact rates from the workbook Input sheet) override the factor
    model above; surfaced read/edit one state at a time."""
    st.divider()
    st.markdown("**Per-cell premiums** — exact rates that override the factor model")
    cp = p.cell_premiums
    if not cp:
        st.caption("None loaded — the factor model above is used for every cell. Per-cell "
                   "premiums are populated from the workbook Input sheet by "
                   "`tools/generate_seed.py`.")
        return
    states = sorted({s for m in cp.values() for s in m})
    st.caption(f"{len(cp)} cells × {len(states)} states loaded. When a cell+state is present "
               "here it is used verbatim (no pull-forward), overriding the factor model. "
               "Edit one state at a time below.")
    left, right = st.columns([1, 3])
    with left:
        default_ix = states.index("TX") if "TX" in states else 0
        sel = st.selectbox("State", states, index=default_ix, key="prem_cell_state")
        if st.button("Clear per-cell premiums", key="prem_cell_clear",
                     help="Drop all per-cell premiums and fall back to the factor model."):
            p.cell_premiums = {}
            st.rerun()
    with right:
        col = f"Premium ({sel})"
        df = pd.DataFrame({col: {label: m.get(sel) for label, m in cp.items()}})
        ed = st.data_editor(
            df, use_container_width=True, height=360, key=f"prem_cell_editor_{sel}",
            column_config={col: st.column_config.NumberColumn(format="%.2f")})
        for label, v in ed[col].items():
            if v is not None and not pd.isna(v):
                cp.setdefault(label, {})[sel] = float(v)


def _edit_joint_grid(joint, ages, uws, key_prefix) -> float:
    """Render/edit a joint plan×age×UW grid in place; return the grand total weight."""
    grand = 0.0
    for pl in list(joint) or sorted({p for p in joint}):
        st.markdown(f"**Plan {pl}** — weight by issue age (rows) × UW class (columns)")
        grid = joint.setdefault(pl, {})
        df = pd.DataFrame(
            {u: [float(grid.get(str(a), {}).get(u, 0.0)) for a in ages] for u in uws},
            index=ages)
        ed = st.data_editor(
            df, use_container_width=True, key=f"{key_prefix}_{pl}",
            column_config={u: st.column_config.NumberColumn(format="%.5f") for u in uws})
        sub = 0.0
        for u in uws:
            col = ed[u].tolist()
            for i, a in enumerate(ages):
                w = float(col[i])
                grid.setdefault(str(a), {})[u] = w
                sub += w
        grand += sub
        st.caption(f"Plan {pl} subtotal: {sub:.4f}")
    return grand


def _edit_marginals(block, key_prefix) -> None:
    """Render/edit gender/preferred/hhd marginals on a dict-like block in place. ``block``
    may be the AssumptionSet.distribution or a by_state dict."""
    def _marg(label, mapping, key):
        new = _dict_editor(mapping, "Weight", key, fmt="%.5f")
        st.caption(f"{label} sums to {sum(new.values()):.4f}")
        return new

    cols = st.columns(3)
    getter = (lambda k: block[k]) if isinstance(block, dict) else (lambda k: getattr(block, k))
    setter = (block.__setitem__) if isinstance(block, dict) else (
        lambda k, v: setattr(block, k, v))
    with cols[0]:
        st.markdown("**Gender**")
        setter("gender", _marg("Gender", getter("gender"), f"{key_prefix}_gender"))
    with cols[1]:
        st.markdown("**Preferred**")
        setter("preferred", _marg("Preferred", getter("preferred"), f"{key_prefix}_pref"))
    with cols[2]:
        st.markdown("**HHD**")
        setter("hhd", _marg("HHD", getter("hhd"), f"{key_prefix}_hhd"))


def _distribution(asm) -> None:
    d = asm.distribution
    st.subheader("Distribution weight grid (national)")
    st.caption(
        "Plan × issue age × UW is a single **joint** weight grid (the mix varies "
        "together and is not separable). Gender, preferred and household-discount are "
        "independent marginals applied on top. The whole grid and each marginal should "
        "sum to 1; a cell's weight is grid[plan, age, uw] × gender × preferred × hhd "
        "(re-normalised at run time)."
    )
    ages = sorted(d.by_issue_age)
    uws = list(d.uw)
    grand = _edit_joint_grid(d.joint, ages, uws, "dist_grid")
    st.caption(f"**Grid total across all plans: {grand:.4f}** (should be ~1.0)")
    _edit_marginals(d, "w")

    st.subheader("Special Enrollment Period (SEP) states")
    st.caption("Mark each state Yes/No. SEP states have a different UW mix (skew to "
               "open-enrolment); the experience study blends each state's distribution "
               "toward the average of its like type.")
    all_states = [s for s in available_states() if s != "All"]
    sep = set(d.sep_rule_states or [])
    sdf = pd.DataFrame({"sep_rule": [s in sep for s in all_states]}, index=all_states)
    sed = st.data_editor(
        sdf, use_container_width=True, height=320, key="dist_sep_rule",
        column_config={"sep_rule": st.column_config.CheckboxColumn("SEP state?")})
    d.sep_rule_states = [s for s in all_states if bool(sed["sep_rule"].get(s, False))]

    st.subheader("Per-state distribution overrides")
    st.caption("States with an override price from their own grid (GI/OE/UW & plan mix vary "
               "by state); states without one use the national grid above. Overrides are "
               "populated by adopting sales experience, or initialise one from national here.")
    state = st.selectbox("State", all_states, key="dist_state_pick")
    has = state in d.by_state and d.by_state[state].get("joint")
    if not has:
        st.info(f"{state} has no override — it uses the national grid.")
        if st.button(f"Initialize {state} from national", key="dist_state_init"):
            import copy as _copy
            d.by_state[state] = {
                "joint": _copy.deepcopy(d.joint), "gender": dict(d.gender),
                "preferred": dict(d.preferred), "hhd": dict(d.hhd)}
            st.rerun()
    else:
        sd = d.by_state[state]
        sd.setdefault("joint", {})
        for dim, src in (("gender", d.gender), ("preferred", d.preferred), ("hhd", d.hhd)):
            sd.setdefault(dim, dict(src))
        sg = _edit_joint_grid(sd["joint"], ages, uws, f"dist_state_grid_{state}")
        st.caption(f"**{state} grid total: {sg:.4f}** (should be ~1.0)")
        _edit_marginals(sd, f"dist_state_marg_{state}")
        if st.button(f"Remove {state} override (revert to national)", key="dist_state_del"):
            d.by_state.pop(state, None)
            st.rerun()


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

    st.subheader("State lapse factors")
    st.caption("A per-state multiplier on the lapse rate (1.0 = national). Applied as "
               "lapse × state factor when pricing that state.")
    t.state_factors = _dict_editor(t.state_factors, "Lapse factor", "term_state", fmt="%.4f")

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
                                   value=c.age80_halving, key="comm_age80")


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
