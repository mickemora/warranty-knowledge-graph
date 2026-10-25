"""Transform: source CSV extracts -> RDF that uses the warranty ontology.

This is the "transform" half of the Week 3 load pipeline. It runs in the rdf_tools Lambda
(reading the CSVs from S3) and locally (tests, scripts/serve_local.py). The mapping is plain,
reviewable Python on purpose: each CSV column maps to one ontology property, and anything
derived (months in service) is called out.

Missing or malformed values are not fixed here. They are passed through (or left out) so the
SHACL validation step reports them against the business rules.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from warranty_kg.namespaces import ID, WKO, iri
from warranty_kg.vin import is_valid as vin_is_valid

TABLES = ("suppliers", "parts", "dealers", "customers", "vehicles", "repair_orders", "claims")


def _rdflib():
    import rdflib  # imported lazily: the VPC Lambdas never need it
    return rdflib


def read_tables(texts: Mapping[str, str]) -> dict[str, list[dict]]:
    """{'claims': '<csv text>', ...} -> {'claims': [row, ...], ...}"""
    return {name: list(csv.DictReader(io.StringIO(texts[name]))) for name in TABLES if name in texts}


def read_dir(path) -> dict[str, list[dict]]:
    from pathlib import Path
    p = Path(path)
    return read_tables({n: (p / f"{n}.csv").read_text(encoding="utf-8")
                        for n in TABLES if (p / f"{n}.csv").exists()})


def months_in_service(in_service: str, claim_date: str) -> int | None:
    try:
        a, b = date.fromisoformat(in_service), date.fromisoformat(claim_date)
    except (TypeError, ValueError):
        return None
    months = (b.year - a.year) * 12 + (b.month - a.month)
    return months - (1 if b.day < a.day else 0)


class _Builder:
    def __init__(self):
        rdflib = _rdflib()
        self.rdflib = rdflib
        self.g = rdflib.Graph()
        self.g.bind("wko", WKO)
        self.g.bind("wkd", ID)
        self.g.bind("rdfs", "http://www.w3.org/2000/01/rdf-schema#")
        self.XSD = rdflib.XSD
        self.counts: dict[str, int] = {}

    def node(self, type_key: str, ident: str):
        return self.rdflib.URIRef(iri(type_key, ident))

    def entity(self, type_key: str, cls: str, ident: str, label: str | None):
        s = self.node(type_key, ident)
        self.g.add((s, self.rdflib.RDF.type, self.rdflib.URIRef(WKO + cls)))
        if label:
            self.g.add((s, self.rdflib.RDFS.label, self.rdflib.Literal(label)))
        self.counts[cls] = self.counts.get(cls, 0) + 1
        return s

    def lit(self, s, prop: str, value, kind: str = "string"):
        """Add a literal. Empty values are skipped; unparseable numbers/dates are kept as plain
        strings so SHACL's datatype checks report them instead of the transform crashing."""
        if value is None or str(value).strip() == "":
            return
        v = str(value).strip()
        L, X = self.rdflib.Literal, self.XSD
        lit = L(v)
        try:
            if kind == "integer":
                lit = L(int(v), datatype=X.integer)
            elif kind == "decimal":
                lit = L(Decimal(v), datatype=X.decimal)
            elif kind == "date":
                date.fromisoformat(v)
                lit = L(v, datatype=X.date)
        except (ValueError, InvalidOperation):
            pass
        self.g.add((s, self.rdflib.URIRef(WKO + prop), lit))

    def rel(self, s, prop: str, type_key: str, ident: str | None):
        if ident is None or str(ident).strip() == "":
            return
        self.g.add((s, self.rdflib.URIRef(WKO + prop), self.node(type_key, str(ident).strip())))


