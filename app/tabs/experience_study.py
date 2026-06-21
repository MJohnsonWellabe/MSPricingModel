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

    st.markdown("#### Suggested distribution weight factors")
    st.caption("Adopt fits a joint plan × issue-age × UW grid from the data plus "
               "gender / preferred / HHD marginals. The marginal summaries below are "
               "derived from that grid for reference.")
    st.markdown("**By issue age**")
    st.dataframe(_factor_df(d.by_issue_age, "Weight"), use_container_width=True)
    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Gender**"); st.dataframe(_factor_df(d.gender, "Weight"), use_container_width=True)
        st.markdown("**Preferred**"); st.dataframe(_factor_df(d.preferred, "Weight"), use_container_width=True)
    with cols[1]:
        st.markdown("**Plan**"); st.dataframe(_factor_df(d.plan, "Weight"), use_container_width=True)
        st.markdown("**HHD**"); st.dataframe(_factor_df(d.hhd, "Weight"), use_container_width=True)
    with cols[2]:
        st.markdown("**UW**"); st.dataframe(_factor_df(d.uw, "Weight"), use_container_width=True)

    st.markdown("#### Suggested premium factors")
    st.markdown("**Base premium by issue age** (plan-G blend)")
    st.dataframe(_factor_df(p.base_by_issue_age, "Base premium"), use_container_width=True)
    pc = st.columns(3)
    st.caption("The suggested differentials are editable — adjust before adopting.")
    with pc[0]:
        st.markdown("**Plan relativities (G = 1.00)**")
        st.dataframe(_factor_df(p.plan_rel, "Relativity"), use_container_width=True)
        p.gender_diff = st.number_input(
            "Gender differential (M vs F)", value=float(p.gender_diff),
            step=0.01, format="%.3f", key="sales_gender_diff")
    with pc[1]:
        st.markdown("**UW relativities**")
        st.dataframe(_factor_df(p.uw_rel, "Relativity"), use_container_width=True)
        p.preferred_diff = st.number_input(
            "Non-preferred differential", value=float(p.preferred_diff),
            step=0.01, format="%.3f", key="sales_pref_diff")
    with pc[2]:
        st.markdown("**State factor**")
        st.dataframe(_factor_df(p.state_factor, "Factor"), use_container_width=True, height=220)
        p.hhd_diff = st.number_input(
            "Non-HHD differential", value=float(p.hhd_diff),
            step=0.01, format="%.3f", key="sales_hhd_diff")

    if st.button("Adopt distribution & premiums", type="primary", key="sales_adopt"):
        from app.state import set_assumptions
        set_assumptions(suggested)
        st.success("Adopted into the distribution and premium factor tables.")


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

    st.markdown("**Base claim cost by plan & attained age** (gender blend)")
    bca = m["base_cc_by_age"]
    ages = sorted({a for p in bca.values() for a in p})
    dfb = pd.DataFrame({p: {a: round(bca.get(p, {}).get(a, float("nan")), 0) for a in ages}
                        for p in sorted(bca)})
    st.dataframe(dfb, use_container_width=True, height=260)

    cols = st.columns(3)
    with cols[0]:
        m["gender_diff"] = st.number_input(
            "Gender differential (M vs F)", value=float(m["gender_diff"]),
            step=0.01, format="%.3f", key="claims_gender_diff",
            help="Suggested from the data — editable before adopting.")
    with cols[1]:
        st.markdown("**State factors (vs All)**")
        st.dataframe(pd.DataFrame(
            {"Factor": {s: round(f, 3) for s, f in sorted(m["state_factors"].items())}}),
            use_container_width=True, height=220)
    with cols[2]:
        st.markdown("**Claim-cost aging (diagnostic)**")
        st.dataframe(pd.DataFrame(
            {"cc_d/cc_1": {d: round(r, 3) for d, r in sorted(m["aging_by_duration"].items())}}),
            use_container_width=True, height=220)

    st.markdown("**UW selection by duration** (observed cc relative to all-UW)")
    sel = {}
    for (uw, d), f in m["selection"].items():
        sel.setdefault(uw, {})[d] = round(f, 3)
    st.dataframe(pd.DataFrame(sel), use_container_width=True, height=200)

    st.caption("Adopt sets base claim cost by age, the gender differential, state morbidity "
               "factors, and UW selection factors. Claim-cost aging is a diagnostic (not "
               "auto-adopted). Lapse, mortality, trend, commission and economic assumptions "
               "are not in the claims data and stay manual.")
    if st.button("Adopt morbidity", type="primary", key="claims_adopt"):
        from app.state import set_assumptions
        set_assumptions(apply_claims(get_assumptions(), m))
        st.success("Adopted base claim cost, gender differential, state factors, and selection.")


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
