"""Canonical schemas and normalisation for uploaded sales and claims data.

The UI parses CSVs with pandas and hands the engine a list of plain dict rows;
these helpers map flexible/workbook-style headers and values to the canonical
form the experience functions expect. Pure stdlib — no pandas — so it runs under
Pyodide and is unit-testable headlessly.
"""
from __future__ import annotations

from typing import Iterable

ISSUE_AGE_BANDS = (65, 68, 73, 77, 83, 85)
PLANS = ("F", "G", "N")
UW_CLASSES = ("UW", "OE", "GI")

# canonical column sets (used for templates and validation)
SALES_COLUMNS = (
    "state", "issue_age", "gender", "plan", "uw_class",
    "preferred", "hhd", "application_count", "entered_premium",
)
CLAIMS_COLUMNS = (
    "state", "plan", "issue_age", "gender", "uw_class",
    "duration", "cnt", "earned", "annualized_prem", "adj_claims",
)

# header aliases (lower-cased) -> canonical key
_ALIASES = {
    "state": "state", "issue state code": "state", "policy_issue_state": "state",
    "issue_state": "state",
    "issue_age": "issue_age", "issue age": "issue_age",
    "customer age at issue": "issue_age", "person_issue_age": "issue_age",
    "age": "issue_age", "age bucket": "issue_age",
    "gender": "gender", "customer gender": "gender", "person_sex": "gender", "sex": "gender",
    "plan": "plan", "plan name": "plan", "plan_code": "plan",
    "uw_class": "uw_class", "uw": "uw_class", "underwriting": "uw_class",
    "med supp underwriting type": "uw_class",
    "preferred": "preferred", "pref": "preferred",
    "hhd": "hhd", "household discount": "hhd",
    "application_count": "application_count", "application count": "application_count",
    "count": "application_count", "applications": "application_count",
    "entered_premium": "entered_premium", "entered premium": "entered_premium",
    "premium": "entered_premium", "annualized_prem": "annualized_prem",
    "duration": "duration", "cnt": "cnt", "earned": "earned",
    "exposure": "exposure", "life_years": "exposure", "life years": "exposure",
    "adj_claims": "adj_claims", "adj claims": "adj_claims", "claims": "adj_claims",
}


def nearest_band(age) -> int:
    a = int(round(float(age)))
    return min(ISSUE_AGE_BANDS, key=lambda b: abs(b - a))


def _plan_letter(value) -> str | None:
    s = str(value).upper()
    # HIGH DEDUCTIBLE plans roll into their base letter; check explicit letters last
    for token, letter in (("PLAN F", "F"), ("PLAN G", "G"), ("PLAN N", "N")):
        if token in s:
            return letter
    s2 = s.strip()
    if s2 in PLANS:
        return s2
    # plan codes like "MMS24G" / "MLHMS21G" end in the plan letter
    for ch in reversed(s2):
        if ch in PLANS:
            return ch
    return None


def _gender(value) -> str | None:
    s = str(value).strip().upper()
    if s.startswith("M"):
        return "M"
    if s.startswith("F"):
        return "F"
    return None


def _uw(value) -> str | None:
    s = str(value).strip().upper()
    return s if s in UW_CLASSES else None


def _yn(value) -> str | None:
    s = str(value).strip().upper()
    if s in ("Y", "YES", "TRUE", "1"):
        return "Y"
    if s in ("N", "NO", "FALSE", "0", ""):
        return "N"
    return None


def _num(value) -> float | None:
    try:
        s = str(value).replace(",", "").replace("$", "").strip()
        if s == "" or s.upper() == "NULL":
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _remap(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        key = _ALIASES.get(str(k).strip().lower())
        if key and key not in out:
            out[key] = v
    return out


def normalize_sales(rows: Iterable[dict]) -> list[dict]:
    """Return canonical sales rows, skipping rows missing required fields."""
    result = []
    for raw in rows:
        r = _remap(raw)
        plan = _plan_letter(r.get("plan", ""))
        gender = _gender(r.get("gender", ""))
        uw = _uw(r.get("uw_class", ""))
        count = _num(r.get("application_count")) or 0.0
        if plan is None or gender is None or uw is None or "issue_age" not in r:
            continue
        result.append({
            "state": str(r.get("state", "All")).strip() or "All",
            "issue_age": nearest_band(r["issue_age"]),
            "gender": gender, "plan": plan, "uw_class": uw,
            "preferred": _yn(r.get("preferred", "N")) or "N",
            "hhd": _yn(r.get("hhd", "N")) or "N",
            "application_count": count,
            "entered_premium": _num(r.get("entered_premium")) or 0.0,
        })
    return result


def normalize_claims(rows: Iterable[dict]) -> list[dict]:
    """Return canonical claims rows, skipping rows missing required fields."""
    result = []
    for raw in rows:
        r = _remap(raw)
        plan = _plan_letter(r.get("plan", ""))
        uw = _uw(r.get("uw_class", ""))
        if plan is None or uw is None or "issue_age" not in r or "duration" not in r:
            continue
        cnt = _num(r.get("cnt")) or 0.0
        result.append({
            "state": str(r.get("state", "All")).strip() or "All",
            "plan": plan,
            "issue_age": nearest_band(r["issue_age"]),
            "gender": _gender(r.get("gender", "")) or "U",
            "uw_class": uw,
            "duration": int(round(_num(r.get("duration")) or 1)),
            "cnt": cnt,
            "exposure": _num(r.get("exposure")) or 0.0,
            "earned": _num(r.get("earned")) or 0.0,
            "annualized_prem": _num(r.get("annualized_prem")) or 0.0,
            "adj_claims": _num(r.get("adj_claims")) or 0.0,
        })
    return result
