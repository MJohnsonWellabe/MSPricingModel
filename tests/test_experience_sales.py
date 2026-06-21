import csv
import io

from medigap_engine.experience.sales import aggregate_sales
from medigap_engine.experience.schema import normalize_sales
from medigap_engine.io.defaults import load_template_csv


def test_normalize_sales_buckets_and_maps():
    rows = [
        {"Issue State Code": "TX", "Customer Age at Issue": 66,
         "Customer Gender": "Male", "Plan Name": "MED SUPP PLAN G",
         "Med Supp Underwriting Type": "UW", "Preferred": "Yes",
         "Household Discount": "No", "Application Count": 3, "Entered Premium": 4500},
    ]
    out = normalize_sales(rows)
    assert len(out) == 1
    r = out[0]
    assert r["issue_age"] == 65   # 66 -> nearest band 65
    assert r["gender"] == "M" and r["plan"] == "G" and r["uw_class"] == "UW"
    assert r["preferred"] == "Y" and r["hhd"] == "N"


def test_aggregate_sales_weights_and_premium():
    rows = [
        {"state": "TX", "issue_age": 65, "gender": "M", "plan": "G", "uw_class": "UW",
         "preferred": "Y", "hhd": "Y", "application_count": 3, "entered_premium": 3000},
        {"state": "FL", "issue_age": 65, "gender": "M", "plan": "G", "uw_class": "UW",
         "preferred": "Y", "hhd": "Y", "application_count": 1, "entered_premium": 1200},
        {"state": "TX", "issue_age": 73, "gender": "F", "plan": "N", "uw_class": "OE",
         "preferred": "N", "hhd": "N", "application_count": 4, "entered_premium": 4000},
    ]
    agg = aggregate_sales(rows)
    k1 = (65, "M", "G", "UW", "Y", "Y")
    k2 = (73, "F", "N", "OE", "N", "N")
    assert abs(sum(agg["weights"].values()) - 1.0) < 1e-9
    assert abs(agg["weights"][k1] - 0.5) < 1e-9   # 4 of 8 applications
    # avg premium for k1 = (3000+1200)/(3+1) = 1050
    assert abs(agg["avg_premium"][k1] - 1050.0) < 1e-9
    assert abs(agg["state_premiums"][k1]["TX"] - 1000.0) < 1e-9
    assert abs(agg["avg_premium"][k2] - 1000.0) < 1e-9


def test_sales_sample_loads_and_aggregates():
    text = load_template_csv("sales_sample.csv")
    rows = list(csv.DictReader(io.StringIO(text)))
    agg = aggregate_sales(rows)
    assert agg["n_rows"] > 0
    assert abs(sum(agg["weights"].values()) - 1.0) < 1e-6
