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
                         "sales_template.csv", "text/csv")
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

    rows = []
    for k, w in sorted(agg["weights"].items(), key=lambda kv: -kv[1]):
        rows.append({
            "Issue age": k[0], "Gender": k[1], "Plan": k[2], "UW": k[3],
            "Pref": k[4], "HHD": k[5], "Weight": round(w, 5),
            "Avg premium": round(agg["avg_premium"].get(k, 0.0), 2),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=320)

    if st.button("Adopt distribution & premiums", type="primary"):
        from app.state import set_assumptions
        set_assumptions(apply_sales(get_assumptions(), agg))
        st.success("Adopted into the distribution and premium factor tables.")


def _claims_section() -> None:
    st.subheader("Claims data")
    c = st.columns([1, 1, 2])
    c[0].download_button("Download template", load_template_csv("claims_template.csv"),
                         "claims_template.csv", "text/csv")
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

    st.markdown("**Duration-1 claim cost by plan & issue age**")
    d1 = m["dur1_cc"]
    ages = sorted({a for p in d1.values() for a in p})
    df1 = pd.DataFrame({p: {a: round(d1.get(p, {}).get(a, float("nan")), 0) for a in ages}
                        for p in sorted(d1)})
    st.dataframe(df1, use_container_width=True)

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**State factors (vs All)**")
        st.dataframe(pd.DataFrame(
            {"Factor": {s: round(f, 3) for s, f in sorted(m["state_factors"].items())}}),
            use_container_width=True, height=240)
    with cols[1]:
        st.markdown("**Claim-cost aging by duration (cc_d / cc_1)**")
        st.dataframe(pd.DataFrame(
            {"Ratio": {d: round(r, 3) for d, r in sorted(m["aging_by_duration"].items())}}),
            use_container_width=True, height=240)

    st.caption("Adopting recalibrates the level of the base claim-cost tables (per "
               "plan) and the state morbidity factors. Selection and aging above are "
               "shown for your judgement and are not auto-applied.")
    if st.button("Adopt morbidity", type="primary"):
        from app.state import set_assumptions
        set_assumptions(apply_claims(get_assumptions(), m))
        st.success("Adopted base claim-cost level and state factors.")


def _ae_section() -> None:
    st.subheader("Actual-to-Expected (morbidity)")
    records = st.session_state.get("claims_records")
    if not records:
        st.info("Load claims data on the 'Claims → morbidity' tab first.")
        return
    dims = st.multiselect(
        "Group by", ["state", "plan", "issue_age", "uw_class", "duration"],
        default=["state"],
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
