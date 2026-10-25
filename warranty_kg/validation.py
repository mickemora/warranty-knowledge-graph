"""SHACL validation (pySHACL) plus a vocabulary check against the ontology.

Used by the pipeline's validate step (functions/rdf_tools) and by `scripts/kg.py validate --local`.
"""

from __future__ import annotations

from collections import OrderedDict

from warranty_kg.namespaces import WKO

SEVERITY = {"http://www.w3.org/ns/shacl#Violation": "Violation",
            "http://www.w3.org/ns/shacl#Warning": "Warning",
            "http://www.w3.org/ns/shacl#Info": "Info"}

RESULTS_QUERY = """
PREFIX sh: <http://www.w3.org/ns/shacl#>
SELECT ?focus ?path ?severity ?message ?shape ?value WHERE {
    ?r a sh:ValidationResult ; sh:focusNode ?focus ; sh:resultSeverity ?severity ;
       sh:sourceShape ?shape .
    OPTIONAL { ?r sh:resultPath ?path }
    OPTIONAL { ?r sh:resultMessage ?message }
    OPTIONAL { ?r sh:value ?value }
}"""


def vocabulary_check(data, ontology) -> list[dict]:
    """Every wko: class and property used in the data must be declared in the ontology."""
    from rdflib import RDF as RDF_NS

    declared = {str(s) for s in ontology.subjects(RDF_NS.type) if str(s).startswith(WKO)}
    problems = []
    used_props = {str(p) for p in data.predicates() if str(p).startswith(WKO)}
    used_classes = {str(o) for o in data.objects(None, RDF_NS.type)
                    if str(o).startswith(WKO)}
    for term in sorted((used_props | used_classes) - declared):
        problems.append({"severity": "Violation", "shape": "OntologyVocabulary",
                         "message": f"{term[len(WKO):]} is used in the data but not declared "
                                    "in the ontology", "count": 1, "examples": [term]})
    return problems


def validate(data, shapes, ontology, *, max_examples: int = 5) -> tuple[dict, str]:
    """Validate `data` (rdflib.Graph: instance data + reference data).

    Returns (summary, report_turtle). summary["conforms"] is False only for violations;
    warnings are reported but do not fail validation.
    """
    import pyshacl

    conforms, report, _text = pyshacl.validate(
        data_graph=data, shacl_graph=shapes, ont_graph=None, inference="none",
        abort_on_first=False, allow_warnings=True, advanced=False, meta_shacl=False)

    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for row in report.query(RESULTS_QUERY):
        sev = SEVERITY.get(str(row.severity), str(row.severity))
        path = str(row.path).replace(WKO, "wko:") if row.path is not None else None
        message = str(row.message) if row.message is not None else "constraint failed"
        key = (sev, path, message)
        g = groups.setdefault(key, {"severity": sev, "path": path, "message": message,
                                    "count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < max_examples:
            g["examples"].append(str(row.focus))

    results = list(groups.values()) + vocabulary_check(data, ontology)
    violations = sum(r["count"] for r in results if r["severity"] == "Violation")
    warnings = sum(r["count"] for r in results if r["severity"] == "Warning")
    results.sort(key=lambda r: (r["severity"] != "Violation", -r["count"]))
    summary = {"conforms": violations == 0, "violations": violations, "warnings": warnings,
               "dataTriples": len(data), "results": results}
    return summary, report.serialize(format="turtle")
