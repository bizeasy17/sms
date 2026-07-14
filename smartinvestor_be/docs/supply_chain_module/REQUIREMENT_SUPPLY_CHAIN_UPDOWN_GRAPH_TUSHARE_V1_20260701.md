# Requirement: Supply Chain Upstream/Downstream Graph via Tushare V1

- Date: 2026-07-01
- Environment: UAT (design only, no implementation in this change)
- Status: Confirmed

## 1. Goal

Build a new module in smartinvestor_be to visualize upstream/downstream supply chain relations for a given company.

V1 must work without announcement NLP. It should rely on low-cost/high-coverage structured interfaces and produce explainable graph outputs with confidence scores.

## 2. Service Ownership (confirmed)

- Module owner: smartinvestor_be
- Data source owner: Tushare Pro APIs
- UI consumer: smartinvestor_fe graph view (future integration)

## 3. Scope

### 3.1 In scope (V1)

- Extract company product tags from:
  - stock_company.business_scope
  - fina_mainbz.bz_item
- Match product tags to concept boards via concept_detail.
- Project tags into chain layers using an internal chain definition dictionary.
- Build graph response:
  - nodes (company, tags, concepts, chain layers)
  - edges (belongs_to, maps_to, upstream_of, downstream_of)
  - confidence and evidence metadata

### 3.2 Out of scope (V1)

- Named counterparty extraction from announcements (supplier/customer names from PDF NLP)
- Contract amount parsing
- Entity resolution from free-text announcements

## 4. Data Source Strategy

### 4.1 V1 primary data sources

1. stock_company (doc_id=112, low-cost)
- fields: business_scope, main_business, introduction, industry
- usage: broad product/operation keyword coverage

2. fina_mainbz (doc_id=81)
- fields: bz_item, bz_sales, bz_profit, bz_cost
- usage: core product labels and business importance weighting

3. concept_detail (doc_id=126)
- usage: concept board membership and market-recognized thematic relation

### 4.2 Optional V1.5/V2 data sources

- sw industry / index_member for finer hierarchy constraints
- top10_holders for capital linkage hints
- fina_indicator for economic consistency checks
- anns_d / stk_notices for named evidence extraction (depends on permission)

Note: In current UAT token, anns_d permission is unavailable. Do not make anns_d a V1 dependency.

## 5. Functional Design

### 5.1 Pipeline

1. Input
- ts_code
- market (default CN)
- optional asof_date

2. Profile collection
- fetch stock_company profile
- fetch fina_mainbz latest valid period rows

3. Tag extraction and normalization
- extract raw tags from business_scope and bz_item
- normalize synonyms and aliases
- classify tags by type:
  - raw_material
  - component
  - product
  - equipment
  - application

4. Scoring
- base score from source quality:
  - fina_mainbz.bz_item > stock_company.business_scope
- importance adjustment using bz_sales/bz_profit/bz_cost when available
- term quality adjustment using dictionary precision

5. Concept mapping
- map tags to concept boards using concept_detail bridge rules
- assign mapping confidence and evidence text

6. Chain layering
- map tags to chain layers using internal CHAIN_DEFINITIONS
- derive upstream/downstream adjacency by layer index order

7. Graph assembly
- nodes:
  - center company node
  - tag nodes
  - concept nodes
  - chain layer nodes
- edges:
  - company_has_tag
  - tag_in_concept
  - tag_in_layer
  - layer_upstream_of / layer_downstream_of

8. Output
- graph payload + evidence + confidence distribution

## 6. Graph Contract (proposed)

### 6.1 Request

- GET /api/supply-chain/graph/
- query params:
  - ts_code (required)
  - max_nodes (optional, default 120)
  - min_confidence (optional, default 0.35)
  - include_concepts (optional, default true)
  - include_layers (optional, default true)

### 6.2 Response

- code: 0|non-zero
- data:
  - center: { ts_code, name }
  - nodes: [
      { id, type, label, score, confidence, meta }
    ]
  - edges: [
      { source, target, relation, confidence, evidence_source, evidence_text }
    ]
  - stats:
    - tag_count
    - concept_count
    - layer_count
    - edge_count
    - confidence_summary
  - trace:
    - source_modes
    - asof
    - warnings

## 7. Confidence Model

Confidence level policy:

- High:
  - tag appears in fina_mainbz and maps to deterministic chain keyword
- Medium:
  - tag appears in business_scope and concept_detail mapping is stable
- Low:
  - only weak lexical match or ambiguous concept projection

Confidence must always include explanation fields.

## 8. Chain Knowledge Base (core asset)

Maintain internal CHAIN_DEFINITIONS as versioned config.

Each chain:
- chain_name
- ordered layers
- layer keywords
- optional aliases
- optional exclusion terms

Example chains to bootstrap:
- lithium battery chain
- semiconductor chain
- liquor chain
- photovoltaic chain

## 9. Delivery Priority

Phase priority by ROI:

1. P0 (immediate)
- fina_mainbz + stock_company tag extraction
- concept_detail mapping
- basic graph output

2. P1
- sw hierarchy constraints
- confidence calibration and dedup improvements

3. P2
- named evidence from announcements (anns_d / stk_notices + NLP)
- capital and financial validation overlays

## 10. Acceptance Criteria

1. Given ts_code, API returns graph payload with nodes/edges/confidence.
2. At least one evidence_source is attached for each edge.
3. V1 works without announcement NLP and without anns_d dependency.
4. Result quality is explainable via trace and evidence fields.
5. Module supports at least top A-share chains through CHAIN_DEFINITIONS.

## 11. Risks and Constraints

1. Concept board mapping can create thematic noise; confidence gating is mandatory.
2. business_scope text can be broad; normalization dictionary quality is critical.
3. fina_mainbz coverage/latency varies by company and period.
4. Without announcement extraction, V1 is relation inference, not legal-proof counterparty relation.

## 12. Validation Plan (when implementation starts)

1. Unit tests:
- tag extraction
- synonym normalization
- layer mapping
- confidence scoring

2. Integration tests:
- API response contract
- representative symbols from multiple chains

3. Manual review set:
- 20 symbols across 4 chains
- compare inferred layers with analyst expectation

## 13. Non-goals Clarification

This module in V1 is for chain-structure inference and visualization, not for auto-trading execution and not for regulatory-grade disclosure proof.
