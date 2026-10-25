"""Warranty Claim Explorer API: the read-only queries behind the relationship explorer UI.

Pure logic over any SPARQL client with a `select()` method (NeptuneSparql in Lambda,
LocalSparql in tests and the local server). The HTTP wiring is in functions/explorer_api.

Routes (all GET unless noted, all under /api):
    /stats                          entity counts and total claim cost
    /search?q=water pump            claims, VINs, parts, dealers, suppliers, ROs, customers
    /entities?type=claim&offset=0   paged list of one entity type
    /entity?iri=...                 attributes of one entity
    /neighborhood?iri=...           connected entities, grouped by relationship (graph view)
    /related?iri=<claim IRI>        the "Related information" panel (built on cq01 + cq03)
    /competency                     the competency questions
    /competency/cq03?claimNumber=.. run one competency question
"""

from __future__ import annotations

import re
import time

from warranty_kg import competency
from warranty_kg.namespaces import (BY_CLASS, BY_KEY, ENTITY_TYPES, RDFS, SKOS, WKO,
                                    parse_iri, sparql_prefixes)

PFX = sparql_prefixes()
ENTITY_VALUES = " ".join(f"wko:{t.cls}" for t in ENTITY_TYPES)
_SAFE_TEXT = re.compile(r"[^\w\s\-.,&'/]", re.UNICODE)
HIDDEN_PREDICATES = {SKOS + "broaderTransitive", SKOS + "topConceptOf", SKOS + "inScheme",
                     SKOS + "hasTopConcept"}
PER_RELATION = 12
# For transactional records (a claim, a repair order) the useful picture is two hops wide:
# the claim's part -> its supplier, the vehicle -> its owner. Mirrors the explorer mockup.
SECOND_HOP = {"claim": ("suppliedBy", "ownedBy"), "repairOrder": ("ownedBy", "suppliedBy")}

ATTRIBUTE_ORDER = [
    "claimNumber", "vin", "partNumber", "dealerCode", "supplierCode", "roNumber", "customerId",
    "categoryCode", "claimDate", "failureCode", "complaint", "cause", "correction",
    "mileageAtClaim", "monthsInService", "laborHours", "laborCost", "partsCost", "totalCost",
    "make", "model", "modelYear", "trim", "engine", "assemblyPlant", "buildDate",
    "inServiceDate", "openDate", "closeDate", "mileageIn", "laborOperation", "payType",
    "unitCost", "standardLaborHours", "city", "state", "region", "country",
]


def select_vars(query: str) -> list[str]:
    """Projected variable names of a SELECT, in order: ?x at the top level and (expr AS ?y)."""
    m = re.search(r"\bSELECT\s+(?:DISTINCT\s+|REDUCED\s+)?(.*?)\bWHERE\b", query, re.S | re.I)
    if not m:
        return []
    clause, out, depth, i = m.group(1), [], 0, 0
    for tok in re.finditer(r"\(|\)|\bAS\s+\?(\w+)|\?(\w+)", clause, re.I):
        if tok.group(0) == "(":
            depth += 1
        elif tok.group(0) == ")":
            depth -= 1
        elif tok.group(1) and depth == 1:
            out.append(tok.group(1))
        elif tok.group(2) and depth == 0:
            out.append(tok.group(2))
    return list(dict.fromkeys(out))


class NotFound(LookupError):
    pass


