---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-27
---

# ADR-0013: Bizinfo support-program snapshots

## Context

The source registry already identifies the official Bizinfo API, but the
runtime could not collect or consume its support-program results. Support
programs change more frequently than reviewed regulatory rules, so discovery
needs a repeatable API snapshot without turning an API record into an approved
eligibility decision.

ADR-0003 deferred automated Bizinfo collection for the initial foundation.
That deferral is now replaced by this decision; the snapshot and integration
boundaries from ADR-0003 remain unchanged.

## Decision

1. `BIZINFO_SUPPORT_PROGRAMS_DAILY` is a public, versioned dataset backed by
   the official Bizinfo support-program API.
2. `BizinfoSupportAdapter` obtains its credential only from constructor
   configuration or `BIZINFO_API_KEY`. The credential is not persisted in the
   registry, snapshot, exception, or adapter representation.
3. The adapter accepts HTTPS only, limits response size, converts transport
   errors into credential-safe errors, validates JSON, and writes the original
   payload in the common snapshot envelope.
4. `BizinfoSupportV1Parser` converts documented API fields into immutable
   `SupportProgram` values. Missing required fields, duplicate program IDs,
   invalid publication dates, and inconsistent totals are rejected.
5. Collection time is used as both `observed_at` and `retrieved_at`, because
   the catalog response does not provide one authoritative timestamp for the
   complete result set.
6. A program record is only a discovery candidate. Eligibility, priority, and
   recommendation require separate reviewed rules and evidence. An LLM may
   summarize a selected record but may not infer those decisions.

## Consequences

- Support-program discovery can be refreshed and replayed without network
  access during analysis or tests.
- Raw API payloads remain traceable while domain code receives a stable typed
  contract.
- Daily collection still needs common scheduling, retry, and status
  orchestration.
- Program-detail documents and their eligibility conditions remain a separate
  knowledge-ingestion and role-B review task.

## Verification

- Official field and alias normalization tests.
- Duplicate, invalid total, invalid JSON, response-size, HTTPS, and source-path
  safety tests.
- Query construction and credential-redaction tests.
- Adapter-to-snapshot-to-dataset-registry round-trip test.
