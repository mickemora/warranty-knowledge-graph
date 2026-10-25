"""Materialization rules and the ten competency questions, run against the in-memory graph."""

import pytest

pytest.importorskip("rdflib")

from warranty_kg import competency, rules  # noqa: E402
from warranty_kg.explorer import select_vars  # noqa: E402
from warranty_kg.namespaces import iri, sparql_prefixes  # noqa: E402

P = sparql_prefixes()


def ask(kg, body):
    return kg.ask(P + "ASK { " + body + " }")


def test_inverse_properties_materialized(kg, generated):
    vin = generated[0].signals["showcase"]["vin"]
    v = iri("vehicle", vin)
    assert ask(kg, f"<{v}> wko:ownedBy ?c . ?c a wko:Customer")              # from Customer owns
    assert ask(kg, f"<{v}> wko:hasClaim <{iri('claim', 'C-100245')}>")       # from claimForVehicle
    assert ask(kg, f"<{iri('supplier', 'S01')}> wko:supplies <{iri('part', '16100-WP220')}>")


def test_subclass_and_subproperty(kg):
    d = iri("dealer", "D014")
    for cls in ("Dealer", "Organization", "Party", "BusinessEntity"):
        assert ask(kg, f"<{d}> a wko:{cls}")
    assert ask(kg, f'<{d}> wko:identifier "D014"')


def test_every_claim_affects_one_top_level_system(kg):
    rows = kg.select(P + """SELECT ?c (COUNT(?s) AS ?n) WHERE { ?c a wko:WarrantyClaim .
        OPTIONAL { ?c wko:affectsSystem ?s } } GROUP BY ?c HAVING (COUNT(?s) != 1)""")
    assert rows == []


def test_rules_are_idempotent(kg):
    before = kg.select(rules.COUNT)[0]["n"]
    for _, update in rules.RULES:
        kg.update(update)
    assert kg.select(rules.COUNT)[0]["n"] == before


@pytest.fixture(scope="module")
def answers(kg):
    return {q.id: kg.select(q.bind()) for q in competency.load_all().values()}


def test_ten_questions_all_answer(answers):
    assert sorted(answers) == [f"cq{i:02d}" for i in range(1, 11)]
    assert all(answers.values()), [k for k, v in answers.items() if not v]


def test_cq01_claim_360(answers):
    (row,) = answers["cq01"]
    assert row["dealer"] == "Prosper Meridian" and row["supplier"] == "Apex Thermal Systems"
    assert row["category"] == "Engine Cooling" and row["system"] == "Powertrain"
    assert row["roNumber"] == "RO-987654" and row["owner"]


def test_cq03_related_claims_cluster_in_the_build_window(answers):
    rows = answers["cq03"]
    in_window = [r for r in rows if "2021-09-01" <= r["buildDate"] <= "2021-12-15"
                 and r["plant"] == "San Marcos, TX"]
    assert len(rows) >= 40 and len(in_window) / len(rows) > 0.75


def test_cq06_top_population_is_the_defect(answers):
    top = answers["cq06"][0]
    assert (top["partNumber"], top["model"], top["modelYear"], top["plant"]) == \
        ("16100-WP220", "Aster", 2022, "San Marcos, TX")


def test_cq07_flags_the_high_labor_dealer(answers):
    top = answers["cq07"][0]
    assert top["dealerCode"] == "D017" and top["laborVsStandard"] > 1.4
    assert all(r["laborVsStandard"] < 1.25 for r in answers["cq07"][1:])


def test_cq08_repeat_repairs_concentrate_at_one_dealer(answers):
    rows = answers["cq08"]
    assert sum(r["dealerCode"] == "D017" for r in rows) / len(rows) > 0.7


def test_cq09_finds_the_build_window(answers):
    top = answers["cq09"][0]
    assert top["model"] == "Aster" and top["plant"] == "San Marcos, TX"
    assert "2021-09" <= top["buildMonth"] <= "2021-12" and top["claimRatePct"] > 30


def test_cq10_at_risk_population(answers, generated):
    s = generated[0].signals["supplierDefect"]
    # vehicles in the window minus those that already have a water pump claim
    assert len(answers["cq10"]) == s["cohortVehicles"] - s["cohortClaims"]


def test_parameters_are_validated():
    q = competency.load_all()["cq01"]
    assert '"C-123456"' in q.bind({"claimNumber": "C-123456"})
    for bad in ('C-1" } DROP ALL #', "x", "C-1234567"):
        with pytest.raises(ValueError):
            q.bind({"claimNumber": bad})
    q10 = competency.load_all()["cq10"]
    assert '"2021-10-01"^^<http://www.w3.org/2001/XMLSchema#date>' in q10.bind({"buildFrom": "2021-10-01"})


def test_select_vars():
    q = "SELECT ?a ?b (COUNT(DISTINCT ?x) AS ?n) (ROUND(AVG(?y) * 10) / 10 AS ?avg) WHERE { }"
    assert select_vars(q) == ["a", "b", "n", "avg"]
