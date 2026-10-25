# Week 5: Business user experience

**Goal:** a simple interface for exploring warranty relationships.

![Warranty Claim Explorer](../images/explorer-claim.png)

## Relationship explorer

The **Warranty Claim Explorer** (`frontend/`) follows the infographic's mockup: search across claim
numbers, VINs, part numbers, dealers, suppliers and customers; a graph of the selected record and
its connections; a **Related Information** panel; and **View Related Claims**.

| Area | What it does |
|---|---|
| Search bar | Matches any business key or name (`wko:identifier` or `rdfs:label`), ranked exact → prefix → contains. Questions of four or more words also offer "Ask" (natural language). |
| Left navigation | Paged lists of claims, vehicles, parts, dealers, repair orders, suppliers and customers. |
| Graph | The record and its neighbors. For a claim it goes two hops (part → supplier, vehicle → owner), like the mockup. Click any node to re-center on it. Large relationships show the first 12 and a count. |
| Related Information | For a claim: related-claim count, model, model year, part category, system, dealer, supplier, cost, status, owner (built on CQ01 + CQ03). For other records: key attributes and relationship counts. |
| Details | All attributes, plus the record's types with inferred superclasses. |
| Competency Questions | All ten, with parameter forms, results and the SPARQL. |
| Ask a Question | Natural-language search with Amazon Bedrock (optional). |

The page has no third-party scripts: the graph is plain SVG, so it runs under a strict
Content-Security-Policy and needs no CDN.

## Key navigation workflows

1. **Claim investigation.** Search `C-100245` → see vehicle, dealer, part, supplier, owner →
   *View Related Claims* → notice the San Marcos late-2021 build dates → open
   *Competency Questions → CQ09* to confirm the window → *CQ10* for the vehicles still at risk.
2. **Vehicle history.** Search a VIN → graph shows its claims, repair orders, owner, selling dealer
   → click any claim or RO.
3. **Supplier review.** Search `Apex` → supplier → its parts → a part's claims; or CQ05 → CQ06.
4. **Dealer audit.** CQ07 (labor vs standard) → click `D017` → the dealer's claims and repair
   orders → CQ08 for its repeat repairs.

## Natural-language search (optional)

`POST /api/nlq` sends the question to a Lambda function that asks Claude Sonnet 4.5 on Amazon Bedrock to write
one SPARQL query using only the ontology's terms (the prompt includes a schema generated from
`ontology/warranty.ttl` and the ten competency questions as examples). The query is checked
(read-only, no `SERVICE`, row limit, parses), executed by the read-only explorer Lambda inside the
VPC, and summarized in two or three sentences from the returned rows only. The UI always shows the
generated SPARQL, so users and SMEs can see exactly what was asked of the graph.

Try: *"Which dealers submitted the most water pump claims?"*,
*"What is the average claim cost by model?"*,
*"Which suppliers have parts with claims in the first 6 months of service?"*

## Feedback log

| Date | User / role | Workflow | Feedback | Change made |
|---|---|---|---|---|
| | | | | |
