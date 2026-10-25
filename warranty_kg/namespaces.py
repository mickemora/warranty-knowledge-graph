"""Single source of truth for IRIs, named graphs and the business entity types.

Everything that builds or parses an IRI (the CSV-to-RDF mapping, the explorer API, the
competency queries, the UI) goes through this module, so the identifiers stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote

BASE = "https://warranty.example.com/"
WKO = BASE + "ontology#"           # the ontology (classes, properties)
ID = BASE + "id/"                  # instance data
GRAPH = BASE + "graph/"            # named graphs in Neptune

SKOS = "http://www.w3.org/2004/02/skos/core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SH = "http://www.w3.org/ns/shacl#"

# One named graph per source, so each can be reloaded or dropped on its own.
# Neptune's default graph is the union of all named graphs, so queries see everything.
GRAPH_ONTOLOGY = GRAPH + "ontology"     # ontology/warranty.ttl
GRAPH_REFERENCE = GRAPH + "reference"   # reference/*.ttl (part taxonomy, claim statuses)
GRAPH_DATA = GRAPH + "data"             # transformed warranty records
GRAPH_INFERRED = GRAPH + "inferred"     # triples materialized by warranty_kg.rules
ALL_GRAPHS = (GRAPH_ONTOLOGY, GRAPH_REFERENCE, GRAPH_DATA, GRAPH_INFERRED)

PREFIXES = {
    "wko": WKO, "wkd": ID, "skos": SKOS, "rdf": RDF, "rdfs": RDFS,
    "owl": OWL, "xsd": XSD, "sh": SH,
}


def sparql_prefixes(names: tuple[str, ...] = ("wko", "wkd", "skos", "rdf", "rdfs", "xsd")) -> str:
    return "".join(f"PREFIX {n}: <{PREFIXES[n]}>\n" for n in names)


@dataclass(frozen=True)
class EntityType:
    key: str          # API / UI key
    cls: str          # ontology class local name
    path: str         # IRI path segment
    id_prop: str      # identifier property local name
    label: str        # display name (singular)
    plural: str


ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType("claim", "WarrantyClaim", "claim", "claimNumber", "Warranty Claim", "Claims"),
    EntityType("vehicle", "Vehicle", "vehicle", "vin", "Vehicle", "Vehicles"),
    EntityType("part", "Part", "part", "partNumber", "Part", "Parts"),
    EntityType("dealer", "Dealer", "dealer", "dealerCode", "Dealer", "Dealers"),
    EntityType("repairOrder", "RepairOrder", "repair-order", "roNumber", "Repair Order",
               "Repair Orders"),
    EntityType("supplier", "Supplier", "supplier", "supplierCode", "Supplier", "Suppliers"),
    EntityType("customer", "Customer", "customer", "customerId", "Customer", "Customers"),
    EntityType("partCategory", "PartCategory", "part-category", "categoryCode",
               "Part Category", "Part Categories"),
)
BY_KEY = {t.key: t for t in ENTITY_TYPES}
BY_CLASS = {WKO + t.cls: t for t in ENTITY_TYPES}
BY_PATH = {t.path: t for t in ENTITY_TYPES}


def iri(type_key: str, ident: str) -> str:
    """IRI for a business entity, e.g. iri('claim', 'C-100245')."""
    return f"{ID}{BY_KEY[type_key].path}/{quote(str(ident), safe='')}"


def parse_iri(value: str) -> tuple[EntityType, str] | None:
    """Inverse of iri(): returns (type, identifier) or None for non-entity IRIs."""
    if not value.startswith(ID):
        return None
    path, _, ident = value[len(ID):].partition("/")
    t = BY_PATH.get(path)
    return (t, unquote(ident)) if t and ident else None


def wko(local: str) -> str:
    return WKO + local
