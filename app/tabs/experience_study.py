"""Experience Study tab.

Upload raw sales and claims CSVs (or load the bundled samples), derive
distribution/premium and morbidity assumptions, adopt them, and run
actual-to-expected analysis.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from app.state import get_assumptions
from medigap_engine.experience.ae import actual_to_expected
from medigap_engine.experience.claims import derive_morbidity
from medigap_engine.experience.credibility import blend, credibility_z
from medigap_engine.experience.port import apply_claims, apply_sales
from medigap_engine.experience.sales import aggregate_sales
from medigap_engine.experience.schema import SALES_COLUMNS, CLAIMS_COLUMNS
from medigap_engine.io.defaults import load_template_csv


def _read_csv_to_records(text: str) -> list[dict]:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    return df.to_dict("records")


def _factor_df(mapping: dict, value_label: str) -> pd.DataFrame:
    """Render a {label: float} mapping as a one-column table (sorted by key)."""
    items = sorted(mapping.items(), key=lambda kv: kv[0])
    return pd.DataFrame({value_label: {str(k): round(float(v), 5) for k, v in items}})


def render() -> None:
    st.header("Experience Study")
    st.caption(
        "Load raw sales and claims data to derive assumptions. Nothing changes "
        "your model until you click an **Adopt** button."
    )
    study, claims_tab, ae = st.tabs(["Sales → distribution & premiums",
                                     "Claims → morbidity", "AE Analysis"])
    with study:
        _sales_section()
    with claims_tab:
        _claims_section()
    with ae:
        _ae_section()


def _sales_section() -> None:
    st.subheader("Sales data")
    c = st.columns([1, 1, 2])
    c[0].download_button("Download template", load_template_csv("sales_template.csv"),
                         "sales_template.csv", "text/csv", key="sales_template_dl")
    if c[1].button("Load sample data", key="load_sales_sample"):
        st.session_state["sales_text"] = load_template_csv("sales_sample.csv")
    up = st.file_uploader("Upload sales CSV", type=["csv"], key="sales_upload")
    if up is not None:
        st.session_state["sales_text"] = up.getvalue().decode("utf-8")

    st.caption("Expected columns: " + ", ".join(SALES_COLUMNS))
    text = st.session_state.get("sales_text")
    if not text:
        return
    try:
        records = _read_csv_to_records(text)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse CSV: {exc}")
        return
    agg = aggregate_sales(records)
    st.success(f"Parsed {agg['n_rows']:,} usable rows / {agg['total_count']:,.0f} applications.")

    # Preview the *factors* the data suggests — exactly what Adopt will write —
    # rather than the full 432-cell weight grid.
    suggested = apply_sales(get_assumptions(), agg)
    d = suggested.distribution
    p = suggested.premium
    cur = get_assumptions()

    st.markdown("#### Suggested distribution — joint plan × issue-age × UW grid")
    st.caption("This is the same joint grid the model prices with (F/G/N split by issue "
               "age and UW mix), fit from the data. UW mix also varies by state (below).")
    grid_rows = {}
    for plan, ag in d.joint.items():
        for a, uws in ag.items():
            r = grid_rows.setdefault(int(a), {})
            for u, w in uws.items():
                r[f"{plan}-{u}"] = round(w, 4)
    st.dataframe(pd.DataFrame(grid_rows).T.sort_index().fillna(0.0),
                 use_container_width=True, height=240)

    if d.by_state:
        sep = set(d.sep_rule_states or [])
        st.markdown("**UW mix by state** (GI / OE / UW share) — blended toward the "
                    "like-type (separate-rule vs regular) average by sales volume")
        st.caption("Each state's grid is its own sales mix credibility-blended toward the "
                   "average of its type. Separate-rule states (editable on the Distribution "
                   "assumptions tab) skew to open-enrolment; regular states skew underwritten. "
                   "The full state/age/plan/UW grid is the joint grid above scaled to each "
                   "state's mix.")
        mix_rows = {}
        for s in sorted(d.by_state):
            uw = d.uw_mix(s)
            tot = sum(uw.values()) or 1.0
            row = {u: round(uw.get(u, 0.0) / tot, 3) for u in ("GI", "OE", "UW")}
            row["type"] = "sep-rule" if s in sep else "regular"
            mix_rows[s] = row
        st.dataframe(pd.DataFrame(mix_rows).T, use_container_width=True, height=300)
        pick = st.selectbox("Inspect a state's full plan × age × UW grid",
                            sorted(d.by_state), key="sales_state_pick")
        sd = d.by_state[pick]
        gr = {}
        for plan, ag in sd.get("joint", {}).items():
            for a, uws in ag.items():
                rr = gr.setdefault(int(a), {})
                for u, w in uws.items():
                    rr[f"{plan}-{u}"] = round(w, 4)
        st.dataframe(pd.DataFrame(gr).T.sort_index().fillna(0.0),
                     use_container_width=True, height=220)

    st.markdown("#### Suggested premium factors — current vs suggested")
    st.caption("Differentials are isolated by a multivariate fit (each holds the others "
               "fixed) and are editable before adopting.")
    cp = cur.premium
    st.dataframe(pd.DataFrame({
        "current base": {int(a): round(v) for a, v in sorted(cp.base_by_issue_age.items())},
        "suggested base": {int(a): round(v) for a, v in sorted(p.base_by_issue_age.items())},
    }), use_container_width=True, height=240)
    pc = st.columns(3)
    with pc[0]:
        st.markdown("**Plan rel (cur → sugg)**")
        st.dataframe(pd.DataFrame({
            "current": {k: round(cp.plan_rel.get(k, 1.0), 3) for k in p.plan_rel},
            "suggested": {k: round(v, 3) for k, v in p.plan_rel.items()}}),
            use_container_width=True)
        p.gender_diff = st.number_input(
            f"Gender diff (cur {cp.gender_diff*100:.1f}%)", value=float(p.gender_diff),
            step=0.01, format="%.3f", key="sales_gender_diff")
    with pc[1]:
        st.markdown("**UW rel (cur → sugg)**")
        st.dataframe(pd.DataFrame({
            "current": {k: round(cp.uw_rel.get(k, 1.0), 3) for k in p.uw_rel},
            "suggested": {k: round(v, 3) for k, v in p.uw_rel.items()}}),
            use_container_width=True)
        p.preferred_diff = st.number_input(
            f"Non-preferred diff (cur {cp.preferred_diff*100:.1f}%)",
            value=float(p.preferred_diff), step=0.01, format="%.3f", key="sales_pref_diff")
    with pc[2]:
        st.markdown("**State factor (cur → sugg)**")
        st.dataframe(pd.DataFrame({
            "current": {s: round(cp.state_factor.get(s, 1.0), 3) for s in sorted(p.state_factor)},
            "suggested": {s: round(v, 3) for s, v in sorted(p.state_factor.items())},
        }), use_container_width=True, height=160)
        p.hhd_diff = st.number_input(
            f"Non-HHD diff (cur {cp.hhd_diff*100:.1f}%)", value=float(p.hhd_diff),
            step=0.01, format="%.3f", key="sales_hhd_diff")

    st.caption("Adopt the distribution mix and the premium factor model separately, or "
               "both at once. (Edited differentials above are included in the premium adopt.) "
               "Adopting premiums also writes per-cell premiums from the sales averages "
               "(these drive priced premium directly); the premium pull-forward stress is "
               "set on the Pull-forward tab.")

    def _adopt_sales(parts, msg):
        import copy
        from app.state import set_assumptions
        new = copy.deepcopy(get_assumptions())
        if "distribution" in parts:
            new.distribution = copy.deepcopy(suggested.distribution)
        if "premium" in parts:
            new.premium = copy.deepcopy(suggested.premium)
        set_assumptions(new)
        st.success(msg)

    sc = st.columns(3)
    if sc[0].button("Adopt distribution", key="sales_adopt_dist"):
        _adopt_sales(("distribution",), "Adopted the distribution weight grid.")
    if sc[1].button("Adopt premiums", key="sales_adopt_prem"):
        _adopt_sales(("premium",), "Adopted the premium factor tables.")
    if sc[2].button("Adopt all", type="primary", key="sales_adopt"):
        _adopt_sales(("distribution", "premium"),
                     "Adopted the distribution and premium factor tables.")


def _claims_section() -> None:
    st.subheader("Claims data")
    c = st.columns([1, 1, 2])
    c[0].download_button("Download template", load_template_csv("claims_template.csv"),
                         "claims_template.csv", "text/csv", key="claims_template_dl")
    if c[1].button("Load sample data", key="load_claims_sample"):
        st.session_state["claims_text"] = load_template_csv("claims_sample.csv")
    up = st.file_uploader("Upload claims CSV", type=["csv"], key="claims_upload")
    if up is not None:
        st.session_state["claims_text"] = up.getvalue().decode("utf-8")

    st.caption("Expected columns: " + ", ".join(CLAIMS_COLUMNS))
    text = st.session_state.get("claims_text")
    if not text:
        return
    try:
        records = _read_csv_to_records(text)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse CSV: {exc}")
        return
    st.session_state["claims_records"] = records
    m = derive_morbidity(records)
    st.success(f"Parsed {m['n_rows']:,} rows; observed overall claim cost "
               f"${m['overall_cc']:,.0f}/life-year.")

    cur = get_assumptions()
    cmorb = cur.morbidity
    cred = st.number_input(
        "Full-credibility standard (life-years of exposure; 0 = no blending)",
        value=2000.0, min_value=0.0, step=500.0, key="claims_cred_std",
        help="Z = min(1, sqrt(exposure / standard)); adopted base cost = "
             "Z·experience + (1−Z)·current pricing.")

    st.markdown("**Base claim cost by plan & issue age — current vs experience vs "
                "credibility-blended adopt** (gender blend, per life-year)")
    bca = m["base_cc_by_issue_age"]
    expo = m.get("base_cc_exposure", {})
    ages = list(cmorb.ages)
    rows = {}
    for p in cmorb.plans:
        cur_map = dict(zip(cmorb.ages, cmorb.base_cc[p]))
        for a in ages:
            sg = bca.get(p, {}).get(a)
            z = credibility_z(expo.get(p, {}).get(a, 0.0), cred)
            adopt = blend(sg, cur_map.get(a, 0.0), z) if sg is not None else cur_map.get(a)
            r = rows.setdefault(a, {})
            r[f"{p} cur"] = round(cur_map.get(a, 0.0))
            r[f"{p} exp"] = round(sg) if sg is not None else None
            r[f"{p} Z"] = round(z, 2)
            r[f"{p} adopt"] = round(adopt) if adopt is not None else None
    st.dataframe(pd.DataFrame(rows).T.sort_index(), use_container_width=True, height=250)

    cols = st.columns(3)
    with cols[0]:
        st.caption(f"Gender differential — raw {m['gender_diff']*100:.1f}% vs "
                   f"isolated {m['gender_diff_isolated']*100:.1f}% "
                   f"(current model {cmorb.gender_cc_diff*100:.1f}%)")
        m["gender_diff_isolated"] = st.number_input(
            "Adopted gender differential (M vs F)", value=float(m["gender_diff_isolated"]),
            step=0.01, format="%.3f", key="claims_gender_diff",
            help="Isolated (multivariate) estimate, holding age/plan/UW fixed — editable.")
    with cols[1]:
        st.markdown("**State factors (vs All)** — current vs experience")
        sf_cur = cmorb.state_factors
        st.dataframe(pd.DataFrame({
            "current": {s: round(sf_cur.get(s, 1.0), 3) for s in sorted(m["state_factors"])},
            "experience": {s: round(f, 3) for s, f in sorted(m["state_factors"].items())},
        }), use_container_width=True, height=220)
    with cols[2]:
        st.markdown("**Claim-cost aging — current vs suggested** (cumulative, ≥1)")
        st.caption(f"From the attained-age claim progression (ref issue age "
                   f"{m.get('aging_ref_issue_age', 70)}); the data has only ~6 policy "
                   f"durations, so aging is anchored to attained age, not duration.")
        cur_cum, run = {}, 1.0
        for i, inc in enumerate(cmorb.cc_aging_by_duration[:10], start=1):
            run *= (1.0 + inc)
            cur_cum[i] = round(run, 3)
        st.dataframe(pd.DataFrame({
            "current": cur_cum,
            "suggested": {d: round(v, 3) for d, v in sorted(m["aging_curve"].items()) if d <= 10},
        }), use_container_width=True, height=220)

    st.markdown("**UW selection by duration — current vs experience vs adopted**")
    st.caption("Experience is credibility-blended toward current pricing by exposure; thin "
               "durations (e.g. duration 6) carry little weight and revert to pricing.")
    sel_adopt = apply_claims(get_assumptions(), m, parts=("selection",),
                             credibility_standard=cred).morbidity.selection_factors
    adopt_map = {(r["uw"], r["duration"]): r["factor"] for r in sel_adopt
                 if r["issue_age"] == cmorb.ages[0]}
    cur_map_sel = {(r["uw"], r["duration"]): r["factor"] for r in cmorb.selection_factors
                   if r["issue_age"] == cmorb.ages[0]}
    exp_map = {(uw, d): f for (uw, d), f in m["selection"].items()}
    exp_exp = m.get("selection_exposure", {})
    durs = sorted({d for (_u, d) in set(exp_map) | set(cur_map_sel) | set(adopt_map)})
    seltbl = {}
    for uw in ("UW", "OE", "GI"):
        for d in durs:
            seltbl.setdefault(d, {})[f"{uw} cur"] = round(cur_map_sel.get((uw, d), float("nan")), 3)
            seltbl[d][f"{uw} exp"] = round(exp_map.get((uw, d), float("nan")), 3)
            seltbl[d][f"{uw} adopt"] = round(adopt_map.get((uw, d), float("nan")), 3)
            seltbl[d][f"{uw} ly"] = round(exp_exp.get((uw, d), 0.0))
    st.dataframe(pd.DataFrame(seltbl).T.sort_index(), use_container_width=True, height=240)

    st.caption("Adopt each piece separately, or all at once. Base cost is credibility-"
               "blended toward current pricing; aging is isolated and forced monotone ≥1. "
               "Where an issue-age band (or plan) has no experience, the current pricing "
               "value is kept (revert to pricing). Lapse, mortality, trend, commission and "
               "economic assumptions are not in the claims data and stay manual.")

    def _adopt_claims(parts, msg):
        from app.state import set_assumptions
        set_assumptions(apply_claims(get_assumptions(), m, parts=parts,
                                     credibility_standard=cred))
        st.success(msg)

    ac = st.columns(6)
    if ac[0].button("Adopt base cost", key="claims_adopt_base"):
        _adopt_claims(("base_cc",), "Adopted base claim cost (credibility-blended).")
    if ac[1].button("Adopt gender", key="claims_adopt_gender"):
        _adopt_claims(("gender",), "Adopted the gender differential.")
    if ac[2].button("Adopt state", key="claims_adopt_state"):
        _adopt_claims(("state",), "Adopted state morbidity factors.")
    if ac[3].button("Adopt selection", key="claims_adopt_sel"):
        _adopt_claims(("selection",), "Adopted UW selection factors.")
    if ac[4].button("Adopt aging", key="claims_adopt_aging"):
        _adopt_claims(("aging",), "Adopted claim-cost aging.")
    if ac[5].button("Adopt all", type="primary", key="claims_adopt"):
        _adopt_claims(("base_cc", "gender", "state", "selection", "aging"),
                      "Adopted base cost, gender, state, selection, and aging.")


def _ae_section() -> None:
    st.subheader("Actual-to-Expected (morbidity)")
    st.caption("Expected is computed from the assumptions **currently loaded in the model** "
               "(after any Adopt). Load claims, optionally Adopt, then review A/E here.")
    records = st.session_state.get("claims_records")
    if not records:
        st.info("Load claims data on the 'Claims → morbidity' tab first.")
        return
    dims = st.multiselect(
        "Group by", ["state", "plan", "issue_age", "uw_class", "duration"],
        default=["state"], key="ae_groupby",
        help="Choose nothing to roll up to a single all-data figure.")
    out = actual_to_expected(records, get_assumptions(), by=tuple(dims))
    df = pd.DataFrame(out)
    for col in ("actual", "expected"):
        if col in df:
            df[col] = df[col].round(0)
    if "ae" in df:
        df["ae"] = df["ae"].round(3)

    def _ae_color(v):
        # dependency-free colouring (no matplotlib): red = light assumptions, green = redundant
        try:
            if v >= 1.10:
                return "background-color: #f8b4b4"
            if v <= 0.90:
                return "background-color: #b4f8b4"
        except TypeError:
            pass
        return ""

    styler = df.style.map(_ae_color, subset=["ae"]) if "ae" in df else df
    st.dataframe(styler, hide_index=True, use_container_width=True, height=420)
    st.caption("A/E > 1 (red) means actual claims exceeded expected (assumptions may be light); "
               "< 1 (green) means redundant.")
