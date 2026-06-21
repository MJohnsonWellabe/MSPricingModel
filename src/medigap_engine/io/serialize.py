"""(De)serialise the assumption model to/from plain dicts (JSON-friendly).

Kept dependency-free so it runs identically in CPython and Pyodide.
"""
from __future__ import annotations

from ..models.assumptions import (
    AssumptionSet,
    CommissionAssumptions,
    DistributionAssumptions,
    MorbidityAssumptions,
    OtherAssumptions,
    PremiumAssumptions,
    RerateAssumptions,
    TerminationAssumptions,
)


def assumptions_from_dict(d: dict) -> AssumptionSet:
    m = d["morbidity"]
    morbidity = MorbidityAssumptions(
        ages=list(m["ages"]),
        plans=list(m["plans"]),
        base_cc={k: list(v) for k, v in m["base_cc"].items()},
        gender_cc_diff=float(m["gender_cc_diff"]),
        state_factors=dict(m["state_factors"]),
        selection_factors=[dict(r) for r in m["selection_factors"]],
        cc_aging_by_duration=list(m["cc_aging_by_duration"]),
        preferred_diff=float(m["preferred_diff"]),
        hhd_diff=float(m["hhd_diff"]),
        trend_by_year=list(m["trend_by_year"]),
        trend_first_year_exponent=float(m.get("trend_first_year_exponent", 1.75)),
    )
    r = d["rerates"]
    rerates = RerateAssumptions(
        solve=bool(r["solve"]),
        specified_rerates=list(r["specified_rerates"]),
        aging_rerate_by_age_ages=list(r["aging_rerate_by_age_ages"]),
        aging_rerate_by_age_factor=list(r["aging_rerate_by_age_factor"]),
        target_lifetime_lr=float(r["target_lifetime_lr"]),
        target_irr=(None if r.get("target_irr") is None else float(r["target_irr"])),
        max_rerate=float(r["max_rerate"]),
        in_year_lr_floor=float(r["in_year_lr_floor"]),
        consecutive_z=float(r["consecutive_z"]),
        consecutive_b=int(r["consecutive_b"]),
        antiselection_lambda_claims=float(
            r.get("antiselection_lambda_claims", r.get("antiselection_lambda", 0.5))),
        antiselection_lambda_lapse=float(
            r.get("antiselection_lambda_lapse", r.get("antiselection_lambda", 0.5))),
    )
    p = d["premium"]
    premium = PremiumAssumptions(
        base_by_issue_age={int(k): float(v) for k, v in p["base_by_issue_age"].items()},
        plan_rel={k: float(v) for k, v in p["plan_rel"].items()},
        uw_rel={k: float(v) for k, v in p["uw_rel"].items()},
        gender_diff=float(p["gender_diff"]),
        preferred_diff=float(p["preferred_diff"]),
        hhd_diff=float(p["hhd_diff"]),
        state_factor={k: float(v) for k, v in p["state_factor"].items()},
        premium_trend=float(p.get("premium_trend", 0.0)),
    )
    dist = d["distribution"]
    distribution = DistributionAssumptions(
        by_issue_age={int(k): float(v) for k, v in dist["by_issue_age"].items()},
        gender={k: float(v) for k, v in dist["gender"].items()},
        plan={k: float(v) for k, v in dist["plan"].items()},
        uw={k: float(v) for k, v in dist["uw"].items()},
        preferred={k: float(v) for k, v in dist["preferred"].items()},
        hhd={k: float(v) for k, v in dist["hhd"].items()},
    )
    t = d["termination"]
    termination = TerminationAssumptions(
        base_lapse=list(t["base_lapse"]),
        uw_lapse_rel=list(t["uw_lapse_rel"]),
        state_factors=dict(t["state_factors"]),
        mort_age=list(t["mort_age"]),
        mort_qx=list(t["mort_qx"]),
        dur2_scaling=float(t["dur2_scaling"]),
        dur3plus_scaling=float(t["dur3plus_scaling"]),
    )
    c = d["commission"]
    commission = CommissionAssumptions(
        by_state={k: list(v) for k, v in c["by_state"].items()},
        plan_n_schedule=list(c["plan_n_schedule"]),
        nonn_schedule=list(c["nonn_schedule"]),
        gi_flat=float(c["gi_flat"]),
        plan_f_offset=float(c["plan_f_offset"]),
        age80_halving=bool(c["age80_halving"]),
    )
    o = d["other"]
    other = OtherAssumptions(**{k: float(v) for k, v in o.items()})
    return AssumptionSet(
        morbidity=morbidity, premium=premium, rerates=rerates, distribution=distribution,
        termination=termination, commission=commission, other=other,
        schema_version=str(d.get("schema_version", "1")),
    )


