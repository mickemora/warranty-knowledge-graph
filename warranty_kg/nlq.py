"""Natural-language questions -> SPARQL with Claude on Amazon Bedrock (optional, Week 5).

Flow:
  1. The model gets a compact description of the ontology (generated from ontology/warranty.ttl)
     and the ten competency questions as worked examples, and writes one SPARQL SELECT.
  2. The query is checked: read-only, no SERVICE, row limit, and it must parse.
  3. It runs through the caller's executor (in AWS: the explorer Lambda inside the VPC).
     If Neptune rejects it, the model gets the error once and can correct the query.
  4. The model summarizes the rows in two or three sentences, using only numbers in the rows.

The ontology is the contract: the model may only use classes and properties that exist in it,
which is what makes generated queries reviewable.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from warranty_kg import competency
from warranty_kg.namespaces import PREFIXES, WKO
from warranty_kg.sparql import SparqlError, ensure_read_only

# Claude Sonnet 4.5 through the global cross-Region inference profile, which most Bedrock
# regions can call. Override with NLQ_MODEL_ID (Lambda) or `-c nlqModelId=` (CDK), for example
# us.anthropic.claude-sonnet-4-5-20250929-v1:0 to keep inference in US regions.
DEFAULT_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = Path(os.environ.get("ONTOLOGY_FILE") or ROOT / "ontology" / "warranty.ttl")
MAX_ROWS = 100
# API Gateway HTTP APIs stop waiting after 30 s, so the slower optional steps (a corrected
# query, the summary) only run while there is time left.
RETRY_BUDGET_S, SUMMARY_BUDGET_S = 14, 20

_schema_cache: str | None = None


def schema_text(path: Path = ONTOLOGY) -> str:
    """Render the ontology as a compact, model-friendly schema description."""
    global _schema_cache
    if _schema_cache:
        return _schema_cache
    from rdflib import OWL, RDF, RDFS, Graph, Namespace

    skos = Namespace("http://www.w3.org/2004/02/skos/core#")
    g = Graph().parse(path, format="turtle")

    def short(x):
        return "wko:" + str(x)[len(WKO):] if str(x).startswith(WKO) else (
            "xsd:" + str(x).split("#")[-1] if "XMLSchema" in str(x) else
            "skos:Concept" if str(x).endswith("skos/core#Concept") else str(x))

    lines = ["Classes:"]
    for c in sorted(g.subjects(RDF.type, OWL.Class), key=str):
        if not str(c).startswith(WKO):
            continue
        sup = ", ".join(short(s) for s in g.objects(c, RDFS.subClassOf))
        d = g.value(c, skos.definition)
        lines.append(f"  {short(c)}" + (f" (subclass of {sup})" if sup else "")
                     + (f": {d}" if d else ""))
    lines.append("Relationships (subject -> object):")
    for p in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
        dom, rng = g.value(p, RDFS.domain), g.value(p, RDFS.range)
        inv = g.value(p, OWL.inverseOf)
        lines.append(f"  {short(dom)} {short(p)} {short(rng)}"
                     + (f"   (inverse: {short(inv)})" if inv else ""))
    lines.append("Attributes:")
    for p in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
        lines.append(f"  {short(g.value(p, RDFS.domain))} {short(p)} {short(g.value(p, RDFS.range))}")
    _schema_cache = "\n".join(lines)
    return _schema_cache


def system_prompt() -> str:
    examples = "\n\n".join(
        f"Question: {q.question}\n```sparql\n{_strip_header(q.bind())}\n```"
        for q in competency.load_all().values())
    prefixes = "\n".join(f"PREFIX {k}: <{v}>" for k, v in PREFIXES.items()
                         if k in ("wko", "rdfs", "skos", "xsd"))
    return f"""You translate warranty business questions into SPARQL 1.1 for Amazon Neptune.

The graph follows this ontology (prefix wko: <{WKO}>):
{schema_text()}

Facts about the data:
- Every entity has rdfs:label (claim numbers, dealer names, part names, vehicle "2022 Meridian Aster XLE", customer names).
- Part categories are SKOS concepts: wko:PartCategory with rdfs:label and skos:broader to a top-level vehicle system
  (Powertrain, Chassis, Electrical, Body & Interior, Climate). wko:affectsSystem links a claim to its system.
