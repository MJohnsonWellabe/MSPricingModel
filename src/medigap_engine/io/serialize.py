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
    RerateAssumptions,
    TerminationAssumptions,
)


def assumptions_from_dict(d: dict) -> AssumptionSet:
    m = d["morbidity"]
    morbidity = MorbidityAssumptions(
        ages=list(m["ages"]),
        plans=list(m["plans"]),
        base_cc_male={k: list(v) for k, v in m["base_cc_male"].items()},
        base_cc_female={k: list(v) for k, v in m["base_cc_female"].items()},
        state_factors=dict(m["state_factors"]),
        selection_factors=[dict(r) for r in m["selection_factors"]],
        cc_aging_by_duration=list(m["cc_aging_by_duration"]),
        preferred_factor=dict(m["preferred_factor"]),
        hhd_factor=dict(m["hhd_factor"]),
        trend_by_year=list(m["trend_by_year"]),
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
        antiselection_lambda=float(r["antiselection_lambda"]),
    )
    dist = d["distribution"]
    distribution = DistributionAssumptions(
        gender=dict(dist["gender"]),
        preferred=dict(dist["preferred"]),
        hhd=dict(dist["hhd"]),
    )
    t = d["termination"]
    termination = TerminationAssumptions(
        base_lapse={k: list(v) for k, v in t["base_lapse"].items()},
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
        morbidity=morbidity, rerates=rerates, distribution=distribution,
        termination=termination, commission=commission, other=other,
        schema_version=str(d.get("schema_version", "1")),
    )


def assumptions_to_dict(a: AssumptionSet) -> dict:
    m, r, dist, t, c, o = (
        a.morbidity, a.rerates, a.distribution, a.termination, a.commission, a.other,
    )
    return {
        "schema_version": a.schema_version,
        "morbidity": {
            "ages": m.ages, "plans": m.plans,
            "base_cc_male": m.base_cc_male, "base_cc_female": m.base_cc_female,
            "state_factors": m.state_factors, "selection_factors": m.selection_factors,
            "cc_aging_by_duration": m.cc_aging_by_duration,
            "preferred_factor": m.preferred_factor, "hhd_factor": m.hhd_factor,
            "trend_by_year": m.trend_by_year,
        },
        "rerates": {
            "solve": r.solve, "specified_rerates": r.specified_rerates,
            "aging_rerate_by_age_ages": r.aging_rerate_by_age_ages,
            "aging_rerate_by_age_factor": r.aging_rerate_by_age_factor,
            "target_lifetime_lr": r.target_lifetime_lr, "target_irr": r.target_irr,
            "max_rerate": r.max_rerate, "in_year_lr_floor": r.in_year_lr_floor,
            "consecutive_z": r.consecutive_z, "consecutive_b": r.consecutive_b,
            "antiselection_lambda": r.antiselection_lambda,
        },
        "distribution": {"gender": dist.gender, "preferred": dist.preferred, "hhd": dist.hhd},
        "termination": {
            "base_lapse": t.base_lapse, "state_factors": t.state_factors,
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
