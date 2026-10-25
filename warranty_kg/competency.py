"""Competency questions: the business questions the knowledge graph must answer.

Each question is a standalone, valid SPARQL file in queries/competency/ with a comment header:

    # id: cq01
    # title: Claim 360
    # question: For a claim, which vehicle, dealer, repair order, part and supplier are involved?
    # value: why the business cares
    # param: claimNumber | string | ^C-[0-9]{6}$ | C-100245

Parameters appear in the query as a VALUES clause with the default value, e.g.
    VALUES ?claimNumber { "C-100245" }
so the file runs as-is in a Neptune notebook. bind() swaps in a validated value.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("CQ_DIR") or Path(__file__).resolve().parent.parent / "queries" / "competency")
_HEADER = re.compile(r"^#\s*(\w+):\s*(.*)$")


@dataclass
class Param:
    name: str
    type: str          # string | integer | date
    pattern: str
    default: str

    def literal(self, value: str) -> str:
        value = str(value).strip()
        if not re.fullmatch(self.pattern, value):
            raise ValueError(f"{self.name}={value!r} does not match {self.pattern}")
        if self.type == "integer":
            return str(int(value))
        if self.type == "date":
            return f'"{value}"^^<http://www.w3.org/2001/XMLSchema#date>'
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Question:
    id: str
    title: str
    question: str
    value: str
    text: str
    file: str
    params: list[Param] = field(default_factory=list)

    def bind(self, values: dict | None = None) -> str:
        q = self.text
        for p in self.params:
            v = (values or {}).get(p.name, p.default)
            q, n = re.subn(r"VALUES\s+\?" + p.name + r"\s*\{[^}]*\}",
                           f"VALUES ?{p.name} {{ {p.literal(v)} }}", q, count=1)
            if n != 1:
                raise ValueError(f"{self.id}: no VALUES clause for ?{p.name}")
        return q

    def describe(self) -> dict:
        return {"id": self.id, "title": self.title, "question": self.question,
                "value": self.value, "file": self.file,
                "params": [{"name": p.name, "type": p.type, "pattern": p.pattern,
                            "default": p.default} for p in self.params],
                "sparql": self.text}


def parse(path: Path) -> Question:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = _HEADER.match(line)
        if m:
            meta.setdefault(m.group(1), []).append(m.group(2).strip())
    params = []
    for raw in meta.get("param", []):
        name, typ, pattern, default = [x.strip() for x in raw.split("|")]
        params.append(Param(name, typ, pattern, default))
    return Question(id=meta["id"][0], title=meta["title"][0], question=meta["question"][0],
                    value=" ".join(meta.get("value", [])), text=text, file=path.name,
                    params=params)


def load_all(directory: Path | str | None = None) -> dict[str, Question]:
    d = Path(directory) if directory else DEFAULT_DIR
    qs = [parse(p) for p in sorted(d.glob("cq*.rq"))]
    return {q.id: q for q in qs}
