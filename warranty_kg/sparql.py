"""SPARQL clients with one interface, so the same code runs against Neptune and in tests.

    NeptuneSparql   SigV4-signed HTTPS to Neptune's /sparql endpoint (IAM auth)
    LocalSparql     an in-memory rdflib Dataset (tests, scripts/serve_local.py)

Both return rows as plain dicts: IRIs and strings as str, xsd numbers as int/float,
dates as ISO strings. `select()` is read-only by construction on Neptune: queries are sent as
`query=`, and Neptune only runs updates sent as `update=`. `ensure_read_only()` adds a second,
explicit check for any query text that comes from outside the code (NLQ, the CLI).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

XSD = "http://www.w3.org/2001/XMLSchema#"
_INT = {XSD + t for t in ("integer", "int", "long", "short", "byte", "nonNegativeInteger",
                          "positiveInteger", "negativeInteger", "nonPositiveInteger",
                          "unsignedInt", "unsignedLong")}
_FLOAT = {XSD + t for t in ("decimal", "double", "float")}


def _convert(value: str, datatype: str | None):
    if datatype in _INT:
        try:
            return int(value)
        except ValueError:
            return value
    if datatype in _FLOAT:
        try:
            return float(value)
        except ValueError:
            return value
    if datatype == XSD + "boolean":
        return value in ("true", "1")
    return value


def rows_from_json(doc: dict) -> list[dict]:
    """SPARQL 1.1 JSON results -> list of plain dicts."""
    out = []
    for b in doc.get("results", {}).get("bindings", []):
        out.append({k: (v["value"] if v["type"] != "literal"
                        else _convert(v["value"], v.get("datatype")))
                    for k, v in b.items()})
    return out


class SparqlError(RuntimeError):
    pass


# --------------------------------------------------------------------------- read-only guard

_STRINGS = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_IRIS = re.compile(r"<[^<>\s]*>")
_COMMENTS = re.compile(r"#[^\n]*")
_FORBIDDEN = re.compile(
    r"\b(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY|WITH|SERVICE)\b", re.I)
_FORM = re.compile(r"\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", re.I)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*(OFFSET\s+\d+\s*)?$", re.I)


def ensure_read_only(query: str, max_rows: int = 200) -> str:
    """Reject anything but a single read query (no updates, no SERVICE federation) and make
    sure a SELECT returns at most `max_rows` rows. Returns the (possibly limited) query."""
    stripped = _COMMENTS.sub(" ", _IRIS.sub("<>", _STRINGS.sub('""', query)))
    bad = _FORBIDDEN.search(stripped)
    if bad:
        raise SparqlError(f"only read queries are allowed (found {bad.group(1).upper()})")
    form = _FORM.search(stripped)
    if not form:
        raise SparqlError("query must be a SELECT, ASK, CONSTRUCT or DESCRIBE")
    if form.group(1).upper() == "SELECT":
        q = query.rstrip().rstrip(";")
        m = _LIMIT.search(_COMMENTS.sub("", q).rstrip())
        if not m:
            return f"{q}\nLIMIT {max_rows}"
        if int(m.group(1)) > max_rows:
            return re.sub(r"\bLIMIT\s+\d+", f"LIMIT {max_rows}", q, count=1, flags=re.I)
        return q
    return query


# --------------------------------------------------------------------------- Neptune

class NeptuneSparql:
    """Minimal SigV4 SPARQL client. Needs botocore (present in the Lambda runtime)."""

    def __init__(self, endpoint: str | None = None, port: str | int | None = None,
                 region: str | None = None, timeout: int = 60):
        self.endpoint = endpoint or os.environ["NEPTUNE_ENDPOINT"]
        self.port = str(port or os.environ.get("NEPTUNE_PORT", "8182"))
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.url = f"https://{self.endpoint}:{self.port}/sparql"
        self.timeout = timeout

    def _post(self, form: dict, accept: str = "application/sparql-results+json") -> dict:
        import botocore.session
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        body = urllib.parse.urlencode(form)
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": accept}
        req = AWSRequest(method="POST", url=self.url, data=body, headers=headers)
        creds = botocore.session.get_session().get_credentials().get_frozen_credentials()
        SigV4Auth(creds, "neptune-db", self.region).add_auth(req)
        http = urllib.request.Request(self.url, data=body.encode(), method="POST",
                                      headers=dict(req.headers.items()))
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                doc = json.loads(detail)
                detail = f'{doc.get("code")}: {doc.get("detailedMessage")}'
            except ValueError:
                pass
            raise SparqlError(f"Neptune returned {exc.code}: {detail}") from None
        return json.loads(text) if text.strip() else {}

    def select(self, query: str) -> list[dict]:
        return rows_from_json(self._post({"query": query}))

    def ask(self, query: str) -> bool:
        return bool(self._post({"query": query}).get("boolean"))

    def update(self, update: str) -> dict:
        return self._post({"update": update}, accept="application/json")


# --------------------------------------------------------------------------- local

class LocalSparql:
    """rdflib-backed stand-in for Neptune. The default graph is the union of named graphs,
    as in Neptune."""

    def __init__(self, dataset=None):
        from rdflib import Dataset
        self.ds = dataset if dataset is not None else Dataset(default_union=True)

    def graph(self, name: str):
        from rdflib import URIRef
        return self.ds.graph(URIRef(name))

    def select(self, query: str) -> list[dict]:
        from rdflib import BNode, Literal
        res = self.ds.query(query)
        out = []
        for row in res:
            d = {}
            for var in res.vars:
                v = row[var]
                if v is None:
                    continue
                if isinstance(v, Literal):
                    d[str(var)] = _convert(str(v), str(v.datatype) if v.datatype else None)
                elif isinstance(v, BNode):
                    d[str(var)] = f"_:{v}"
                else:
                    d[str(var)] = str(v)
            out.append(d)
        return out

    def ask(self, query: str) -> bool:
        return bool(self.ds.query(query).askAnswer)

    def update(self, update: str) -> dict:
        self.ds.update(update)
        return {}
