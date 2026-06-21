"""Experience Study tab (Phase 1 placeholder structure).

Full derivation of morbidity/persistence assumptions from uploaded, pre-aggregated
claims data — plus the actual-to-expected (AE) analysis subtab — lands in Phase 2.
The expected upload format and AE views are previewed here so the workflow is clear.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

EXPECTED_COLUMNS = [
    "state", "plan", "issue_age", "gender", "uw_class", "duration",
    "exposure", "earned_premium", "incurred_claims",
]


def render() -> None:
    st.header("Experience Study")
    st.info(
        "Phase 2 feature. Upload a **pre-aggregated** claims extract (grouped by "
        "state / plan / issue age / gender / UW class / duration) to derive "
        "morbidity and persistency assumptions and run actual-to-expected analysis."
    )

    study, ae = st.tabs(["Study", "AE Analysis"])
    with study:
        st.subheader("Expected upload format")
        st.dataframe(pd.DataFrame(columns=EXPECTED_COLUMNS), hide_index=True,
                     use_container_width=True)
        up = st.file_uploader("Upload pre-aggregated claims CSV", type=["csv"],
                              disabled=False)
        if up is not None:
            try:
                df = pd.read_csv(up)
                st.dataframe(df.head(50), use_container_width=True)
                st.caption(f"{len(df):,} rows loaded. Assumption derivation arrives in Phase 2.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not parse CSV: {exc}")
    with ae:
        st.subheader("Actual-to-Expected (preview)")
        st.caption(
            "Will show A/E for morbidity and persistency at selectable granularity "
            "(by state, plan, age, duration) and roll up to all states."
        )