- Claim status: wko:hasStatus to a concept whose rdfs:label is Submitted, Under review, Approved, Paid or Rejected.
- Inverse relationships are materialized, so both directions can be queried.
- Dates are xsd:date (compare with "2023-01-01"^^xsd:date). Money is USD xsd:decimal.
- Plants: "San Marcos, TX", "Lexington, KY", "Chattanooga, TN". Models: Aster, Cascade, Summit, Lumen. Make: Meridian.

Rules:
- Write exactly one SELECT query. Never write updates, SERVICE or federated queries.
- Use only the classes and properties listed above, with these prefixes:
{prefixes}
- Return human-readable columns (labels, numbers, dates), not only IRIs. Use ORDER BY, and LIMIT 50 unless the question asks for a count.
- For text matching use CONTAINS(LCASE(STR(?x)), "lowercase text").
- Reply with one short sentence explaining the approach, then the query in a ```sparql block. Nothing else.

Worked examples (the ten competency questions):

{examples}"""


def _strip_header(q: str) -> str:
    return "\n".join(line for line in q.splitlines() if not line.startswith("#")).strip()


def extract_sparql(text: str) -> tuple[str, str]:
    m = re.search(r"```(?:sparql)?\s*(.*?)```", text, re.S | re.I)
    if not m:
        raise SparqlError("the model did not return a SPARQL block")
    explanation = text[:m.start()].strip()
    return m.group(1).strip(), explanation


def check_syntax(query: str) -> None:
    try:
        from rdflib.plugins.sparql import prepareQuery
    except ImportError:  # syntax check is best-effort where rdflib is unavailable
        return
    try:
        prepareQuery(query)
    except Exception as exc:  # pyparsing errors have many types
        raise SparqlError(f"generated SPARQL does not parse: {exc}") from None


class Nlq:
    def __init__(self, executor: Callable[[str], list[dict]], bedrock=None,
                 model_id: str | None = None):
        self.execute = executor
        self.model_id = model_id or os.environ.get("NLQ_MODEL_ID") or DEFAULT_MODEL
        if bedrock is None:
            import boto3
            bedrock = boto3.client("bedrock-runtime")
        self.bedrock = bedrock

    def _converse(self, system: str, messages: list[dict], max_tokens: int = 1500) -> str:
        resp = self.bedrock.converse(modelId=self.model_id, system=[{"text": system}],
                                     messages=messages,
                                     inferenceConfig={"maxTokens": max_tokens})
        return "".join(c.get("text", "") for c in resp["output"]["message"]["content"])

    def ask(self, question: str) -> dict:
        question = (question or "").strip()
        if not 3 <= len(question) <= 500:
            raise ValueError("question must be 3-500 characters")
        started = time.monotonic()
        system = system_prompt()
        messages = [{"role": "user", "content": [{"text": question}]}]
        reply = self._converse(system, messages)
        error, rows, query, explanation = None, None, "", ""
        for attempt in range(2):
            try:
                query, explanation = extract_sparql(reply)
                query = ensure_read_only(query, MAX_ROWS)
                check_syntax(query)
                rows = self.execute(query)
                error = None
                break
            except SparqlError as exc:
                error = str(exc)
                if attempt == 0 and time.monotonic() - started < RETRY_BUDGET_S:
                    messages += [{"role": "assistant", "content": [{"text": reply}]},
                                 {"role": "user", "content": [{"text":
                                  f"That query failed: {error}\nReturn a corrected query."}]}]
                    reply = self._converse(system, messages)
                else:
                    break
        if error:
            return {"question": question, "sparql": query, "explanation": explanation,
                    "error": error, "rows": [], "answer": None, "model": self.model_id}
        if time.monotonic() - started > SUMMARY_BUDGET_S:
            return {"question": question, "sparql": query, "explanation": explanation,
                    "rows": rows, "answer": None, "model": self.model_id}
        answer = self._converse(
            "You answer warranty analysts. Use only the numbers and names in the query results. "
            "Two or three plain sentences. If the results are empty, say what was searched for "
            "and that nothing matched.",
            [{"role": "user", "content": [{"text":
              f"Question: {question}\n\nSPARQL:\n{query}\n\nResults ({len(rows)} rows, first 40):\n"
              f"{json.dumps(rows[:40], default=str)}"}]}], max_tokens=400)
        return {"question": question, "sparql": query, "explanation": explanation,
                "rows": rows, "answer": answer.strip(), "model": self.model_id}