def lit(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_iri(value: str | None) -> str:
    if not value or not parse_iri(value):
        raise ValueError("iri must be a warranty entity IRI (https://warranty.example.com/id/...)")
    if any(c in value for c in '<>"{}|^`\\ '):
        raise ValueError("invalid IRI")
    return value


def _local(iri: str) -> str:
    return iri.split("#")[-1].split("/")[-1]


class Explorer:
    def __init__(self, sparql, cq_dir=None):
        self.sparql = sparql
        self.questions = competency.load_all(cq_dir)

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        rows = self.sparql.select(PFX + f"""
SELECT ?type (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  VALUES ?type {{ {ENTITY_VALUES} }}
  ?s a ?type .
}} GROUP BY ?type""")
        counts = {BY_CLASS[r["type"]].key: r["n"] for r in rows if r["type"] in BY_CLASS}
        cost = self.sparql.select(PFX + """
SELECT (SUM(?c) AS ?total) WHERE { ?claim a wko:WarrantyClaim ; wko:totalCost ?c }""")
        triples = self.sparql.select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
        return {"counts": {t.key: counts.get(t.key, 0) for t in ENTITY_TYPES},
                "totalClaimCost": round(float(cost[0].get("total", 0) or 0), 2) if cost else 0,
                "triples": triples[0]["n"] if triples else 0,
                "types": [{"key": t.key, "label": t.label, "plural": t.plural}
                          for t in ENTITY_TYPES]}

    # ------------------------------------------------------------------ search
    def search(self, q: str, limit: int = 20) -> dict:
        text = _SAFE_TEXT.sub("", (q or "")).strip().lower()[:60]
        if len(text) < 2:
            raise ValueError("search text must be at least 2 characters")
        # Two steps: match text first (cheap), then describe only the matches.
        matches = self.sparql.select(PFX + f"""
SELECT DISTINCT ?s WHERE {{
  {{ ?s wko:identifier ?text }} UNION {{ ?s rdfs:label ?text }}
  FILTER(CONTAINS(LCASE(STR(?text)), {lit(text)}))
}} LIMIT 300""")
        subjects = [m["s"] for m in matches if parse_iri(m["s"])]
        rows = []
        if subjects:
            values = " ".join(f"<{x}>" for x in subjects)
            rows = self.sparql.select(PFX + f"""
SELECT ?s ?type ?label ?id WHERE {{
  VALUES ?s {{ {values} }}
  ?s a ?type .
  FILTER(?type IN ({", ".join(f"wko:{t.cls}" for t in ENTITY_TYPES)}))
  OPTIONAL {{ ?s rdfs:label ?label }}
  OPTIONAL {{ ?s wko:identifier ?id }}
}}""")
        seen, hits = set(), []
        order = {t.key: i for i, t in enumerate(ENTITY_TYPES)}
        for r in rows:
            if r["s"] in seen:
                continue
            seen.add(r["s"])
            t = BY_CLASS[r["type"]]
            ident = str(r.get("id", ""))
            label = str(r.get("label", ident))
            exact = text in (ident.lower(), label.lower())
            starts = ident.lower().startswith(text) or label.lower().startswith(text)
            hits.append({"iri": r["s"], "type": t.key, "typeLabel": t.label, "label": label,
                         "identifier": ident,
                         "_rank": (0 if exact else 1 if starts else 2, order[t.key], label)})
        hits.sort(key=lambda h: h["_rank"])
        for h in hits:
            h.pop("_rank")
        return {"query": text, "results": hits[:limit], "more": len(hits) > limit}

    # ------------------------------------------------------------------ lists
    LISTS = {
        "claim": ("?claimNumber ?claimDate ?status ?vin ?dealer ?part ?totalCost", """
  ?s wko:claimNumber ?claimNumber ; wko:claimDate ?claimDate ; wko:totalCost ?totalCost ;
     wko:hasStatus/rdfs:label ?status ; wko:claimForVehicle/wko:vin ?vin ;
     wko:submittedBy/rdfs:label ?dealer ; wko:referencesPart/rdfs:label ?part .""",
                  "DESC(?claimDate)"),
        "vehicle": ("?vin ?label ?assemblyPlant ?buildDate ?claims", """
  ?s wko:vin ?vin ; rdfs:label ?label ; wko:assemblyPlant ?assemblyPlant ; wko:buildDate ?buildDate .
  { SELECT ?s (COUNT(?c) AS ?claims) WHERE { ?s a wko:Vehicle . OPTIONAL { ?s wko:hasClaim ?c } } GROUP BY ?s }""",
                    "DESC(?claims) ?vin"),
        "part": ("?partNumber ?label ?category ?supplier ?claims", """
  ?s wko:partNumber ?partNumber ; rdfs:label ?label ; wko:hasCategory/rdfs:label ?category ;
     wko:suppliedBy/rdfs:label ?supplier .
  { SELECT ?s (COUNT(?c) AS ?claims) WHERE { ?s a wko:Part . OPTIONAL { ?s wko:referencedByClaim ?c } } GROUP BY ?s }""",
                 "DESC(?claims)"),
        "dealer": ("?dealerCode ?label ?city ?state ?region ?claims", """
  ?s wko:dealerCode ?dealerCode ; rdfs:label ?label ; wko:city ?city ; wko:state ?state ; wko:region ?region .
  { SELECT ?s (COUNT(?c) AS ?claims) WHERE { ?s a wko:Dealer . OPTIONAL { ?s wko:submits ?c } } GROUP BY ?s }""",
                   "DESC(?claims)"),
        "repairOrder": ("?roNumber ?openDate ?payType ?laborOperation ?dealer ?vin", """
  ?s wko:roNumber ?roNumber ; wko:openDate ?openDate ; wko:payType ?payType ;
     wko:laborOperation ?laborOperation ; wko:performedBy/rdfs:label ?dealer ;
     wko:repairOrderFor/wko:vin ?vin .""", "DESC(?openDate)"),
        "supplier": ("?supplierCode ?label ?country ?parts ?claims", """
  ?s wko:supplierCode ?supplierCode ; rdfs:label ?label ; wko:country ?country .
  { SELECT ?s (COUNT(DISTINCT ?p) AS ?parts) (COUNT(?c) AS ?claims) WHERE {
      ?s a wko:Supplier . OPTIONAL { ?s wko:supplies ?p . OPTIONAL { ?p wko:referencedByClaim ?c } } } GROUP BY ?s }""",
                     "DESC(?claims)"),
        "customer": ("?customerId ?label ?city ?state ?vehicles", """
  ?s wko:customerId ?customerId ; rdfs:label ?label ; wko:city ?city ; wko:state ?state .
  { SELECT ?s (COUNT(?v) AS ?vehicles) WHERE { ?s a wko:Customer . OPTIONAL { ?s wko:owns ?v } } GROUP BY ?s }""",
                     "?customerId"),
        "partCategory": ("?categoryCode ?label ?system", """
  ?s wko:categoryCode ?categoryCode ; rdfs:label ?label .
  OPTIONAL { ?s skos:broader/rdfs:label ?system }""", "?categoryCode"),
    }

    def entities(self, type_key: str, offset: int = 0, limit: int = 50) -> dict:
        if type_key not in self.LISTS:
            raise ValueError(f"type must be one of {sorted(self.LISTS)}")
        offset, limit = max(0, int(offset)), max(1, min(int(limit), 200))
        t = BY_KEY[type_key]
        cols, where, order = self.LISTS[type_key]
        rows = self.sparql.select(PFX + f"""
SELECT ?s {cols} WHERE {{
  ?s a wko:{t.cls} .{where}
}} ORDER BY {order} LIMIT {limit} OFFSET {offset}""")
        total = self.sparql.select(PFX + f"SELECT (COUNT(?s) AS ?n) WHERE {{ ?s a wko:{t.cls} }}")
        columns = [c.lstrip("?") for c in cols.split()]
        return {"type": type_key, "label": t.plural, "columns": columns,
                "total": total[0]["n"] if total else 0, "offset": offset, "limit": limit,
                "rows": [{"iri": r.pop("s"), **r} for r in rows]}

    # ------------------------------------------------------------------ one entity
    def entity(self, iri: str) -> dict:
        iri = check_iri(iri)
        rows = self.sparql.select(PFX + f"""
SELECT ?p ?o ?plabel WHERE {{
  <{iri}> ?p ?o .
  FILTER(isLiteral(?o))
  OPTIONAL {{ ?p rdfs:label ?plabel }}
}}""")
        types = self.sparql.select(f"SELECT ?t WHERE {{ <{iri}> a ?t }}")
        if not rows and not types:
            raise NotFound(iri)
        t, ident = parse_iri(iri)
        attrs, label = {}, ident
        for r in rows:
            p = r["p"]
            if p == RDFS + "label":
                label = r["o"]
                continue
            if not p.startswith(WKO) or p == WKO + "identifier":
                continue
            name = _local(p)
            attrs.setdefault(name, {"property": name, "label": r.get("plabel", name),
                                    "value": r["o"]})
        order = {n: i for i, n in enumerate(ATTRIBUTE_ORDER)}
        attributes = sorted(attrs.values(), key=lambda a: (order.get(a["property"], 999),
                                                           a["property"]))
        classes = sorted(_local(x["t"]) for x in types if x["t"].startswith(WKO))
        return {"iri": iri, "type": t.key, "typeLabel": t.label, "identifier": ident,
                "label": label, "classes": classes, "attributes": attributes}

    def neighborhood(self, iri: str, per_relation: int = PER_RELATION) -> dict:
        iri = check_iri(iri)
        center = self.entity(iri)
        rows = self.sparql.select(PFX + f"""
SELECT ?p ?plabel ?o ?type ?label WHERE {{
  VALUES ?type {{ {ENTITY_VALUES} }}
  <{iri}> ?p ?o .
  ?o a ?type .
  OPTIONAL {{ ?p rdfs:label ?plabel }}
  OPTIONAL {{ ?o rdfs:label ?label }}
}}""")
        groups: dict[str, dict] = {}
        for r in rows:
            if r["p"] in HIDDEN_PREDICATES or r["o"] == iri:
                continue
            g = groups.setdefault(r["p"], {"predicate": _local(r["p"]),
                                           "label": r.get("plabel", _local(r["p"])),
                                           "total": 0, "nodes": {}})
            if r["o"] not in g["nodes"]:
                g["total"] += 1
                t = BY_CLASS[r["type"]]
                _, ident = parse_iri(r["o"]) or (None, r["o"])
                g["nodes"][r["o"]] = {"iri": r["o"], "type": t.key, "typeLabel": t.label,
                                      "label": r.get("label", ident), "identifier": ident}
        nodes = [{"iri": iri, "type": center["type"], "typeLabel": center["typeLabel"],
                  "label": center["label"], "identifier": center["identifier"],
                  "center": True}]
        edges, relations = [], []
        for pred, g in sorted(groups.items(), key=lambda kv: kv[1]["label"]):
            shown = sorted(g["nodes"].values(), key=lambda n: str(n["label"]))[:per_relation]
            for n in shown:
                nodes.append(n)
                edges.append({"source": iri, "target": n["iri"], "predicate": g["predicate"],
                              "label": g["label"]})
            relations.append({"predicate": g["predicate"], "label": g["label"],
                              "total": g["total"], "shown": len(shown)})
        hop2 = SECOND_HOP.get(center["type"])
        if hop2 and len(nodes) > 1:
            pairs = " ".join(f"(<{n['iri']}> wko:{p})" for n in nodes[1:] for p in hop2)
            extra = self.sparql.select(PFX + f"""
SELECT ?s ?p ?plabel ?o ?type ?label WHERE {{
  VALUES (?s ?p) {{ {pairs} }}
  ?s ?p ?o .
  ?o a ?type .
  FILTER(?type IN ({", ".join(f"wko:{t.cls}" for t in ENTITY_TYPES)}))
  OPTIONAL {{ ?p rdfs:label ?plabel }}
  OPTIONAL {{ ?o rdfs:label ?label }}
}}""")
            known = {n["iri"] for n in nodes}
            for r in extra:
                if r["o"] not in known:
                    known.add(r["o"])
                    t = BY_CLASS[r["type"]]
                    _, ident = parse_iri(r["o"]) or (None, r["o"])
                    nodes.append({"iri": r["o"], "type": t.key, "typeLabel": t.label,
                                  "label": r.get("label", ident), "identifier": ident,
                                  "hop": 2})
                edges.append({"source": r["s"], "target": r["o"], "predicate": _local(r["p"]),
                              "label": r.get("plabel", _local(r["p"])), "hop": 2})
        return {"center": center, "nodes": nodes, "edges": edges, "relations": relations}

    # ------------------------------------------------------------------ related panel
    def related(self, iri: str) -> dict:
        iri = check_iri(iri)
        t, ident = parse_iri(iri)
        if t.key != "claim":
            raise ValueError("related information is available for claims")
        c360 = self.run_question("cq01", {"claimNumber": ident})["rows"]
        if not c360:
            raise NotFound(iri)
        related = self.run_question("cq03", {"claimNumber": ident})["rows"]
        c = c360[0]
        vehicle = self.sparql.select(PFX + f"""
SELECT ?model ?modelYear WHERE {{ <{iri}> wko:claimForVehicle ?v . ?v wko:model ?model ; wko:modelYear ?modelYear }}""")
        v = vehicle[0] if vehicle else {}
        return {
            "claim": c,
            "panel": [
                {"label": "Related claims", "value": len(related)},
                {"label": "Vehicle model", "value": v.get("model")},
                {"label": "Model year", "value": v.get("modelYear")},
                {"label": "Part category", "value": c.get("category")},
                {"label": "Vehicle system", "value": c.get("system")},
                {"label": "Dealer", "value": c.get("dealer")},
                {"label": "Supplier", "value": c.get("supplier")},
            ],
            "relatedClaims": related,
        }

    # ------------------------------------------------------------------ competency questions
    def list_questions(self) -> list[dict]:
        return [q.describe() for q in self.questions.values()]

    def run_question(self, qid: str, params: dict | None = None) -> dict:
        if qid not in self.questions:
            raise NotFound(f"unknown competency question {qid}")
        q = self.questions[qid]
        known = {p.name for p in q.params}
        sparql = q.bind({k: v for k, v in (params or {}).items() if k in known and v != ""})
        start = time.perf_counter()
        rows = self.sparql.select(sparql)
        ms = round((time.perf_counter() - start) * 1000)
        return_cols = select_vars(sparql)
        return {"id": q.id, "title": q.title, "question": q.question, "sparql": sparql,
                "columns": return_cols, "rows": rows, "elapsedMs": ms}