def assumptions_to_dict(a: AssumptionSet) -> dict:
    m, p, r, dist, t, c, o = (
        a.morbidity, a.premium, a.rerates, a.distribution, a.termination,
        a.commission, a.other,
    )
    return {
        "schema_version": a.schema_version,
        "morbidity": {
            "ages": m.ages, "plans": m.plans,
            "base_cc": m.base_cc, "gender_cc_diff": m.gender_cc_diff,
            "state_factors": m.state_factors, "selection_factors": m.selection_factors,
            "cc_aging_by_duration": m.cc_aging_by_duration,
            "preferred_diff": m.preferred_diff, "hhd_diff": m.hhd_diff,
            "trend_by_year": m.trend_by_year,
            "trend_first_year_exponent": m.trend_first_year_exponent,
        },
        "premium": {
            "base_by_issue_age": p.base_by_issue_age,
            "plan_rel": p.plan_rel, "uw_rel": p.uw_rel,
            "gender_diff": p.gender_diff, "preferred_diff": p.preferred_diff,
            "hhd_diff": p.hhd_diff, "state_factor": p.state_factor,
            "premium_trend": p.premium_trend,
        },
        "rerates": {
            "solve": r.solve, "specified_rerates": r.specified_rerates,
            "aging_rerate_by_age_ages": r.aging_rerate_by_age_ages,
            "aging_rerate_by_age_factor": r.aging_rerate_by_age_factor,
            "target_lifetime_lr": r.target_lifetime_lr, "target_irr": r.target_irr,
            "max_rerate": r.max_rerate, "in_year_lr_floor": r.in_year_lr_floor,
            "consecutive_z": r.consecutive_z, "consecutive_b": r.consecutive_b,
            "antiselection_lambda_claims": r.antiselection_lambda_claims,
            "antiselection_lambda_lapse": r.antiselection_lambda_lapse,
        },
        "distribution": {
            "by_issue_age": dist.by_issue_age, "gender": dist.gender, "plan": dist.plan,
            "uw": dist.uw, "preferred": dist.preferred, "hhd": dist.hhd,
        },
        "termination": {
            "base_lapse": t.base_lapse, "uw_lapse_rel": t.uw_lapse_rel,
            "state_factors": t.state_factors,
            "mort_age": t.mort_age, "mort_qx": t.mort_qx,
            "dur2_scaling": t.dur2_scaling, "dur3plus_scaling": t.dur3plus_scaling,
        },
        "commission": {
            "by_state": c.by_state, "plan_n_schedule": c.plan_n_schedule,
            "nonn_schedule": c.nonn_schedule, "gi_flat": c.gi_flat,
            "plan_f_offset": c.plan_f_offset, "age80_halving": c.age80_halving,
        },
        "other": {
            "discount_rate": o.discount_rate, "premium_tax": o.premium_tax,
            "oper_acq": o.oper_acq, "marketing_acq": o.marketing_acq,
            "maintenance": o.maintenance, "inflation": o.inflation,
            "rbc_factor": o.rbc_factor, "covariance": o.covariance,
            "rbc_pct_of_prem": o.rbc_pct_of_prem, "nier": o.nier,
            "tax_rate": o.tax_rate, "ibnr_pct": o.ibnr_pct,
        },
    }
