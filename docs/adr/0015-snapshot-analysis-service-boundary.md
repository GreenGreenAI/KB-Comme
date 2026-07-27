---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-27
---

# ADR-0015: Snapshot analysis service boundary

## Context

The deterministic pipeline could create a `DecisionPacket`, but callers had to
manually locate a snapshot, apply its dataset parser and freshness policy,
construct a `TradeProgram`, and serialize the packet. A web route that repeats
those steps could bypass storage, integrity, or decimal-precision rules.

## Decision

1. `AnalysisService` is the transport-neutral application boundary for an
   analysis request. HTTP, CLI, or workflow adapters call this service rather
   than the pipeline directly.
2. A request identifies data with `dataset_id` and `snapshot_version`. It never
   supplies a filesystem path. Both values and `program_id` must be safe path
   segments, and the resolved storage root must remain inside the project.
3. The service reads through `DatasetRegistry` and `ParserRegistry`, enforcing
   source identity, content hash, schema, dataset kind, and freshness before it
   creates a `TradeProgram`. `as_of` cannot be later than execution time, and a
   snapshot observed or retrieved after `as_of` cannot enter a historical run.
   These business-date comparisons use `Asia/Seoul`.
4. Request schema 1.0 accepts monetary values only as decimal strings. Unknown
   fields, floats, invalid dates, reserved company facts, and path traversal
   are rejected as `invalid_request`.
5. Operational failures use stable error codes: `unknown_dataset`,
   `snapshot_not_found`, `snapshot_invalid`, `snapshot_stale`,
   `wrong_dataset_kind`, and `invalid_case_input`.
6. `decision_packet_document` serializes `DecisionPacket` without converting
   `Decimal` to binary floating point. Dates and enums use their canonical
   string values; frozen mappings are restored as JSON objects.
7. This service returns deterministic packet data. LLM synthesis and HTTP
   authentication are separate outer boundaries and cannot change the packet.

## Consequences

- Analysis is reproducible from a named, verified snapshot without trusting a
  caller-provided path.
- Transport adapters have one error and serialization contract.
- The current boundary supports base analysis and typed case-analysis inputs.
  A public JSON schema for evidence-bearing case inputs remains future work.
- Network routing, authentication, authorization, and persistence of analysis
  runs are not introduced by this decision.

## Verification

- Request schema, unknown-field, decimal-string, and path traversal tests.
- Missing, stale, corrupted, and wrong-kind snapshot tests.
- Case configuration fail-closed test.
- Repeated packet identity and snapshot lineage test.
- JSON serialization tests for exact decimals, enum values, arrays, and empty
  frozen mappings.
