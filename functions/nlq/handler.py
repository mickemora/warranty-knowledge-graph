"""Natural-language search Lambda (outside the VPC, so it can reach Bedrock without a
VPC endpoint). It never talks to Neptune itself: generated queries are executed by the
read-only explorer Lambda, which checks them again.

HTTP API route: POST /api/nlq  {"question": "Which dealers have the most water pump claims?"}
"""

from __future__ import annotations

import base64
import json
import logging
import os

import boto3

from warranty_kg.nlq import Nlq
from warranty_kg.sparql import SparqlError

log = logging.getLogger()
log.setLevel(logging.INFO)
_lambda = None
_nlq = None


def execute(query: str) -> list[dict]:
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda")
    resp = _lambda.invoke(FunctionName=os.environ["EXPLORER_FUNCTION"],
                          Payload=json.dumps({"action": "sparql_select", "query": query}))
    out = json.loads(resp["Payload"].read())
    if "errorMessage" in out:
        raise SparqlError(out["errorMessage"])
    if out.get("error"):
        raise SparqlError(out["error"])
    return out["rows"]


def respond(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json",
                                              "Cache-Control": "no-store"},
            "body": json.dumps(body, default=str)}


def handler(event, _context=None):
    global _nlq
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    try:
        question = json.loads(body).get("question", "")
        if _nlq is None:
            _nlq = Nlq(execute)
        result = _nlq.ask(question)
        log.info(json.dumps({"question": question, "sparql": result.get("sparql"),
                             "rows": len(result.get("rows") or []), "error": result.get("error")}))
        return respond(200, result)
    except (ValueError, json.JSONDecodeError) as exc:
        return respond(400, {"error": str(exc)})
    except Exception as exc:  # Bedrock access, throttling: show the reason in the UI
        log.exception("nlq failed")
        return respond(502, {"error": f"{type(exc).__name__}: {exc}"})
