# BACKLOG

Out-of-scope ideas. Anything not in the scope doc lands here instead of in the build.

## Deferred from v1 by decision

- Additional vector stores (pgvector, Weaviate, Chroma) — see D-001
- Additional LLM providers (Cohere, Mistral, Bedrock, Vertex) — see D-002
- Cloud-specific IaC / deploy overlays (AWS, GCP, Azure) — see D-003

## Raised during build

- **`logging_structured=false` opt-out path** (BaseTemplateEngineer, 2026-09-07). The
  `logging_structured` registry key is default `true` with a note "key exists to allow
  opting out". Phase 1 base implements only the structlog path: the base always depends
  on `structlog` and always configures it. A file-level Jinja conditional around the
  imports made the assembled module fail `ruff` (`F401` unused import) in the
  opt-out branch. Implementing the opt-out cleanly needs either an import-slot loop in
  the base skeleton or a separate `logging_config.py` variant. Low priority: no consumer
  has asked for plain-stdlib logging.
## Resolved (kept for audit)

- **`app` service `depends_on` for datastore overlays** (BaseTemplateEngineer, 2026-09-07).
  No fragment slot existed for an overlay to add `depends_on: { <svc>: { condition:
  service_healthy } }` to the base compose `app` service. RESOLVED by D-027: overlay-contract
  §4.3 now defines a `compose.app-deps.yml.jinja` fragment slot; the base `app` service loops
  `selected_overlays` for its `depends_on`. No registry change. Phase 2 datastore overlays
  implement it.

## Resolved by decision

- **Per-service `copier update` granularity for monorepo**: RESOLVED by D-036 - the orchestrated per-service render gives each `services/<svc>/` its own `.copier-answers.yml`, so `copier update` runs per service natively.

## Raised during Phase 3 (owner)

- **Generated data-access CRUD scaffold** (owner, 2026-09-09). Ship initial
  code for the common data operations in the generated service: create an
  entity, update an entity, find all, find one by id, delete one, and more
  (count, exists, pagination). Provide it for the `db_postgres`, `db_mongodb`,
  and optionally `db_redis` overlays - a small `repository`/`dao` module +
  an example entity + tests, so a generated service is not just a bare client.
  Schedule into Phase 7 (hardening) or a dedicated overlay-enrichment pass.
