"""The synthetic dataset: volumes, referential integrity and the planted business signals."""

from collections import Counter
from datetime import date

from datagen.generate import (DEFECT_FROM, DEFECT_TO, Generator, inject_defects)
from warranty_kg.vin import check_digit, is_valid


def test_volumes_match_the_pilot_plan(generated):
    ds, _ = generated
    assert 500 <= len(ds.claims) <= 1000          # "500-1,000 claims" (Week 3)
    assert len(ds.vehicles) > 2000 and len(ds.dealers) == 24 and len(ds.suppliers) == 11
    assert len(ds.repair_orders) > len(ds.claims)  # every claim has an RO, plus customer-pay visits


def test_deterministic(generated):
    again = Generator(seed=42).run()
    assert [c["claim_number"] for c in again.claims] == [c["claim_number"] for c in generated[0].claims]


def test_vins_are_valid_and_unique(generated):
    ds, _ = generated
    vins = [v["vin"] for v in ds.vehicles]
    assert len(set(vins)) == len(vins)
    assert all(is_valid(v) for v in vins)
    assert check_digit("1M8GDM9AXKP042788") == "X"   # textbook example


def test_referential_integrity(generated):
    ds, _ = generated
    vins = {v["vin"] for v in ds.vehicles}
    dealers = {d["dealer_code"] for d in ds.dealers}
    parts = {p["part_number"] for p in ds.parts}
    ros = {r["ro_number"]: r for r in ds.repair_orders}
    customers = {c["customer_id"] for c in ds.customers}
    assert len(ros) == len(ds.repair_orders)
    assert len({c["claim_number"] for c in ds.claims}) == len(ds.claims)
    for v in ds.vehicles:
        assert v["owner_customer_id"] in customers and v["selling_dealer_code"] in dealers
        assert v["build_date"] < v["in_service_date"]
    for c in ds.claims:
        ro = ros[c["ro_number"]]
        assert c["vin"] in vins and c["dealer_code"] in dealers and c["causal_part_number"] in parts
        assert ro["vin"] == c["vin"] and ro["dealer_code"] == c["dealer_code"]
        assert ro["pay_type"] == "Warranty"
        assert abs(float(c["labor_cost"]) + float(c["parts_cost"]) - float(c["total_cost"])) < 0.011
    for ro in ds.repair_orders:
        for pn in filter(None, ro["replaced_part_numbers"].split("|")):
            assert pn in parts


def test_supplier_defect_signal(generated):
    ds, _ = generated
    vehicles = {v["vin"]: v for v in ds.vehicles}

    def in_cohort(v):
        return (v["model"], v["model_year"], v["assembly_plant"]) == ("Aster", 2022, "San Marcos, TX") \
            and DEFECT_FROM <= date.fromisoformat(v["build_date"]) <= DEFECT_TO

    pump = [c for c in ds.claims if c["causal_part_number"] == "16100-WP220"]
    cohort = [v for v in ds.vehicles if in_cohort(v)]
    in_window = {c["vin"] for c in pump if in_cohort(vehicles[c["vin"]])}
    rest = {c["vin"] for c in pump} - in_window
    cohort_rate = len(in_window) / len(cohort)
    other_rate = len(rest) / (len(ds.vehicles) - len(cohort))
    assert cohort_rate > 0.3 and cohort_rate > 20 * other_rate


def test_repeat_repairs_signal(generated):
    ds, _ = generated
    assert ds.signals["repeatRepairs"]["vehicles"] >= 10
    by_dealer = Counter(c["dealer_code"] for c in ds.claims)
    assert by_dealer["D017"] > 0


def test_showcase_claim(generated):
    ds, _ = generated
    c = next(c for c in ds.claims if c["claim_number"] == "C-100245")
    assert (c["dealer_code"], c["ro_number"], c["causal_part_number"]) == ("D014", "RO-987654", "16100-WP220")
    assert ds.signals["showcase"]["vin"].endswith("123456")


def test_defect_injection_is_logged():
    ds = inject_defects(Generator(seed=42).run())
    kinds = {d["defect"] for d in ds.defects}
    assert kinds == {"CLAIM_BEFORE_IN_SERVICE", "TOTAL_MISMATCH", "NEGATIVE_COST", "DEALER_MISMATCH",
                     "MISSING_CAUSAL_PART", "LABOR_HOURS_OUT_OF_RANGE", "BAD_CLAIM_NUMBER", "BAD_VIN_FORMAT"}
