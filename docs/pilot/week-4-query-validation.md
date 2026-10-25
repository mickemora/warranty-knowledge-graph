# Week 4: Query and validation

**Goal:** prove that the model answers real business questions, with the SMEs.

## The ten competency questions

Each is a standalone SPARQL file in [`queries/competency/`](../../queries/competency/) with a
header (id, title, question, why it matters, parameters). Parameters are `VALUES` clauses with a
default, so every file runs as-is in a Neptune notebook, and the explorer and CLI swap in
validated values.

Results on the synthetic dataset: [`docs/competency-results.md`](../competency-results.md)
(regenerate with `python scripts/kg.py cq report --local`).

| # | What the answer shows on the synthetic data | Relies on |
|---|---|---|
| CQ01 | C-100245: Aster XLE, owner, Prosper Meridian, RO-987654, water pump, Apex Thermal Systems, Engine Cooling / Powertrain | inverse `ownedBy`, derived `affectsSystem` |
| CQ02 | The showcase vehicle's warranty RO and claim, in date order | inverses `hasRepairOrder`, `hasClaim` |
| CQ03 | 61 related water pump claims on Asters, almost all built at San Marcos in late 2021 | causal part, vehicle build data |
| CQ04 | Cost by system and category (Steering, Brakes, HVAC lead on cost) | SKOS taxonomy, `affectsSystem` |
| CQ05 | Supplier exposure; Apex Thermal Systems has 92 claims on 3 parts | inverse `supplies` |
| CQ06 | For S01: the water pump on Aster MY2022 San Marcos dominates (59 claims, ~15 months in service) | |
| CQ07 | Tyler Meridian books 1.62× standard labor; every other dealer is ≤ 1.1× | `standardLaborHours` |
| CQ08 | 14 repeat repairs, nearly all at Tyler Meridian | months in service |
| CQ09 | October 2021 builds: 73% of vehicles have a water pump claim (vs ≤ 17% outside the window) | build month |
| CQ10 | 75 vehicles from the window without a claim yet, with owner and servicing dealer | `FILTER NOT EXISTS`, `ownedBy` |

Run them:

```bash
python scripts/kg.py cq list
python scripts/kg.py cq run cq09                       # against Neptune
python scripts/kg.py cq run cq10 --param buildFrom=2021-10-01 --param buildTo=2021-10-31
python scripts/kg.py cq run cq03 --local               # in-memory graph, no AWS
```

…or open **Competency Questions** in the explorer, where each question has a parameter form, the
results table and the SPARQL.

## Refining the model from feedback

The pipeline makes refinement cheap: edit `ontology/`, `shapes/` or `warranty_kg/mapping.py`,
run `pytest` (it checks the ontology, shapes and every competency answer locally), then
`cdk deploy --all`. The deploy reruns the pipeline because the source hash changed.

## SME validation sign-off

| CQ | Answer correct? | Useful as presented? | Changes requested | SME | Date |
|---|---|---|---|---|---|
| CQ01 | | | | | |
| CQ02 | | | | | |
| CQ03 | | | | | |
| CQ04 | | | | | |
| CQ05 | | | | | |
| CQ06 | | | | | |
| CQ07 | | | | | |
| CQ08 | | | | | |
| CQ09 | | | | | |
| CQ10 | | | | | |
