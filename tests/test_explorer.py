"""Explorer API logic and the HTTP Lambda wiring, against the in-memory graph."""

import json

import pytest

pytest.importorskip("rdflib")

from functions.explorer_api.handler import handle_http  # noqa: E402
from warranty_kg.explorer import NotFound  # noqa: E402
from warranty_kg.namespaces import iri  # noqa: E402

CLAIM = iri("claim", "C-100245")


def test_stats(explorer, generated):
    s = explorer.stats()
    assert s["counts"]["claim"] == len(generated[0].claims)
    assert s["totalClaimCost"] > 0 and s["triples"] > 50_000


@pytest.mark.parametrize("text,type_,ident", [
    ("C-100245", "claim", "C-100245"), ("water pump", "part", "16100-WP220"),
    ("prosper", "dealer", "D014"), ("apex", "supplier", "S01"), ("RO-987654", "repairOrder", "RO-987654")])
def test_search(explorer, text, type_, ident):
    first = explorer.search(text)["results"][0]
    assert (first["type"], first["identifier"]) == (type_, ident)


def test_search_rejects_short_text(explorer):
    with pytest.raises(ValueError):
        explorer.search("a")


def test_entities_paging(explorer):
    page = explorer.entities("claim", offset=0, limit=10)
    assert len(page["rows"]) == 10 and page["total"] > 500
    assert page["columns"][0] == "claimNumber"
    nxt = explorer.entities("claim", offset=10, limit=10)
    assert {r["iri"] for r in page["rows"]}.isdisjoint({r["iri"] for r in nxt["rows"]})


def test_entity(explorer):
    e = explorer.entity(CLAIM)
    attrs = {a["property"]: a["value"] for a in e["attributes"]}
    assert attrs["claimNumber"] == "C-100245" and attrs["failureCode"] == "COOL-LEAK"
    assert "BusinessEntity" in e["classes"]


def test_neighborhood_matches_the_mockup(explorer):
    n = explorer.neighborhood(CLAIM)
    types = {x["type"] for x in n["nodes"]}
    assert {"claim", "vehicle", "dealer", "part", "repairOrder", "supplier", "customer"} <= types
    supplier = next(x for x in n["nodes"] if x["type"] == "supplier")
    assert supplier["hop"] == 2 and supplier["label"] == "Apex Thermal Systems"


def test_neighborhood_caps_large_relations(explorer):
    n = explorer.neighborhood(iri("part", "16100-WP220"))
    rel = next(r for r in n["relations"] if r["predicate"] == "referencedByClaim")
    assert rel["total"] > rel["shown"] == 12


def test_related_panel(explorer):
    r = explorer.related(CLAIM)
    panel = {p["label"]: p["value"] for p in r["panel"]}
    assert panel["Vehicle model"] == "Aster" and panel["Model year"] == 2022
    assert panel["Related claims"] == len(r["relatedClaims"]) > 40


def test_bad_iris_are_rejected(explorer):
    for bad in ("http://evil/", iri("claim", "C-1") + "> } DROP ALL {", ""):
        with pytest.raises((ValueError, NotFound)):
            explorer.entity(bad)


def _get(explorer, path, **qs):
    resp = handle_http({"rawPath": path, "queryStringParameters": qs,
                        "requestContext": {"http": {"method": "GET"}}}, explorer)
    return resp["statusCode"], json.loads(resp["body"])


def test_http_routes(explorer):
    assert _get(explorer, "/api/stats")[0] == 200
    status, body = _get(explorer, "/api/competency/cq09")
    assert status == 200 and body["rows"] and body["columns"][0] == "model"
    status, body = _get(explorer, "/api/competency/cq01", claimNumber="C-100245")
    assert status == 200 and body["rows"][0]["dealer"] == "Prosper Meridian"
    assert _get(explorer, "/api/competency/cq01", claimNumber="nope")[0] == 400
    assert _get(explorer, "/api/competency/cq99")[0] == 404
    assert _get(explorer, "/api/nothing")[0] == 404
    assert _get(explorer, "/api/entities", type="spaceship")[0] == 400
