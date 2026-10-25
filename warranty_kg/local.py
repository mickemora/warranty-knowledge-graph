"""Build the whole knowledge graph in memory: the same four named graphs as in Neptune,
with the materialization rules applied. Used by tests, `scripts/serve_local.py` and
`scripts/kg.py ... --local`, so everything can be tried without an AWS account."""

from __future__ import annotations

from pathlib import Path

from warranty_kg import mapping, rules
from warranty_kg.namespaces import GRAPH_DATA, GRAPH_ONTOLOGY, GRAPH_REFERENCE
from warranty_kg.sparql import LocalSparql

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "data" / "generated"


def ensure_dataset(out: Path = GENERATED, seed: int = 42) -> Path:
    if not (out / "manifest.json").exists():
        from datagen.generate import Generator
        Generator(seed).run().write(out)
    return out


def build(raw_dir: Path | None = None, *, materialize: bool = True) -> LocalSparql:
    raw_dir = Path(raw_dir) if raw_dir else ensure_dataset() / "raw"
    kg = LocalSparql()
    kg.graph(GRAPH_ONTOLOGY).parse(ROOT / "ontology" / "warranty.ttl", format="turtle")
    for ttl in sorted((ROOT / "reference").glob("*.ttl")):
        kg.graph(GRAPH_REFERENCE).parse(ttl, format="turtle")
    data, _ = mapping.to_graph(mapping.read_dir(raw_dir))
    target = kg.graph(GRAPH_DATA)
    for triple in data:
        target.add(triple)
    if materialize:
        for _name, update in rules.RULES:
            kg.update(update)
    return kg
