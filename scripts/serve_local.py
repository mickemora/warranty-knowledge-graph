"""Run the Warranty Claim Explorer locally against an in-memory copy of the knowledge graph.

    python scripts/serve_local.py              # http://localhost:8765
    python scripts/serve_local.py --port 9000
    python scripts/serve_local.py --bedrock    # also enable natural-language search (needs
                                               # AWS credentials with Amazon Bedrock access)

No AWS account needed (except for --bedrock): it generates the synthetic dataset if missing,
runs the same CSV-to-RDF mapping and materialization rules as the AWS pipeline, and serves the
same UI and API code the Lambda functions run. Good for SME workshops and for UI work.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from functions.explorer_api.handler import handle_http  # noqa: E402
from warranty_kg import local  # noqa: E402
from warranty_kg.explorer import Explorer  # noqa: E402
from warranty_kg.sparql import ensure_read_only  # noqa: E402

FRONTEND = ROOT / "frontend"
LOCK = threading.Lock()


class LockedSparql:
    """rdflib is not built for concurrent queries; serialize them."""

    def __init__(self, inner):
        self.inner = inner

    def select(self, q):
        with LOCK:
            return self.inner.select(q)


def make_handler(explorer: Explorer, nlq, config: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WarrantyKG/1.0"

        def log_message(self, fmt, *args):  # quieter than the default
            sys.stderr.write("%s %s\n" % (self.command, self.path))

        def _send(self, status: int, body: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path.startswith("/api/"):
                event = {"rawPath": url.path, "queryStringParameters": dict(parse_qsl(url.query)),
                         "requestContext": {"http": {"method": "GET"}}}
                resp = handle_http(event, explorer)
                return self._send(resp["statusCode"], resp["body"].encode(), "application/json")
            if url.path == "/config.json":
                return self._send(200, json.dumps(config).encode(), "application/json")
            rel = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
            path = (FRONTEND / rel).resolve()
            if not path.is_file() or FRONTEND.resolve() not in path.parents:
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return self._send(200, path.read_bytes(), ctype)

        def do_POST(self):
            if urlsplit(self.path).path != "/api/nlq":
                return self._send(404, b"{}", "application/json")
            if nlq is None:
                return self._send(501, json.dumps({"error": "start with --bedrock to enable"}).encode(),
                                  "application/json")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                question = json.loads(self.rfile.read(length) or b"{}").get("question", "")
                result = nlq.ask(question)
                return self._send(200, json.dumps(result, default=str).encode(), "application/json")
            except Exception as exc:
                return self._send(502, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(),
                                  "application/json")

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--bedrock", action="store_true", help="enable natural-language search")
    ap.add_argument("--model", help="Bedrock model or inference profile ID")
    args = ap.parse_args()

    start = time.time()
    print("Building the knowledge graph in memory…", flush=True)
    kg = local.build()
    sparql = LockedSparql(kg)
    explorer = Explorer(sparql)
    print(f"Ready in {time.time() - start:.1f}s: "
          f"{explorer.stats()['triples']:,} triples", flush=True)

    nlq = None
    if args.bedrock:
        from warranty_kg.nlq import Nlq
        nlq = Nlq(lambda q: sparql.select(ensure_read_only(q, 100)), model_id=args.model)
    config = {"apiBase": "/api", "nlqEnabled": nlq is not None, "environment": "local"}
    server = ThreadingHTTPServer((args.host, args.port), make_handler(explorer, nlq, config))
    print(f"Warranty Claim Explorer: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
