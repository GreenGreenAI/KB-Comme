---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0010: Decision categories and action deduplication

## Context

Decision status answers why a rule result is not final, while condition
applicability answers whether the rule relates to the case. A draft rule can be
both an applicable candidate and require expert review. A single status label
cannot express both facts. Multiple applicable rules can also produce the same
operational action, which would create duplicate tasks for a user.

## Decision

1. Every `RuleDecision` carries deterministic category tags:
   `candidate`, `excluded`, `missing_information`, `expert_review`,
   `source_unusable`, and `urgent_action`.
2. Categories are multi-valued. They are derived only from `matched`,
   `DecisionStatus`, and the rulepack's structured timing.
3. `urgent_action` requires `matched=true` and `timing=immediate`.
4. Actions are deduplicated by case, authority, action name, timing, and
   deadline.
5. A merged action preserves all rule IDs, requirements, documents, procedure
   steps, source IDs, and source claim IDs in stable first-seen order.
6. Different cases or different deadlines never merge.
7. `DecisionPacket` schema `1.3` replaces action `rule_id` with `rule_ids` and
   includes decision categories.

The LLM receives these classifications and merged actions as immutable packet
content. It does not classify decisions or merge tasks.

## Consequences

- A candidate under expert review remains visible as both.
- Missing information is not confused with an explicit exclusion.
- Consumers can render category sections without interpreting reason prose.
- Users receive one operational task while retaining complete regulatory
  lineage.

## Verification

- Category composition tests for candidate, excluded, missing information,
  expert review, unusable source, and urgent action.
- Action merge tests covering rule, document, procedure, and claim lineage.
- End-to-end DecisionPacket tests and full repository checks.
