"""Graph admin Lambda (inside the VPC): the only function that writes to Neptune.

Invoked by the load pipeline (Step Functions) and by scripts/kg.py. Event shapes:

  {"action": "load"}                          drop the four named graphs, start 3 bulk-load jobs
  {"action": "load_status", "loadIds": [..]}  -> {"status": COMPLETED | IN_PROGRESS | FAILED}
  {"action": "materialize"}                   rebuild the inferred graph (warranty_kg.rules)
  {"action": "smoke_test"}                    run all competency questions with defaults
  {"action": "counts"}                        triples per named graph
  {"action": "sparql", "query": "SELECT ..."} read-only query (guarded)
  {"action": "diagnose"}                      engine status, recent load jobs, counts

SPARQL goes over SigV4-signed HTTPS (warranty_kg.sparql.NeptuneSparql); the bulk loader API
goes through boto3's neptunedata client. IAM database authentication is on.
"""

from __future__ import annotations

import os
import time

import boto3
from botocore.config import Config

from warranty_kg import competency, rules
from warranty_kg.namespaces import (ALL_GRAPHS, GRAPH_DATA, GRAPH_INFERRED, GRAPH_ONTOLOGY,
                                    GRAPH_REFERENCE)
from warranty_kg.sparql import NeptuneSparql, ensure_read_only

# S3 prefix -> named graph. The data prefix is written by the transform step.
SOURCES = (("ontology/", GRAPH_ONTOLOGY), ("reference/", GRAPH_REFERENCE),
           ("rdf/data/", GRAPH_DATA))

_sparql = None
_loader = None


def sparql() -> NeptuneSparql:
    global _sparql
    if _sparql is None:
        _sparql = NeptuneSparql(timeout=240)
    return _sparql


def loader():
    global _loader
    if _loader is None:
        endpoint = f'https://{os.environ["NEPTUNE_ENDPOINT"]}:{os.environ["NEPTUNE_PORT"]}'
        _loader = boto3.client("neptunedata", endpoint_url=endpoint, config=Config(
            connect_timeout=5, read_timeout=60, retries={"total_max_attempts": 2, "mode": "standard"}))
    return _loader


def graph_counts() -> dict:
    rows = sparql().select("SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")
    counts = {g: 0 for g in ALL_GRAPHS}
    counts.update({r["g"]: r["n"] for r in rows})
    return counts


def action_load(_event):
    for g in ALL_GRAPHS:
        sparql().update(f"DROP SILENT GRAPH <{g}>")
    bucket = os.environ["DATA_BUCKET"]
    ids = []
    for prefix, graph in SOURCES:
        resp = loader().start_loader_job(
            source=f"s3://{bucket}/{prefix}", format="turtle",
            s3BucketRegion=os.environ["AWS_REGION"], iamRoleArn=os.environ["LOADER_ROLE_ARN"],
            failOnError=True, parallelism="MEDIUM", queueRequest=True,
            parserConfiguration={"namedGraphUri": graph})
        ids.append(resp["payload"]["loadId"])
    return {"loadIds": ids}


DONE = "LOAD_COMPLETED"
PENDING = {"LOAD_NOT_STARTED", "LOAD_IN_QUEUE", "LOAD_IN_PROGRESS"}


def action_load_status(event):
    jobs, errors = [], []
    for load_id in event["loadIds"]:
        payload = loader().get_loader_job_status(loadId=load_id, details=True, errors=True,
                                                 errorsPerPage=5)["payload"]
        overall = payload["overallStatus"]
        jobs.append({"loadId": load_id, "status": overall["status"],
                     "records": overall.get("totalRecords"),
                     "parsingErrors": overall.get("parsingErrors"),
                     "insertErrors": overall.get("insertErrors")})
        if payload.get("errors", {}).get("errorLogs"):
            errors.extend(payload["errors"]["errorLogs"][:5])
    statuses = [j["status"] for j in jobs]
    if any(s != DONE and s not in PENDING for s in statuses):
        status = "FAILED"
    elif all(s == DONE for s in statuses):
        status = "COMPLETED"
    else:
        status = "IN_PROGRESS"
    return {"status": status, "jobs": jobs, "errors": errors[:10], "loadIds": event["loadIds"]}


def action_materialize(_event):
    sparql().update(rules.CLEAR)
    timings = []
    for name, update in rules.RULES:
        start = time.time()
        sparql().update(update)
        timings.append({"rule": name, "seconds": round(time.time() - start, 2)})
    return {"rules": timings, "graphs": graph_counts()}


def action_smoke_test(_event):
    results, ok = [], True
    for q in competency.load_all().values():
        start = time.time()
        rows = sparql().select(q.bind())
        results.append({"id": q.id, "title": q.title, "rows": len(rows),
                        "seconds": round(time.time() - start, 2)})
        ok = ok and len(rows) > 0
    return {"passed": ok, "questions": results}


def action_counts(_event):
    return graph_counts()


def action_sparql(event):
    return sparql().select(ensure_read_only(event["query"], int(event.get("maxRows", 500))))


def action_diagnose(_event):
    out = {"endpoint": os.environ["NEPTUNE_ENDPOINT"], "bucket": os.environ["DATA_BUCKET"]}
    try:
        st = loader().get_engine_status()
        out["engine"] = {k: st.get(k) for k in ("status", "dbEngineVersion", "role")}
    except Exception as exc:  # report, don't fail: this is the troubleshooting action
        out["engine"] = f"UNREACHABLE: {type(exc).__name__}: {exc}"
        return out
    try:
        ids = loader().list_loader_jobs(limit=6)["payload"].get("loadIds", [])
        out["recentLoads"] = action_load_status({"loadIds": ids})["jobs"] if ids else []
    except Exception as exc:
        out["recentLoads"] = f"ERROR: {type(exc).__name__}: {exc}"
    try:
        out["graphs"] = graph_counts()
    except Exception as exc:
        out["graphs"] = f"ERROR: {type(exc).__name__}: {exc}"
    return out


ACTIONS = {name[len("action_"):]: fn for name, fn in globals().items()
           if name.startswith("action_")}


def handler(event, _context=None):
    action = (event or {}).get("action")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; one of {sorted(ACTIONS)}")
    return ACTIONS[action](event)
