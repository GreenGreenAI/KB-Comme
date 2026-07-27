---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-27
---

# ADR-0014: Deterministic collection orchestration

## Context

Registered adapters could write validated snapshots, but every caller still
had to decide independently when to collect, whether to retry, and whether an
older snapshot was safe after a provider outage. Those decisions affect the
evidence used by calculations and therefore must not be delegated to a job
scheduler, UI, or LLM.

## Decision

1. Dataset registry schema 1.1 requires every definition to declare a positive
   `collection_interval_seconds` in addition to its observation and retrieval
   freshness limits.
2. `CollectionOrchestrator` decides that a dataset is due when no snapshot
   exists, its latest verified snapshot is stale, or its collection interval
   has elapsed since `retrieved_at`.
3. A caller supplies a `CollectionRequest` with immutable provider parameters,
   at most five attempts, and an optional force flag. The orchestrator owns
   `retrieved_at`; callers cannot inject it.
4. Each successful adapter result is read back through `DatasetRegistry` and
   `ParserRegistry`. A written file is not considered usable until its
   identity, content hash, schema, source, and freshness pass validation.
5. After all attempts fail, only the latest intact and fresh snapshot may be
   returned as `fallback`. Missing, stale, malformed, or corrupted snapshots
   produce a structured `failed` result.
6. A batch returns one result per dataset and continues after an individual
   operational failure. Duplicate dataset IDs are rejected as a caller error.
7. A platform scheduler determines when the process runs; it does not decide
   data freshness or fallback safety. No LLM participates in this path.

## Consequences

- ECOS, ERP, Bizinfo, and later provider adapters share one collection policy
  boundary without sharing provider-specific request parameters.
- Provider outages are explicit and auditable as `collected`, `skipped`,
  `fallback`, or `failed` results.
- Retries are bounded and immediate. Delayed retry queues and persistent run
  history remain operations-layer work.
- A stale snapshot is never silently promoted because it is the only available
  file.

## Verification

- Due, skipped, and forced collection tests.
- Bounded retry and immutable request tests.
- Fresh fallback, stale fallback, and missing adapter tests.
- Multi-dataset failure isolation and duplicate request tests.
- Full snapshot-registry parsing and freshness checks on returned datasets.
