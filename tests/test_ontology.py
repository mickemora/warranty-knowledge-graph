"""Ontology, taxonomy and SHACL shapes: they parse, agree with each other and catch bad data."""

from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import OWL, RDF, RDFS, Graph, Namespace  # noqa: E402

from warranty_kg import mapping, validation  # noqa: E402
from warranty_kg.namespaces import ENTITY_TYPES, WKO  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
W = Namespace(WKO)


@pytest.fixture(scope="module")
def ontology():
    return Graph().parse(ROOT / "ontology" / "warranty.ttl")


@pytest.fixture(scope="module")
def shapes():
    return Graph().parse(ROOT / "shapes" / "warranty-shapes.ttl")


@pytest.fixture(scope="module")
def reference():
    return Graph().parse(ROOT / "reference" / "part-taxonomy.ttl")


def test_v1_concepts_and_relationships_are_modelled(ontology):
    """The seven entities and seven relationships on the pilot's v1 conceptual model."""
    for cls in ("Vehicle", "WarrantyClaim", "Dealer", "Part", "Customer", "RepairOrder", "Supplier"):
        assert (W[cls], RDF.type, OWL.Class) in ontology
    for prop, dom, rng in [("hasClaim", "Vehicle", "WarrantyClaim"), ("submits", "Dealer", "WarrantyClaim"),
                           ("referencesPart", "WarrantyClaim", "Part"), ("basedOn", "WarrantyClaim", "RepairOrder"),
                           ("supplies", "Supplier", "Part"), ("owns", "Customer", "Vehicle")]:
        assert (W[prop], RDFS.domain, W[dom]) in ontology
        assert (W[prop], RDFS.range, W[rng]) in ontology


def test_every_property_is_documented(ontology):
    for p in list(ontology.subjects(RDF.type, OWL.ObjectProperty)) + \
             list(ontology.subjects(RDF.type, OWL.DatatypeProperty)):
        assert ontology.value(p, RDFS.label), p
        if p != W.identifier:
            assert ontology.value(p, RDFS.domain), p
            assert ontology.value(p, RDFS.range), p


def test_inverse_pairs_have_matching_domains(ontology):
    for p, inv in ontology.subject_objects(OWL.inverseOf):
        assert ontology.value(p, RDFS.domain) == ontology.value(inv, RDFS.range), p
        assert ontology.value(p, RDFS.range) == ontology.value(inv, RDFS.domain), p


def test_entity_registry_matches_ontology(ontology):
    for t in ENTITY_TYPES:
        assert (W[t.cls], RDF.type, OWL.Class) in ontology
        assert (W[t.id_prop], RDFS.subPropertyOf, W.identifier) in ontology


def test_taxonomy_is_two_levels(reference):
    cats = set(reference.subjects(RDF.type, W.PartCategory))
    tops = {c for c in cats if (c, SKOS.broader, None) not in reference}
    assert len(tops) == 5
    for c in cats - tops:
        assert reference.value(c, SKOS.broader) in tops


def test_data_uses_only_declared_vocabulary(generated, ontology):
    data, _ = mapping.to_graph(mapping.read_dir(generated[1] / "raw"))
    assert validation.vocabulary_check(data, ontology) == []


def test_shapes_target_every_entity_class(shapes):
    targets = set(shapes.objects(None, Namespace("http://www.w3.org/ns/shacl#").targetClass))
    for cls in ("WarrantyClaim", "Vehicle", "Dealer", "Customer", "Supplier", "Part", "RepairOrder"):
        assert W[cls] in targets


def _validate(raw_dir, shapes, ontology, reference):
    data, _ = mapping.to_graph(mapping.read_dir(raw_dir))
    for t in reference:
        data.add(t)
    return validation.validate(data, shapes, ontology)


def test_clean_data_conforms(generated, shapes, ontology, reference):
    summary, report = _validate(generated[1] / "raw", shapes, ontology, reference)
    assert summary["conforms"], summary["results"][:3]
    assert summary["violations"] == 0
    assert summary["warnings"] >= 1          # high labor hours at the planted dealer
    assert "ValidationReport" in report


def test_every_injected_defect_is_caught(tmp_path, shapes, ontology, reference):
    from datagen.generate import Generator, inject_defects
    ds = inject_defects(Generator(seed=42).run())
    ds.write(tmp_path)
    summary, _ = _validate(tmp_path / "raw", shapes, ontology, reference)
    assert not summary["conforms"]
    flagged = {ex.rsplit("/", 1)[-1] for r in summary["results"] if r["severity"] == "Violation"
               for ex in r["examples"]}
    for d in ds.defects:
        assert d["record"] in flagged, d
