# Week 1: Business discovery

**Goal:** agree on scope, use case and business requirements.

## Business problem statement

> Warranty information is spread across several systems: claims processing, the vehicle master,
> the dealer network, parts and suppliers. Finding the claims, vehicles, parts and dealers that
> relate to each other takes analysts hours of manual lookups and spreadsheet joins. Emerging
> problems (a supplier lot, a build window, a dealer pattern) are found later than they could be,
> and every team defines "claim", "vehicle population" or "repeat repair" a little differently.

**Target use case: Warranty Claim Relationship Explorer.** Let warranty teams discover and
navigate the relationships among claims, vehicles, dealers, repairs and parts through one shared
business knowledge model.

**In scope for the pilot:** claims, vehicles, dealers, customers (owners), repair orders, parts,
suppliers, the part taxonomy; synthetic data; read-only exploration.
**Out of scope:** connection to production systems, writing back to source systems, cost recovery
workflow, predictive models (see the post-pilot roadmap in Week 6).

## Discovery workshop (2 hours, warranty SMEs)

| Time | Topic | Output |
|---|---|---|
| 0:00 | Introductions, pilot goals, what a knowledge graph is (10-minute demo of `scripts/serve_local.py`) | Shared expectations |
| 0:20 | "Walk us through your last investigation": which systems, which lookups, how long | Pain points, systems list |
| 0:50 | Brainstorm the questions you wish you could answer in one step | Candidate competency questions |
| 1:20 | Prioritize: value × frequency × feasibility with sample data | Top 10 competency questions |
| 1:45 | Success metrics and data approach | Agreed metrics, synthetic-data decision |

## Initial competency questions

The ten questions the ontology and graph must answer. They are the pilot's acceptance tests:
each one is a SPARQL file in [`queries/competency/`](../../queries/competency/), and the load
pipeline runs all ten after every load.

| # | Question | Typical user |
|---|---|---|
| CQ01 | For a given claim, which vehicle, owner, dealer, repair order, causal part, supplier and vehicle system are involved? | Claims analyst |
| CQ02 | What is the full repair and warranty history of a vehicle, in date order? | Field engineer |
| CQ03 | Which other claims name the same causal part on the same model, and when were those vehicles built? | Quality investigator |
| CQ04 | How many claims and how much cost does each vehicle system and part category account for? | Warranty leadership |
| CQ05 | Which suppliers' parts are behind the most warranty claims and cost? | Supplier quality |
| CQ06 | For one supplier, which parts fail on which models, model years and plants, and how early in service? | Supplier quality |
| CQ07 | Which dealers book more labor than the standard time for the parts they replace? | Dealer audit |
| CQ08 | Which vehicles came back with another claim in the same category within 3 months, and where? | Service quality |
| CQ09 | For a part, which model / year / plant / build month has the highest share of vehicles with a claim? | Quality investigator |
| CQ10 | Which vehicles from the suspect build window have not had a claim yet, and who owns them? | Field action planning |

## Success metrics

| Success criterion (infographic) | How it is measured in the pilot |
|---|---|
| Validated business concepts and relationships | Glossary and ontology approved by warranty SMEs (Week 2 sign-off) |
| 10 competency questions answered | All 10 return correct answers; SME sign-off per question (Week 4) |
| Working knowledge graph with sample data | Pipeline run succeeds: SHACL conforms, load completes, smoke test passes |
| Business stakeholder demonstration | Week 6 demo delivered; feedback captured |
| Clear path for expansion | Next-phase recommendation agreed (Week 6) |

Optional quantitative measures: time to answer CQ01/CQ03 today versus in the explorer; number of
systems touched per investigation; analyst confidence (1–5) before and after.

## Data approach

**Decision: synthetic, representative data.** No production data leaves its systems during the
pilot. `datagen/generate.py` produces ~800 claims on ~2,250 vehicles, shaped like real warranty
extracts (one CSV per source table) and seeded with three realistic business signals so the
competency questions have something to find (see [Week 3](week-3-knowledge-graph.md)).
The OEM ("Meridian Motors"), its dealers, suppliers and customers are fictional.

## Project plan and stakeholders

| Role | Responsibility | R / A / C / I |
|---|---|---|
| Executive sponsor (Warranty) | Sets priorities, attends the Week 6 demo | A |
| Warranty SMEs (2–3) | Workshop, glossary review, CQ validation, UX feedback | C |
| Ontology / knowledge engineer | Glossary, ontology, shapes, competency queries | R |
| Cloud / data engineer | AWS deployment, pipeline, data | R |
| UX lead (part-time) | Explorer workflows and feedback sessions | R |
| Enterprise architecture / security | Architecture review, data classification | C |
| IT owners of source systems | Input on real data structures for the next phase | I |
