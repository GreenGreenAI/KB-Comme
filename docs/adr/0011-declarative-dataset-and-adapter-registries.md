---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0011: Declarative dataset and adapter registries

## Context

ECOS and enterprise trade feeds had validated adapters, snapshot readers, and
domain objects, but orchestration still selected each reader and freshness
policy directly in code. Adding K-SURE, Bizinfo, another ERP, or a bank quote
feed that way would scatter source IDs, parser choices, storage rules, and SLAs.

## Decision

1. `data/dataset_registry.json` is the versioned operational dataset catalog.
2. Each `DatasetDefinition` declares dataset/source IDs, data kind, adapter and
   parser keys, payload contract version, collection interval, freshness
   policy, storage scope, and project-relative storage root.
3. `DatasetRegistry` is network-free and lives in `domain`. It validates the
   catalog, selects definitions, verifies snapshot identity and freshness, and
   delegates payload interpretation to `ParserRegistry`.
4. Parsers are objects with an explicit data kind and schema version. A parser
   that is missing or incompatible with a definition is rejected before data
   reaches a domain calculation.
5. `AdapterRegistry` lives in the `integration` leaf. It binds an adapter object
   to a dataset only when `source_id` and `adapter_key` match the definition.
6. Public reproducible data uses `data/snapshots`; tenant data uses the
   Git-ignored `data/runtime` root. Absolute and parent-traversing storage paths
   are invalid.
7. Credentials and tenant endpoints are never registry data. They remain
   runtime adapter configuration.

## Consequences

- Adding a provider starts with one dataset declaration and compatible parser
  and adapter registrations.
- Collection remains isolated in `integration`; calculation code reads only
  verified snapshot files through `domain`.
- The same source, schema, SLA, and storage policy is used consistently across
  collection tests and runtime consumption.
- Registry schema migration and a persistent administrative UI remain future
  work.

## Verification

- Committed registry loading and immutability tests.
- Parser key, kind, and schema compatibility tests.
- Adapter source/key and duplicate-binding tests.
- ECOS and ERP registry-based end-to-end snapshot tests.
- Freshness, private/public storage, path safety, and module-boundary tests.