def to_graph(tables: Mapping[str, Iterable[dict]]):
    """Build the data graph. Returns (rdflib.Graph, summary dict)."""
    b = _Builder()
    rdflib = b.rdflib
    in_service = {}
    vin_check_failures = []

    for r in tables.get("suppliers", []):
        s = b.entity("supplier", "Supplier", r["supplier_code"], r["name"])
        b.lit(s, "supplierCode", r["supplier_code"])
        b.lit(s, "city", r["city"])
        b.lit(s, "country", r["country"])

    for r in tables.get("parts", []):
        s = b.entity("part", "Part", r["part_number"], r["part_name"])
        b.lit(s, "partNumber", r["part_number"])
        b.lit(s, "unitCost", r["unit_cost"], "decimal")
        b.lit(s, "standardLaborHours", r.get("std_labor_hours"), "decimal")
        b.rel(s, "suppliedBy", "supplier", r["supplier_code"])
        b.rel(s, "hasCategory", "partCategory", r["category_code"])

    for r in tables.get("dealers", []):
        s = b.entity("dealer", "Dealer", r["dealer_code"], r["name"])
        b.lit(s, "dealerCode", r["dealer_code"])
        for col, prop in (("city", "city"), ("state", "state"), ("region", "region")):
            b.lit(s, prop, r[col])

    for r in tables.get("customers", []):
        s = b.entity("customer", "Customer", r["customer_id"], r["name"])
        b.lit(s, "customerId", r["customer_id"])
        b.lit(s, "city", r["city"])
        b.lit(s, "state", r["state"])
        b.rel(s, "preferredDealer", "dealer", r["preferred_dealer_code"])

    for r in tables.get("vehicles", []):
        vin = r["vin"].strip()
        label = f'{r["model_year"]} {r["make"]} {r["model"]} {r["trim"]}'.strip()
        s = b.entity("vehicle", "Vehicle", vin, label)
        b.lit(s, "vin", vin)
        for col, prop in (("make", "make"), ("model", "model"), ("trim", "trim"),
                          ("engine", "engine"), ("assembly_plant", "assemblyPlant")):
            b.lit(s, prop, r[col])
        b.lit(s, "modelYear", r["model_year"], "integer")
        b.lit(s, "buildDate", r["build_date"], "date")
        b.lit(s, "inServiceDate", r["in_service_date"], "date")
        b.rel(s, "sellingDealer", "dealer", r["selling_dealer_code"])
        # The source system records ownership on the vehicle; the ontology states it from the
        # customer's side (Customer owns Vehicle). The inverse is materialized after load.
        if r.get("owner_customer_id"):
            b.g.add((b.node("customer", r["owner_customer_id"]), rdflib.URIRef(WKO + "owns"), s))
        in_service[vin] = r["in_service_date"]
        if not vin_is_valid(vin):
            vin_check_failures.append(vin)

    for r in tables.get("repair_orders", []):
        s = b.entity("repairOrder", "RepairOrder", r["ro_number"], r["ro_number"])
        b.lit(s, "roNumber", r["ro_number"])
        b.rel(s, "repairOrderFor", "vehicle", r["vin"])
        b.rel(s, "performedBy", "dealer", r["dealer_code"])
        b.lit(s, "openDate", r["open_date"], "date")
        b.lit(s, "closeDate", r["close_date"], "date")
        b.lit(s, "mileageIn", r["mileage_in"], "integer")
        b.lit(s, "laborOperation", r["labor_operation"])
        b.lit(s, "payType", r["pay_type"])
        for pn in filter(None, (r.get("replaced_part_numbers") or "").split("|")):
            b.rel(s, "replacedPart", "part", pn)

    status_base = ID + "claim-status/"
    for r in tables.get("claims", []):
        s = b.entity("claim", "WarrantyClaim", r["claim_number"], r["claim_number"])
        b.lit(s, "claimNumber", r["claim_number"])
        b.rel(s, "claimForVehicle", "vehicle", r["vin"])
        b.rel(s, "submittedBy", "dealer", r["dealer_code"])
        b.rel(s, "basedOn", "repairOrder", r["ro_number"])
        b.rel(s, "referencesPart", "part", r["causal_part_number"])
        if r.get("status"):
            b.g.add((s, rdflib.URIRef(WKO + "hasStatus"), rdflib.URIRef(status_base + r["status"])))
        b.lit(s, "claimDate", r["claim_date"], "date")
        for col, prop in (("failure_code", "failureCode"), ("complaint", "complaint"),
                          ("cause", "cause"), ("correction", "correction")):
            b.lit(s, prop, r[col])
        b.lit(s, "mileageAtClaim", r["mileage"], "integer")
        b.lit(s, "laborHours", r["labor_hours"], "decimal")
        for col, prop in (("labor_cost", "laborCost"), ("parts_cost", "partsCost"),
                          ("total_cost", "totalCost")):
            b.lit(s, prop, r[col], "decimal")
        mis = months_in_service(in_service.get(r["vin"]), r["claim_date"])
        if mis is not None:
            b.lit(s, "monthsInService", mis, "integer")

    summary = {"triples": len(b.g), "entities": b.counts,
               "vinCheckDigitFailures": vin_check_failures[:20],
               "vinCheckDigitFailureCount": len(vin_check_failures)}
    return b.g, summary


def to_turtle(tables: Mapping[str, Iterable[dict]]) -> tuple[str, dict]:
    g, summary = to_graph(tables)
    return g.serialize(format="turtle"), summary
