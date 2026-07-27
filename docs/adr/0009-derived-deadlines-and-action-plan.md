---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0009: Derived deadlines and deterministic action plans

## Context

Rule evaluation previously accepted a shared mutual-account balance deadline
flag and returned candidate outcomes without a structured execution plan. Filing
and settlement can complete on different dates, and a draft rule can be
applicable while its decision status remains `expert_confirmation_required`.
Decision status alone therefore cannot safely determine whether to recommend an
action.

## Decision

1. `MutualAccountTimeline` is the input contract for dated mutual-account events.
2. A deterministic calculator derives the 30-day entry deadline and independent
   three-calendar-month filing and settlement deadline facts.
3. Derived facts enter the rule engine only through calculation evidence that
   attests the exact case, field, and value.
4. `RuleDecision.matched` records condition applicability separately from status:
   `true` means the rule conditions apply, `false` means a rejecting condition
   failed, and `null` means required facts are uncertain.
5. Only decisions with `matched=true` produce `RecommendedAction` records.
6. Each action preserves its case, rule, authority, timing, deadline, unmet
   requirements, required documents, procedure steps, source IDs, and source
   claim IDs. Rulepacks declare `deadline_key`; runtime code does not infer it
   from a rule ID.
7. `DecisionPacket` schema `1.2` includes immutable actions. The LLM may explain
   these records but may not create, remove, or modify them.

All affected regulatory rules remain `production_ready=false` until role B
reviews the interpretation and source claims.

## Consequences

- Filing and settlement lateness can no longer be conflated.
- Deadline calculations are repeatable and auditable without an LLM.
- Draft status no longer hides whether a rule actually matched.
- The UI or workflow layer can consume an execution plan without parsing prose.
- Adding another dated procedure requires an explicit calculator and rule-to-
  deadline mapping.

## Verification

- Calendar-month and deadline-boundary unit tests.
- Separate filing and settlement completion tests.
- Evidence attestation tests through `FactAssembler`.
- End-to-end case-to-DecisionPacket action tests.
- Full repository checks.
