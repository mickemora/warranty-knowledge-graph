# Week 6: Demonstration and evaluation

**Goal:** show the results, measure them against the success criteria, and decide the next step.

## Demo script (15 minutes)

| Min | Show | Say |
|---|---|---|
| 0 | Infographic (README) | The problem: warranty data in many systems; the pilot: a shared ontology plus a knowledge graph. |
| 2 | Explorer home → search `C-100245` | One claim, and everything it touches, in one view: vehicle, owner, dealer, repair order, part, supplier, vehicle system. |
| 4 | *View Related Claims* | 61 claims on the same part and model. Sorted by build date, they cluster in San Marcos, late 2021. |
| 6 | Competency Questions → CQ09 | October 2021 builds: 73% of vehicles have had the failure. This is a time-bound production or supplier-lot problem, not a design problem. |
| 8 | CQ10 | 75 vehicles from that window have not failed yet. Here are their owners and servicing dealers: the population for a proactive field action. |
| 10 | CQ07 → click D017 → CQ08 | A second pattern: one dealer books 1.6× standard labor and has most of the repeat repairs. |
| 12 | Ask a Question (if NLQ is on) | A question in plain English becomes SPARQL over the same ontology; the query is shown. |
| 13 | Ontology file, SHACL report, pipeline | The reusable foundation: shared definitions, enforced rules, a repeatable pipeline. 100% AWS CDK. |
| 14 | Next-phase options | |

## Success criteria scorecard

| Criterion | Evidence | Met? |
|---|---|---|
| Validated business concepts and relationships | Week 2 glossary and model sign-off | |
| 10 competency questions answered | Week 4 sign-off table; pipeline smoke test | |
| Working knowledge graph with sample data | Successful pipeline run (`kg.py status`) | |
| Business stakeholder demonstration | This demo | |
| Clear path for expansion | Next-phase recommendation below | |

## Impact assessment

| Measure | Today (estimate) | With the explorer | Notes |
|---|---|---|---|
| Time to assemble a claim 360 (CQ01) | | | |
| Time to find related claims (CQ03) | | | |
| Systems touched per investigation | | 1 | |
| Time to scope a build-window population (CQ09 + CQ10) | | | |
| Analyst confidence in definitions (1–5) | | | |

## Lessons learned

| What went well | What to change | Decision / owner |
|---|---|---|
| | | |

## Recommended next phase: options

| Option | What it adds | Builds on |
|---|---|---|
| **Supplier and product quality** | Supplier lots, PPAP/8D records, part changes, supplier recovery; extends CQ05/CQ06/CQ09 | `Supplier`, `Part`, build data |
| **Real data integration** | Replace synthetic CSVs with extracts from the claims, vehicle and dealer systems; keep the same mapping → SHACL → load pipeline | `warranty_kg/mapping.py`, shapes |
| **AI investigation assistant** | An agent that chains competency questions (claim → related → window → at-risk) and drafts the investigation summary | NLQ, competency queries |
| **Predictive analytics** | Early-warning on months-in-service curves per part/population | `monthsInService`, CQ09 |
| **Scale across the enterprise** | Recalls, TSBs, labor operation codes, field reports; governance of the ontology as a shared asset | ontology versioning, named graphs |
