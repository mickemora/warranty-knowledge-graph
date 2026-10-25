"""Command line for the warranty knowledge graph.

Deployed (uses your AWS credentials and the stack outputs):
    python scripts/kg.py pipeline              # run transform -> validate -> load -> materialize -> test
    python scripts/kg.py status                # recent pipeline runs
    python scripts/kg.py report                # latest SHACL data-quality report
    python scripts/kg.py diagnose              # Neptune reachability, load jobs, triples per graph
    python scripts/kg.py cq list
    python scripts/kg.py cq run cq03 --param claimNumber=C-100245
    python scripts/kg.py sparql "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    python scripts/kg.py nlq "Which dealers have the most water pump claims?"
    python scripts/kg.py url                   # the explorer's CloudFront URL

Local (no AWS: in-memory graph built from data/generated):
    python scripts/kg.py validate --local [--raw DIR]
    python scripts/kg.py cq run cq09 --local
    python scripts/kg.py sparql --local "SELECT ..."
    python scripts/kg.py cq report --local     # writes docs/competency-results.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORE_STACK, APP_STACK = "WarrantyKgCoreStack", "WarrantyKgAppStack"


# --------------------------------------------------------------------------- output helpers

def print_table(rows: list[dict], columns: list[str] | None = None, limit: int = 40) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = columns or list(dict.fromkeys(k for r in rows for k in r))
    shown = rows[:limit]
    def cell(v):
        s = "" if v is None else (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
        return s if len(s) <= 40 else s[:39] + "…"
    widths = {c: max(len(c), *(len(cell(r.get(c))) for r in shown)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in shown:
        print("  ".join(cell(r.get(c)).ljust(widths[c]) for c in cols))
    if len(rows) > limit:
        print(f"... {len(rows) - limit} more rows (use --json for all)")


def parse_params(pairs: list[str] | None) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k] = v
    return out


# --------------------------------------------------------------------------- AWS helpers

_outputs: dict | None = None


def outputs() -> dict:
    global _outputs
    if _outputs is None:
        import boto3
        cfn = boto3.client("cloudformation")
        _outputs = {}
        for name in (CORE_STACK, APP_STACK):
            try:
                stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
            except cfn.exceptions.ClientError:
                continue
            _outputs.update({o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])})
        if not _outputs:
            sys.exit(f"Stacks {CORE_STACK} / {APP_STACK} not found. Deploy first (cdk deploy --all), "
                     "or use --local.")
    return _outputs


def invoke(function_key: str, payload: dict):
    import boto3
    resp = boto3.client("lambda").invoke(FunctionName=outputs()[function_key],
                                         Payload=json.dumps(payload).encode())
    body = json.loads(resp["Payload"].read() or b"null")
    if resp.get("FunctionError"):
        sys.exit(f"{function_key} failed: {body.get('errorMessage')}")
    return body


def explorer_get(path: str, params: dict | None = None):
    resp = invoke("ExplorerFunctionName", {"rawPath": "/api" + path,
                                           "queryStringParameters": params or {},
                                           "requestContext": {"http": {"method": "GET"}}})
    body = json.loads(resp["body"])
    if resp["statusCode"] != 200:
        sys.exit(f"error {resp['statusCode']}: {body.get('error')}")
    return body


# --------------------------------------------------------------------------- local helpers

_local_explorer = None


def local_explorer():
    global _local_explorer
    if _local_explorer is None:
        from warranty_kg import local
        from warranty_kg.explorer import Explorer
        print("(building the in-memory graph…)", file=sys.stderr)
        _local_explorer = Explorer(local.build())
    return _local_explorer


# --------------------------------------------------------------------------- commands

def cmd_pipeline(args):
    import boto3
    sfn = boto3.client("stepfunctions")
    arn = sfn.start_execution(stateMachineArn=outputs()["StateMachineArn"],
                              input=json.dumps({"trigger": "cli"}))["executionArn"]
    print(f"Started {arn.split(':')[-1]}")
    if args.no_wait:
        return
    last = None
    while True:
        desc = sfn.describe_execution(executionArn=arn)
        events = sfn.get_execution_history(executionArn=arn, reverseOrder=True, maxResults=5)["events"]
        step = next((e["stateEnteredEventDetails"]["name"] for e in events
                     if "stateEnteredEventDetails" in e), None)
        if step and step != last:
            print(f"  {time.strftime('%H:%M:%S')}  {step}")
            last = step
        if desc["status"] != "RUNNING":
            break
        time.sleep(5)
    print(f"Pipeline {desc['status']}")
    if desc["status"] == "SUCCEEDED":
        out = json.loads(desc["output"])
        v = out.get("validation", {})
        print(f"  SHACL: {v.get('violations')} violations, {v.get('warnings')} warnings "
              f"(s3://{outputs()['DataBucketName']}/{v.get('reportKey')})")
        print("  Triples per graph:")
        for g, n in out.get("materialize", {}).get("graphs", {}).items():
            print(f"    {g.rsplit('/', 1)[-1]:<10} {n:>8,}")
        print("  Competency questions:")
        print_table(out.get("smokeTest", {}).get("questions", []), ["id", "title", "rows", "seconds"])
    else:
        print(json.dumps({k: desc.get(k) for k in ("error", "cause")}, indent=2))
        if "Data quality" in (desc.get("cause") or "") or desc.get("error") == "DataQualityViolations":
            print("Run `python scripts/kg.py report` for the violations.")


def cmd_status(_args):
    import boto3
    sfn = boto3.client("stepfunctions")
    runs = sfn.list_executions(stateMachineArn=outputs()["StateMachineArn"], maxResults=8)["executions"]
    print_table([{"name": r["name"][:36], "status": r["status"],
                  "started": r["startDate"].strftime("%Y-%m-%d %H:%M"),
                  "stopped": r.get("stopDate").strftime("%H:%M") if r.get("stopDate") else ""}
                 for r in runs])


def cmd_report(_args):
    import boto3
    body = boto3.client("s3").get_object(Bucket=outputs()["DataBucketName"],
                                         Key="reports/latest.json")["Body"].read()
    print_validation(json.loads(body))


def print_validation(summary: dict):
    status = "CONFORMS" if summary["conforms"] else "DOES NOT CONFORM"
    print(f"{status}: {summary['violations']} violations, {summary['warnings']} warnings, "
          f"{summary.get('dataTriples', 0):,} data triples")
    rows = [{"severity": r["severity"], "count": r["count"], "path": r.get("path") or "",
             "message": r["message"], "example": (r["examples"] or [""])[0].rsplit("/", 1)[-1]}
            for r in summary["results"]]
    print_table(rows, ["severity", "count", "path", "message", "example"], limit=100)


def cmd_validate(args):
    if not args.local:
        sys.exit("validate runs locally (--local). In AWS, validation is a pipeline step: "
                 "`kg.py pipeline`, then `kg.py report`.")
    from rdflib import Graph

    from warranty_kg import local, mapping, validation
    raw = Path(args.raw) if args.raw else local.ensure_dataset() / "raw"
    data, summary = mapping.to_graph(mapping.read_dir(raw))
    for ttl in (ROOT / "reference").glob("*.ttl"):
        data.parse(ttl, format="turtle")
    shapes = Graph().parse(ROOT / "shapes" / "warranty-shapes.ttl", format="turtle")
    ontology = Graph().parse(ROOT / "ontology" / "warranty.ttl", format="turtle")
    print(f"Transformed {raw}: {summary['triples']:,} triples, "
          f"{summary['vinCheckDigitFailureCount']} VIN check-digit failures")
    result, report = validation.validate(data, shapes, ontology)
    print_validation(result)
    if args.report:
        Path(args.report).write_text(report)
        print(f"SHACL report written to {args.report}")
    sys.exit(0 if result["conforms"] else 1)


def cmd_diagnose(_args):
    print(json.dumps(invoke("AdminFunctionName", {"action": "diagnose"}), indent=2, default=str))


def cmd_sparql(args):
    if args.local:
        from warranty_kg.sparql import ensure_read_only
        rows = local_explorer().sparql.select(ensure_read_only(args.query, 500))
    else:
        rows = invoke("AdminFunctionName", {"action": "sparql", "query": args.query})
    print(json.dumps(rows, indent=2, default=str)) if args.json else print_table(rows)


def cmd_cq(args):
    if args.cq_cmd == "list":
        from warranty_kg import competency
        for q in competency.load_all().values():
            params = ", ".join(f"{p.name}={p.default}" for p in q.params)
            print(f"{q.id}  {q.title}\n      {q.question}" + (f"\n      params: {params}" if params else ""))
        return
    if args.cq_cmd == "report":
        return cq_report(args)
    params = parse_params(args.param)
    result = (local_explorer().run_question(args.id, params) if args.local
              else explorer_get(f"/competency/{args.id}", params))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(f"{result['id'].upper()}  {result['title']}\n{result['question']}\n")
    print_table(result["rows"], result["columns"])
    print(f"\n{len(result['rows'])} rows in {result['elapsedMs']} ms")


def cq_report(args):
    """Run every competency question locally and write the results as Markdown (Week 4)."""
    if not args.local:
        sys.exit("cq report runs against the local graph: add --local")
    ex = local_explorer()
    lines = ["# Competency question results", "",
             "Generated by `python scripts/kg.py cq report --local` from the synthetic dataset "
             "(seed 42). Each question's SPARQL is in `queries/competency/`.", ""]
    for q in ex.questions.values():
        r = ex.run_question(q.id)
        lines += [f"## {q.id.upper()}: {q.title}", "", f"**Question:** {q.question}", "",
                  f"**Why it matters:** {q.value}", ""]
        if q.params:
            lines += ["**Parameters:** " + ", ".join(f"`{p.name}={p.default}`" for p in q.params), ""]
        cols, rows = r["columns"], r["rows"]
        lines += [f"{len(rows)} rows. First {min(len(rows), 8)}:", "",
                  "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in rows[:8]:
            lines.append("| " + " | ".join(str(row.get(c, "")).replace("|", "/") for c in cols) + " |")
        lines.append("")
    out = Path(args.out)
    out.write_text("\n".join(lines))
    print(f"Wrote {out}")


def cmd_nlq(args):
    resp = invoke("NlqFunctionName", {"body": json.dumps({"question": args.question})})
    body = json.loads(resp["body"])
    if resp["statusCode"] != 200:
        sys.exit(f"error: {body.get('error')}")
    if args.json:
        print(json.dumps(body, indent=2, default=str))
        return
    print(body.get("answer") or body.get("error") or "")
    print("\nSPARQL:\n" + (body.get("sparql") or ""))
    print()
    print_table(body.get("rows") or [])


def cmd_url(_args):
    print(outputs()["ExplorerUrl"])


def main():
    ap = argparse.ArgumentParser(description="Warranty knowledge graph CLI",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pipeline", help="run the load pipeline")
    p.add_argument("--no-wait", action="store_true")
    sub.add_parser("status", help="recent pipeline runs")
    sub.add_parser("report", help="latest SHACL validation report")
    sub.add_parser("diagnose", help="Neptune and loader diagnostics")
    sub.add_parser("url", help="print the explorer URL")
    p = sub.add_parser("validate", help="SHACL-validate a dataset locally")
    p.add_argument("--local", action="store_true")
    p.add_argument("--raw", help="directory of CSVs (default data/generated/raw)")
    p.add_argument("--report", help="write the SHACL report (Turtle) here")
    p = sub.add_parser("sparql", help="run a read-only SPARQL query")
    p.add_argument("query")
    p.add_argument("--local", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("nlq", help="ask a natural-language question (Bedrock)")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("cq", help="competency questions")
    cq = p.add_subparsers(dest="cq_cmd", required=True)
    cq.add_parser("list")
    r = cq.add_parser("run")
    r.add_argument("id")
    r.add_argument("--param", action="append", help="name=value (repeatable)")
    r.add_argument("--local", action="store_true")
    r.add_argument("--json", action="store_true")
    r = cq.add_parser("report")
    r.add_argument("--local", action="store_true")
    r.add_argument("--out", default=str(ROOT / "docs" / "competency-results.md"))
    args = ap.parse_args()
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()
