"""Lambda handlers with AWS faked: admin (Neptune), rdf_tools (S3), NLQ wiring."""

import json

import pytest

from functions.admin import handler as admin


class FakeSparql:
    def __init__(self):
        self.updates, self.queries = [], []

    def update(self, u):
        self.updates.append(u)
        return {}

    def select(self, q):
        self.queries.append(q)
        if "GRAPH ?g" in q:
            return [{"g": "https://warranty.example.com/graph/data", "n": 70000}]
        return [{"x": 1}]


class FakeLoader:
    def __init__(self, statuses):
        self.statuses, self.jobs = statuses, []

    def start_loader_job(self, **kw):
        self.jobs.append(kw)
        return {"payload": {"loadId": f"id{len(self.jobs)}"}}

    def get_loader_job_status(self, loadId, **_):
        return {"payload": {"overallStatus": {"status": self.statuses[loadId], "totalRecords": 10}}}


@pytest.fixture
def fakes(monkeypatch):
    sp = FakeSparql()
    ld = FakeLoader({})
    monkeypatch.setattr(admin, "_sparql", sp)
    monkeypatch.setattr(admin, "_loader", ld)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("LOADER_ROLE_ARN", "arn:aws:iam::1:role/loader")
    return sp, ld


def test_load_drops_graphs_and_loads_three_sources(fakes):
    sp, ld = fakes
    out = admin.handler({"action": "load"})
    assert out == {"loadIds": ["id1", "id2", "id3"]}
    assert len(sp.updates) == 4 and all(u.startswith("DROP SILENT GRAPH") for u in sp.updates)
    assert [j["source"] for j in ld.jobs] == ["s3://bucket/ontology/", "s3://bucket/reference/",
                                              "s3://bucket/rdf/data/"]
    assert all(j["format"] == "turtle" and "namedGraphUri" in j["parserConfiguration"] for j in ld.jobs)


@pytest.mark.parametrize("statuses,expected", [
    (["LOAD_COMPLETED", "LOAD_COMPLETED"], "COMPLETED"),
    (["LOAD_COMPLETED", "LOAD_IN_PROGRESS"], "IN_PROGRESS"),
    (["LOAD_IN_QUEUE", "LOAD_NOT_STARTED"], "IN_PROGRESS"),
    (["LOAD_COMPLETED", "LOAD_FAILED"], "FAILED"),
    (["LOAD_S3_ACCESS_DENIED_ERROR", "LOAD_IN_PROGRESS"], "FAILED")])
def test_load_status(fakes, statuses, expected):
    _, ld = fakes
    ld.statuses = {f"j{i}": s for i, s in enumerate(statuses)}
    assert admin.handler({"action": "load_status", "loadIds": list(ld.statuses)})["status"] == expected


def test_materialize_and_smoke(fakes):
    sp, _ = fakes
    out = admin.handler({"action": "materialize"})
    assert len(out["rules"]) == len(sp.updates) - 1
    smoke = admin.handler({"action": "smoke_test"})
    assert smoke["passed"] and len(smoke["questions"]) == 10


def test_admin_sparql_is_read_only(fakes):
    from warranty_kg.sparql import SparqlError
    with pytest.raises(SparqlError):
        admin.handler({"action": "sparql", "query": "DROP ALL"})
    with pytest.raises(ValueError):
        admin.handler({"action": "nope"})


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def get_paginator(self, _name):
        objects = self.objects

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]}
        return P()


def test_rdf_tools_transform_and_validate(generated, monkeypatch):
    pytest.importorskip("pyshacl")
    from pathlib import Path

    from functions.rdf_tools import handler as rdf
    root = Path(__file__).resolve().parent.parent
    s3 = FakeS3()
    for f in (generated[1] / "raw").glob("*.csv"):
        s3.objects[f"raw/{f.name}"] = f.read_bytes()
    for folder in ("ontology", "reference", "shapes"):
        for f in (root / folder).glob("*.ttl"):
            s3.objects[f"{folder}/{f.name}"] = f.read_bytes()
    monkeypatch.setattr(rdf, "s3", s3)
    monkeypatch.setenv("DATA_BUCKET", "bucket")

    t = rdf.handler({"action": "transform"})
    assert t["entities"]["WarrantyClaim"] == len(generated[0].claims)
    assert "rdf/data/warranty-data.ttl" in s3.objects
    v = rdf.handler({"action": "validate", "execution": "test"})
    assert v["conforms"] and v["violations"] == 0
    assert v["reportKey"] in s3.objects and "reports/latest.json" in s3.objects
    assert json.loads(s3.objects["reports/latest.json"])["execution"] == "test"
    assert len(json.dumps(v)) < 256_000     # fits in a Step Functions payload


def test_nlq_handler_rejects_bad_input(monkeypatch):
    from functions.nlq import handler as nlq_handler
    monkeypatch.setattr(nlq_handler, "_nlq", type("N", (), {"ask": lambda self, q: (_ for _ in ()).throw(ValueError("question must be 3-500 characters"))})())
    resp = nlq_handler.handler({"body": json.dumps({"question": "x"})})
    assert resp["statusCode"] == 400
