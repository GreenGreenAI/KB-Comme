---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0012: Evidence-bound K-SURE case orchestration

## Context

The initial K-SURE rulepack could evaluate generic facts, but it lacked a typed
case input, executable action metadata, and product identity in the final
action contract. A matching rule therefore reached a decision but not a usable
application plan.

## Decision

1. `KsureCaseProfile` is the typed input for company size, common credit
   restrictions, exporter/importer grades, country restriction, payment term,
   financing purpose, and prior bank consultation.
2. Every populated profile field must cite evidence IDs. `FactAssembler` still
   enforces catalog type, required evidence role, case identity, and exact value
   attestation.
3. K-SURE candidate outcomes declare authority, action, timing, and product ID.
4. `RecommendedAction` and `PacketAction` preserve `product_ids`. Product
   identity participates in action deduplication, so applications for different
   products are never accidentally merged.
5. A known missing bank consultation remains a conditional candidate with a
   structured requirement. Missing evidence remains insufficient information,
   and an ineligible grade produces no action for that product.
6. The rulepack remains draft and all matching products require expert review
   until cross-role verification is complete.
7. `DecisionPacket` schema `1.4` adds product IDs to actions.

## Consequences

- A real export case can now reach three K-SURE product decisions and complete
  document/procedure action plans.
- The LLM explains product candidates but does not select products or invent
  eligibility evidence.
- Live company, grade, and country-policy adapters can later populate the same
  facts without changing the rule or packet contracts.

## Verification

- Complete three-product end-to-end case test.
- Conditional consultation requirement test.
- Ineligible-grade exclusion and action suppression test.
- Missing evidence and invalid payment-term input tests.
- Full evidence, packet identity, architecture, and documentation checks.
