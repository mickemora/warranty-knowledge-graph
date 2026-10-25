"""Explorer API Lambda (inside the VPC, read-only).

Two ways in:
  * API Gateway HTTP API (payload v2) for the UI: GET /api/... (see warranty_kg/explorer.py)
  * Direct invoke from the NLQ Lambda: {"action": "sparql_select", "query": "SELECT ..."}
"""

from __future__ import annotations

import base64
import json
import logging

from warranty_kg.explorer import Explorer, NotFound
from warranty_kg.sparql import NeptuneSparql, SparqlError, ensure_read_only

log = logging.getLogger()
log.setLevel(logging.INFO)

_explorer = None


def explorer() -> Explorer:
    global _explorer
    if _explorer is None:
        _explorer = Explorer(NeptuneSparql(timeout=25))
    return _explorer


def respond(status: int, body) -> dict:
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json", "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff"},
            "body": json.dumps(body, default=str)}


def route(ex: Explorer, method: str, path: str, qs: dict) -> object:
    path = "/" + path.strip("/")
    if path.startswith("/api"):
        path = path[4:] or "/"
    if method != "GET":
        raise ValueError(f"{method} not supported on {path}")
    if path == "/stats":
        return ex.stats()
    if path == "/search":
        return ex.search(qs.get("q", ""))
    if path == "/entities":
        return ex.entities(qs.get("type", "claim"), qs.get("offset", 0), qs.get("limit", 50))
    if path == "/entity":
        return ex.entity(qs.get("iri"))
    if path == "/neighborhood":
        return ex.neighborhood(qs.get("iri"))
    if path == "/related":
        return ex.related(qs.get("iri"))
    if path == "/competency":
        return ex.list_questions()
    if path.startswith("/competency/"):
        return ex.run_question(path.split("/")[2], qs)
    raise NotFound(path)


def handle_http(event: dict, ex: Explorer) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    qs = event.get("queryStringParameters") or {}
    try:
        return respond(200, route(ex, method, path, qs))
    except NotFound as exc:
        return respond(404, {"error": f"not found: {exc}"})
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    except SparqlError as exc:
        log.exception("query failed")
        return respond(502, {"error": str(exc)})


def handler(event, _context=None):
    if event.get("action") == "sparql_select":       # NLQ Lambda -> here -> Neptune
        try:
            return {"rows": explorer().sparql.select(ensure_read_only(event["query"], 100))}
        except SparqlError as exc:
            return {"error": str(exc)}
    if event.get("isBase64Encoded") and event.get("body"):
        event["body"] = base64.b64decode(event["body"]).decode()
    return handle_http(event, explorer())
