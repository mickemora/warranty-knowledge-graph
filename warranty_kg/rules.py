"""Materialization rules: the inferences the ontology implies, written as SPARQL UPDATE.

Each rule only inserts triples that are not already in the graph, so the inferred graph holds
exactly what reasoning added and running the rules again changes nothing.

Neptune stores RDF and answers SPARQL, but it does not run an OWL/RDFS reasoner. So after each
load the pipeline runs these updates once and writes the results into their own named graph
(GRAPH_INFERRED). Dropping that graph removes every inferred triple; rerunning the rules
rebuilds it. The same updates run against rdflib locally, so tests prove what they produce.

The rules are a small, explicit subset of RDFS / OWL 2 RL, chosen because the explorer and the
competency questions depend on them:

  inverse-of         owl:inverseOf pairs in both directions (Customer owns Vehicle -> Vehicle ownedBy Customer)
  sub-property       rdfs:subPropertyOf (every business key is also a wko:identifier)
  sub-class          rdfs:subClassOf+  (a Dealer is also an Organization, a Party, a BusinessEntity)
  broader-transitive skos:broader+     (Engine Cooling is within Powertrain)
  affects-system     derived: a claim affects the top-level system of its causal part
"""

from __future__ import annotations

from warranty_kg.namespaces import GRAPH_INFERRED, sparql_prefixes

P = sparql_prefixes(("wko", "skos", "rdf", "rdfs")) + "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"

RULES: list[tuple[str, str]] = [
    ("inverse-of (forward)", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?o ?inverse ?s }} }}
WHERE {{
  ?p owl:inverseOf ?inverse .
  ?s ?p ?o .
  FILTER(isIRI(?o))
  FILTER NOT EXISTS {{ ?o ?inverse ?s }}
}}"""),
    ("inverse-of (backward)", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?o ?p ?s }} }}
WHERE {{
  ?p owl:inverseOf ?inverse .
  ?s ?inverse ?o .
  FILTER(isIRI(?o))
  FILTER NOT EXISTS {{ ?o ?p ?s }}
}}"""),
    ("sub-property", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?s ?super ?o }} }}
WHERE {{
  ?p rdfs:subPropertyOf+ ?super .
  FILTER(STRSTARTS(STR(?p), STR(wko:)))
  ?s ?p ?o .
  FILTER NOT EXISTS {{ ?s ?super ?o }}
}}"""),
    ("sub-class", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?s a ?super }} }}
WHERE {{
  ?cls rdfs:subClassOf+ ?super .
  FILTER(STRSTARTS(STR(?cls), STR(wko:)))
  ?s a ?cls .
  FILTER NOT EXISTS {{ ?s a ?super }}
}}"""),
    ("broader-transitive", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?c skos:broaderTransitive ?b }} }}
WHERE {{
  ?c skos:broader+ ?b .
  FILTER NOT EXISTS {{ ?c skos:broaderTransitive ?b }}
}}"""),
    ("affects-system", P + f"""
INSERT {{ GRAPH <{GRAPH_INFERRED}> {{ ?claim wko:affectsSystem ?system }} }}
WHERE {{
  ?claim a wko:WarrantyClaim ; wko:referencesPart/wko:hasCategory ?cat .
  ?cat skos:broader* ?system .
  FILTER NOT EXISTS {{ ?system skos:broader ?any }}
}}"""),
]

CLEAR = f"DROP SILENT GRAPH <{GRAPH_INFERRED}>"
COUNT = f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{GRAPH_INFERRED}> {{ ?s ?p ?o }} }}"
