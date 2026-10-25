# Pilot playbook: six weeks, week by week

The infographic's six-week plan, with what this repository provides for each week's deliverables.
Each week has its own page with the working material: agendas, templates, and the outputs this
repository already produces from the synthetic dataset.

| Week | Theme | Deliverables on the infographic | In this repository |
|---|---|---|---|
| 1 | [Business discovery](week-1-business-discovery.md) | Business problem statement · Initial competency questions (5–10) · Project plan and stakeholders | Problem statement, workshop agenda, the 10 competency questions, success metrics, RACI template |
| 2 | [Ontology modeling](week-2-ontology-modeling.md) | Conceptual model (diagram) · Ontology specification (RDF/OWL/SHACL) · Approved domain glossary | `ontology/warranty.ttl`, `reference/part-taxonomy.ttl`, `shapes/warranty-shapes.ttl`, glossary, model diagram, v1 → v1.1 change log |
| 3 | [Knowledge graph implementation](week-3-knowledge-graph.md) | Knowledge graph in Amazon Neptune · Sample data pipeline/scripts · Data quality validation report | `datagen/`, `warranty_kg/mapping.py`, the Step Functions pipeline, SHACL report in S3 |
| 4 | [Query and validation](week-4-query-validation.md) | 10 validated competency questions and queries · Query results and examples · SME validation sign-off | `queries/competency/*.rq`, [`../competency-results.md`](../competency-results.md), sign-off template |
| 5 | [Business user experience](week-5-user-experience.md) | Relationship explorer UI · Key navigation workflows · Optional NLQ capability · User feedback and refinements | `frontend/`, the explorer API, Bedrock NLQ, feedback log template |
| 6 | [Demonstration and evaluation](week-6-demo-and-evaluation.md) | Executive and business demo · Impact assessment · Lessons learned · Recommended next phase | Demo script, success-criteria scorecard, impact and lessons templates, next-phase options |
