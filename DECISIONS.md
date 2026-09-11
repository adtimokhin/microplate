# DECISIONS

Every decision that resolves ambiguity. Format: decision, date, rationale, status.

Status values: `provisional` (Lead decision, open to override), `confirmed` (agreed with project owner), `superseded`.

---

## D-001: Vector store for v1 is Qdrant, sole option

- Date: 2026-09-07
- Status: confirmed
- Decision: Qdrant is the only vector store overlay in v1. No pgvector, no Weaviate, no Chroma.
- Rationale: Scope §4.2 and §9 already name Qdrant as the presumed choice. One vector store keeps the embedding pipeline overlay and LangChain retrieval chain single-target, which reduces combinatorial surface. Additional stores go to BACKLOG.md.

## D-002: LLM providers for v1 are OpenAI and Anthropic

- Date: 2026-09-07
- Status: provisional
- Decision: The LLM provider client overlay ships OpenAI and Anthropic clients, each independently selectable. No Cohere, Mistral, Bedrock, Vertex in v1.
- Rationale: Scope §9 names these two as the minimum. Both selectable and independently toggleable so a service can carry one or both. Others go to BACKLOG.md.

## D-003: Cloud bias for v1 is none (cloud-agnostic)

- Date: 2026-09-07
- Status: confirmed
- Decision: No cloud-specific IaC or deploy overlay in v1. CI template and Dockerfile stay portable. IaC output, if any, stays cloud-agnostic.
- Rationale: Scope §3 non-goal already rules out auto-deployment and limits IaC to output only. Picking a cloud now adds overlay surface with no v1 payoff. Cloud-specific overlays go to BACKLOG.md.

## D-004: Python baseline is 3.12, async stack on uvicorn

- Date: 2026-09-07
- Status: confirmed
- Decision: Python 3.12 is the minimum supported version for the generator and every generated service. FastAPI on uvicorn, fully async: async SQLAlchemy 2.x, PyMongo async API (see D-008), redis-py asyncio, aio-pika. Base images and CI matrix target 3.12.
- Rationale: Owner selected. Modern typing, broad and stable wheel support, no known C-extension lag for the chosen stack. Overlays may assume 3.12 syntax and stdlib.

## D-005: Multi-service topology output is registry-selectable (monorepo or multi-repo)

- Date: 2026-09-07
- Status: confirmed
- Decision: A registry key selects the topology output layout. `monorepo` produces one repo with `services/<name>/` folders, one shared docker-compose, one `.copier-answers.yml`, and a shared contract/proto dir. `multi_repo` produces one service tree per invocation, each an independent repo, with shared contracts distributed as a generated package or copied dir.
- Rationale: Owner selected "both". Messaging & Topology Engineer owns the added test-matrix and hook complexity this implies and must keep the two layouts behind a single clean registry key with shared overlay logic where possible. This is the topology decision the Messaging Engineer was told to drive early; it is now settled.

## D-006: LangGraph overlay is minimal in v1

- Date: 2026-09-07
- Status: confirmed
- Decision: v1 LangGraph overlay is a single stateful graph scaffold behind one API route, with checkpointing wired to Postgres or Redis (whichever the answers file selects), one example node, and deterministic offline tests using stubbed LLM responses. Off by default. Multi-node agent loops, tool-calling nodes, human-in-the-loop interrupts, and intermediate-step streaming are BACKLOG.
- Rationale: Owner selected. Keeps §8 milestone 7 in v1 while containing non-determinism risk. It stays the only place agent-style control flow appears in a generated service (scope §4.4).

## D-007: Tool/function-call scaffold ships as OpenAPI-shaped routes plus a separate MCP overlay

- Date: 2026-09-07
- Status: confirmed
- Decision: When the tool/function-call endpoint scaffold is selected, the service gets function-call-shaped FastAPI routes whose OpenAPI schemas are tuned for function-calling consumption. A separate MCP server overlay (its own registry key) exposes those same endpoints as MCP tools. Selecting MCP requires the tool scaffold (or gRPC) per §5 validation.
- Rationale: Owner selected "both". Covers scope §4.1 (tool-shaped endpoint) and §4.4 (MCP server scaffold) as independent, composable overlays.

## D-008: MongoDB overlay uses the PyMongo async API, not Motor

- Date: 2026-09-07
- Status: confirmed
- Decision: The MongoDB overlay uses `pymongo` with its async API (`AsyncMongoClient`). Motor is not used.
- Rationale: ResearchData found Motor is deprecated and reached end of life on 2026-05-14. Scope §4.2 already allows "Motor/PyMongo client", so this is within scope. Pinned version: pymongo 4.18.0 (revisit at build time). Client lifecycle bound to the FastAPI lifespan; health check is a `ping` command.

## D-009: gRPC stubs are committed, not generated at build time

- Date: 2026-09-07
- Status: confirmed
- Decision: The gRPC overlay commits generated `_pb2.py`, `_pb2.pyi`, and `_pb2_grpc.py` into the generated project. It also ships a regeneration script with pinned `grpcio-tools` and `protobuf` versions plus a CI check that regenerates and runs `git diff --exit-code`. The generator invokes protoc with pinned tool versions, repo-relative paths, and fixed input-file ordering so its own output is byte-stable.
- Rationale: ResearchMessaging. Build-time generation makes every downstream build depend on the exact local protoc/protobuf version, so a patch bump silently changes output bytes and breaks reproducibility for users who never touched their `.proto`. Committed stubs also make a generated repo clone-and-run with no protoc toolchain. Pinned: grpcio / grpcio-tools / grpcio-health-checking / grpcio-reflection / grpcio-status 1.83.1, protobuf 7.36.1 (revisit at build time). Pin the whole grpc* family to one identical version.

## D-010: Generated-project packaging is pyproject + hatchling + uv with a committed lockfile

- Date: 2026-09-07
- Status: confirmed
- Decision: Every generated service uses `pyproject.toml` with the hatchling build backend and `uv` for dependency management, with `uv.lock` committed and CI running `uv sync --locked`. `pip` stays a documented fallback. Docker base image is `python:3.12-slim-bookworm` (not Alpine: musl breaks pydantic-core, uvloop, and grpcio wheels), multi-stage uv build, non-root user, exec-form CMD for SIGTERM handling. docker-compose files do not emit the obsolete top-level `version:` key. One server process per container; scale by replicas.
- Rationale: ResearchBaseStack. Committed lockfile is required for the determinism agreement: same inputs, same resolved dependency tree. Alpine exclusion avoids source builds on user machines. These choices bind every overlay's dependency contribution, so they are fixed now.
- Detail: `requires-python = ">=3.12"` in every generated `pyproject.toml` (confirmed, follows D-004). Dev dependencies go in PEP 735 `[dependency-groups]` so they never leak into `pip install`. Poetry and pip-tools rejected (Poetry-specific resolver; pip-tools has no cross-platform resolve).

## D-012: Copier usage constraints for deterministic generation

- Date: 2026-09-07
- Status: confirmed
- Decision: Every agent that touches the template or the generator CLI follows these Copier rules, from `research/copier.md`:
  1. `_tasks` and any hooks are list-form only (argv, bypasses the system shell). No string-form tasks. No time or random Jinja extensions anywhere.
  2. The generator CLI always passes an explicit `vcs_ref` (a tag or commit) on both copy and update. It never relies on Copier's "highest PEP 440 tag" default, which changes over time.
  3. The `.copier-answers.yml` template is `{{ _copier_conf.answers_file }}.jinja` containing `{{ _copier_answers|to_nice_yaml -}}`. It is never hand-edited (breaks the update diff). Secrets are excluded from it.
  4. Conditional overlay directories use a Jinja condition in the directory name (`{% if key == 'x' %}dirname{% endif %}`), single quotes inside, no `.jinja` suffix on directories. Templated `_exclude` gated on `_copier_operation` handles copy-once-vs-never-touch-on-update files. `_skip_if_exists` for generate-once files like local secrets.
  5. `_min_copier_version` is set so an old Copier fails loudly rather than misbehaving.
  6. Non-interactive generation uses `copier copy -f -d 'k=v' ...` or `--data-file`; `--defaults` still errors on any question lacking a default, so the answers file must be complete (matches scope §6).
- Rationale: These are the specific Copier behaviours that would otherwise make output non-reproducible or break `copier update`. Owned jointly by RegistryArchitect (template structure), Base Template Engineer (CLI entrypoint), and DevOps & Distribution Engineer (update path, tagging).

## D-013: AI overlays are stubbed via base-URL redirect and httpx2 MockTransport, not respx/vcrpy

- Date: 2026-09-07
- Status: confirmed
- Decision: Every LLM and tracing overlay makes its client's base URL configurable by env var (`OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, LangSmith endpoint, etc). Deterministic offline tests either point that env var at a local fake server fixture or inject an `httpx2.MockTransport` through the SDK's own async httpx client. The generator does not emit `respx`, `pytest-httpx`, or `vcrpy` based tests.
- Rationale: ResearchAI. openai 3.x, anthropic 1.x, and langsmith 0.12.x are built on `httpx2`, not `httpx`. respx / pytest-httpx / vcrpy patch `httpx` and silently fail to intercept unless `httpx2.alias_httpx()` runs before any import. Base-URL redirect and `MockTransport` are the reliable, SDK-supported paths and keep every AI overlay test offline and deterministic (scope §4.5).

## D-014: Embedding overlay ships an OpenAI client and an offline fastembed default

- Date: 2026-09-07
- Status: confirmed
- Decision: The embedding pipeline overlay ships two embedding backends behind one config key: an OpenAI embeddings client (`text-embedding-3-small`, 1536 dims default) and an offline `fastembed` client via `qdrant-client[fastembed]` (`bge-small-en-v1.5`, 384 dims, no API key). The offline backend is the default so the generated service and the generator's own tests run with zero external API calls. Vector size is a registry key so the Qdrant collection bootstrap matches the chosen backend.
- Rationale: ResearchAI. Satisfies scope §4.4 embedding pipeline while keeping the determinism and offline-test agreements. Requires Qdrant per §5 validation (already encoded).

## D-015: LangGraph Redis-checkpoint path uses a redis-stack image, separate from the plain Redis cache overlay

- Date: 2026-09-07
- Status: confirmed
- Decision: When the LangGraph overlay selects Redis as its checkpoint store, the generated docker-compose uses a `redis/redis-stack` (or Redis 8.0+) image for that service, because `langgraph-checkpoint-redis` needs the RedisJSON and RediSearch modules. The plain Redis overlay (cache / pub-sub) keeps the lighter `redis` image. If both are selected, the compose Redis service is upgraded to redis-stack. `AsyncRedisSaver.asetup()` (note the `a` prefix, unlike Postgres `setup()`).
- Rationale: ResearchAI. The two Redis uses have different server requirements; the registry must resolve the image choice deterministically when both overlays are present. Owned by AI Components Engineer with Data Layer Engineer for the compose merge.

## D-011: Observability defaults - OTLP HTTP exporter, vendored correlation-ID middleware

- Date: 2026-09-07
- Status: confirmed
- Decision: The base template uses the OTLP HTTP/protobuf exporter (not the gRPC exporter) so the base image does not pull grpcio. Correlation-ID / request-ID middleware is vendored into the base template as a small module, not taken as a dependency on `asgi-correlation-id`.
- Rationale: ResearchBaseStack raised both as open follow-ups and recommended these options. HTTP exporter keeps the zero-overlay image slim; a service that also selects the gRPC overlay can switch its exporter if it wants. Vendoring a ~30-line middleware avoids a dependency and keeps the correlation-ID behaviour under our control and stable across `copier update`.

---

# Resolutions of RegistryArchitect's Phase 0 open questions

## D-016: Base source root is flat `{{ python_package }}/`, not `src/` layout

- Date: 2026-09-07
- Status: confirmed
- Decision: The generated service's import package renders at the project root: `{{ python_package }}/...`. No `src/` directory. This freezes every overlay's `template_paths` and every rendered path for `copier update`.
- Rationale: RegistryArchitect open question 1. The determinism and update story is identical either way. Flat keeps the overlay gate mechanism simplest: the gated path segment renders straight to the package directory with no shared literal ancestor (`src/`) that the base and every overlay would also have to carry. The src-layout benefit (test against the installed artifact) is marginal for a containerised service; pytest runs against the package via `pythonpath`/editable install. Frozen now; changing it later requires a `_migrations` `git mv`.

## D-017: monorepo topology keeps one root `.copier-answers.yml` carrying the full `services_config`

- Date: 2026-09-07
- Status: confirmed
- Decision: For `topology == monorepo`, generation is one Copier run with a `{% yield %}` loop over `service_names`, and there is one root `.copier-answers.yml` whose `services_config` map holds every per-service overlay selection. No per-service `.copier-answers.<svc>.yml`. `copier update` re-renders the whole monorepo. `multi_repo` keeps one `.copier-answers.yml` per generated repo (one Copier run each). The `overlay-contract.md` §8.1 text is corrected to match.
- Rationale: RegistryArchitect open question 2a. Copier maintains one answers file per run; the contract's own `{% yield %}` monorepo mechanism is a single run. A single root answers file is the native, deterministic choice and matches scope §7 ("`.copier-answers.yml` retained", singular). Per-service `copier update` granularity is deferred to BACKLOG.
- `services_config` submap schema (open question 2b): specified in `docs/registry-schema.md`, content drafted by the Messaging & Topology Engineer during Phase 3 and integrated into the schema doc and `validate_registry.py` by the Registry Architect. Each submap validates against the same registry options.

## D-018: `api_rest` is always on in v1

- Date: 2026-09-07
- Status: confirmed
- Decision: `api_rest` is a computed `true`, not user-togglable in v1. Every generated service has the FastAPI app, because health and readiness endpoints (scope §4.6) are HTTP and always present. A gRPC-only deployment simply does not expose the HTTP port beyond health. A service with no HTTP server at all is BACKLOG.
- Rationale: RegistryArchitect open question 3. Making REST always-on removes a large branching surface from the base and every overlay for no v1 use case. Validation rules V-2 and V-14 stay encoded so they hold if REST ever becomes optional.

## D-019: v0 dependency pins are frozen; bumps are an explicit task

- Date: 2026-09-07
- Status: confirmed
- Decision: The version pins in `registry.yaml` as of 2026-09-07 are frozen. Overlay engineers use the registry pin as-is; they do not re-pin to latest at build time. Bumps happen only through an explicit "refresh pins" task owned by the DevOps & Distribution Engineer: one PR, every changed pin re-verified against upstream with a new `as_of` date, recorded in STATUS.md. If an engineer finds a pin is yanked or broken, they raise it to the Lead rather than bumping silently.
- Rationale: RegistryArchitect open question 4. Determinism across the build window: two overlays built weeks apart must not pin different patch versions of the same library by accident. The generated service's byte-reproducibility is the product.

## D-020: independent overlay toggles are booleans, not multiselect; `streaming` splits into `streaming_sse` and `streaming_grpc`

- Date: 2026-09-07
- Status: confirmed
- Decision: The `streaming` multiselect key is replaced by two boolean keys `streaming_sse` and `streaming_grpc`, matching the ids already in `overlay_order` and the pattern used by `db_*` and `llm_*`. Rule: an overlay gated by an independent on/off choice uses a boolean key; multiselect is reserved for a free list (`service_names`). The Registry Architect should apply the same split to `transport` (`transport_grpc`, `transport_rabbitmq`, both already in `overlay_order`) unless there is a concrete reason to keep it a multiselect; V-1 then becomes "at least one of `transport_grpc`/`transport_rabbitmq` when `topology != single`".
- Rationale: RegistryArchitect open question 5. Cleaner CLI flag surface (`--streaming-sse`), a strict one-key-one-overlay invariant, and consistency with the rest of the registry.

## D-021: the settings loader is base-owned; `prompt_management` adds only the prompt-file layer

- Date: 2026-09-07
- Status: confirmed
- Decision: The pydantic-settings loader is part of the base template (already implied by D-010). The `prompt_management` overlay adds only versioned prompt files plus a prompt registry/loader scoped to prompts. Scope §4.4 bundles the two in prose, but the base needs a settings loader regardless of any AI overlay.
- Rationale: RegistryArchitect open question 6.

## D-022: keep the reserved `iac` key

- Date: 2026-09-07
- Status: confirmed
- Decision: Keep `iac` in the registry with `choices: [none, compose_only]`, default `none`, `build_status: planned`, no assigned milestone. It reserves the namespace so a future cloud-agnostic IaC overlay is an append, not a new key, and it lets `compose_only` be expressed explicitly.
- Rationale: RegistryArchitect open question 7. Near-zero cost; consistent with D-003 (cloud-agnostic, no cloud IaC in v1).

## D-023: the `redis/redis-stack` image pin is owned by the Data Layer Engineer

- Date: 2026-09-07
- Status: confirmed
- Decision: The Data Layer Engineer owns all datastore compose image pins, including the `redis/redis-stack` tag used for the LangGraph Redis-checkpoint path (D-015). They pin an exact tag with an `as_of` date when they build the Redis overlay in Phase 2, verified against upstream. The AI Components Engineer consumes that pin in Phase 4. The derivation script's image-resolution rule (plain `redis` vs `redis-stack`) is the Registry Architect's.
- Rationale: RegistryArchitect open question 8. Keeps every compose image pin with one owner.

## D-024: the `otel_tracing` overlay is built in Phase 1 (milestone 2), not Phase 3

- Date: 2026-09-07
- Status: confirmed
- Decision: `registry.yaml` moves `otel_tracing` to `milestone: 2`. It stays an opt-in overlay (default `false`) but is built by the Base Template Engineer alongside structured logging and health endpoints, since the team roster assigns OpenTelemetry to that engineer and scope §4.6 lists it as cross-cutting.
- Rationale: Lead review of registry v0 found `otel_tracing` at milestone 5, which conflicts with the team roster and the cross-cutting classification. Correcting now so Phase 1 scope is right.

## D-025: private-template access for CI runners is a GitHub App token, SSH deploy key as interim

- Date: 2026-09-07 (approved by owner 2026-09-08)
- Status: confirmed
- Decision: Downstream project CI that runs `copier update` against the private template repo authenticates with a short-lived GitHub App installation token, minted per run from an org-owned GitHub App (`microservice-template-reader`, Contents: read-only, installed on the template repo and each consumer repo). A read-only SSH deploy key on the template repo is sanctioned as an interim for a small number of consumer repos; migrate to the App before the consumer count passes roughly five or before the first repo owned by another team. Fine-grained PAT on a machine user is rejected. Full rationale, comparison table, and setup steps in `docs/private-template-access.md`.
- Rationale: Resolves scope §7 open item "Decide access model (SSH key vs token) for private repo pulls from CI runners". The App wins on central rotation (rotate one private key, no fan-out to N consumer repos) and blast radius (installation tokens expire in 1 hour). A PAT ties automation to a human account and expires within a year; a deploy key means copying a permanent private key into every consumer repo.

## D-026: structured logging is always on in v1; `logging_structured` becomes a computed key

- Date: 2026-09-07
- Status: confirmed
- Decision: The base template always uses structlog and always configures it. `registry.yaml` changes `logging_structured` from a visible prompt to a computed `when: false` key (like `api_rest` and `healthchecks`), default `true`. The plain-stdlib-logging opt-out path is BACKLOG.
- Rationale: BaseTemplateEngineer found a file-level Jinja conditional around the logging imports fails `ruff` F401 in the opt-out branch, so a clean opt-out needs an import-slot loop or a separate module variant. Structured logging + correlation IDs is scope §4.6 cross-cutting, not a real toggle, and no consumer wants plain logging. Leaving the key as a visible prompt that changes nothing would violate scope §5 (no prompt without a deterministic file/dependency delta), so it is demoted to computed.

## D-027: overlays contribute `app` service `depends_on` through a dedicated compose fragment slot

- Date: 2026-09-07
- Status: confirmed
- Decision: The base `docker-compose.yml` skeleton gains a dedicated fragment slot for the `app` service's `depends_on` map. An overlay that adds a datastore or broker service also contributes, through this slot, a `depends_on: { <service>: { condition: service_healthy } }` entry for the `app` service, assembled in `overlay_order` sequence like every other fragment. `overlay-contract.md` §4.3 is amended to document the slot (it currently only lets an overlay add sibling services). The Registry Architect owns the contract amendment and the base skeleton change.
- Rationale: BaseTemplateEngineer flagged that Phase 2 datastore overlays (postgres, redis, mongodb, qdrant, rabbitmq) need the app container to wait on their containers, and the contract has no mechanism for an overlay to touch the base `app` service. This is a Phase 2 prerequisite: it must land before Data Layer or Messaging overlay work starts. Deterministic because the slot iterates the frozen `overlay_order`.
- Update 2026-09-08: the contract-text amendment (overlay-contract §4.3) is RegistryArchitect's and is done. The base skeleton edits themselves (`docker-compose.yml.jinja` gains `app.depends_on` via `include_slot('compose.app-deps.yml')`; `pyproject.toml.jinja` `[dependency-groups]` gains `include_slot('dev-deps.toml')` so overlays can contribute `testcontainers` and other dev-only deps) are BaseTemplateEngineer's, since it owns `template/` base files and built the `include_slot` mechanism. Both slots must render to nothing for the zero-overlay config.

## D-028: team structure for Phase 2 onward

- Date: 2026-09-08
- Status: confirmed
- Decision: Three changes to the roster, Lead's call per the owner:
  1. **Standing Research agents retired.** Phase 0's five research docs (`research/*.md`) stand as the reference. Build agents do their own targeted doc lookups and escalate any version/pin question to the Lead. No dedicated research seat.
  2. **Derivation script pulled forward from Phase 5 to Phase 2.** `scripts/gen_copier_yml.py` (full) and the full rule set of `scripts/validate_registry.py` are now Phase 2 work, owned by the Registry Architect, running in parallel with the overlay builds. Reason: the temporary hand-written `copier.yml` only carries base + `otel_tracing` keys, so the combinatorial harness cannot exercise real overlay selection until the generated `copier.yml` exists. It is now a Phase 2 verification enabler, not a Phase 5 nicety.
  3. **"Messaging & Topology Engineer" split.** Phase 2 seat is **MessagingEngineer**: `messaging_rabbitmq`, `api_grpc` (committed stubs per D-009), `streaming_sse` + `streaming_grpc`, `tool_scaffold`. A separate **TopologyEngineer** seat is created at Phase 3 for the multi-service topology overlay (`monorepo` / `multi_repo`, inter-service wiring, `tests_contract`).
- Data Layer Engineer owns all four datastores (`db_postgres`, `db_mongodb`, `db_redis` + `redis_pubsub`, `db_qdrant`) across milestones 3 and 4, including the `redis/redis-stack` image pin (D-023) and the `compose.app-deps.yml.jinja` fragments (D-027).
- Testing Engineer (same agent, resumed) extends fixtures and boots tests per overlay, flips `build_status` as overlays land, and runs the combinatorial harness as the Phase 2 gate.
- Shared working tree retained (not per-agent worktrees): the overlay contract already isolates each overlay to its own gated subtree and `_fragments/<id>/` directory, and overlays never write shared base files. Integrator rule stays: only the Lead commits `STATUS.md` / `DECISIONS.md` / `BACKLOG.md`; each agent stages only its own new files.

## D-029: Phase 1 working tree is left uncommitted; `ORG` template slug unresolved

- Date: 2026-09-08
- Status: confirmed
- Decision: Per the owner ("the other things are as is"), no Phase 1 snapshot commit is made; all non-DevOps deliverables stay uncommitted on disk through Phase 2. The `DEFAULT_TEMPLATE_SRC` `ORG` placeholder in `msvc_gen/cli.py` and `docs/private-template-access.md` stays until the owner supplies the private repo path. Nothing is pushed to any remote.
- Rationale: Owner instruction. Revisit both at the next checkpoint.

## D-030: primary datastore connection env vars default to a working localhost value, not required-with-no-default

- Date: 2026-09-08
- Status: confirmed
- Decision: For each datastore/broker overlay, the primary connection env var (`APP_DB_POSTGRES_DSN`, `APP_DB_MONGODB_URI`, `APP_REDIS_URL`, `APP_QDRANT_URL`, `APP_RABBITMQ_URL`) is `required: false` with a recorded default that points at the compose service name (e.g. `postgresql+asyncpg://app:app@postgres:5432/app`). `secret: true` stays for the credential-bearing URLs (controls log/echo handling, not whether a default exists). `.env.example` documents the dev default; real deployments override via real env.
- Rationale: DataLayerEngineer. The per-overlay definition of done requires the generated service to boot under `docker compose up` with no manual step. `required: true, default: null` forces the user to hand-fill a value before the service starts, which breaks "generate then run". A localhost/compose-hostname default with a dev password (also visible in the compose file) is not a meaningful secret; production overrides it. RegistryArchitect updates the `env_vars` blocks.
- Refinement 2026-09-08 (RegistryArchitect framing, Lead ruling "Option A"): `overlay-contract.md` §5.4 is amended to distinguish three cases. (a) Credential-bearing connection strings for a bundled compose service (`APP_DB_POSTGRES_DSN`, `APP_DB_MONGODB_URI`, `APP_DB_MONGODB_DATABASE`, `APP_REDIS_URL`, `APP_QDRANT_URL`, `APP_RABBITMQ_URL`): localhost/compose-hostname default, `required: false`, `secret: true`. (b) True external-credential secrets with no meaningful local default (`APP_LLM_OPENAI_API_KEY`, `APP_LLM_ANTHROPIC_API_KEY`, `APP_LANGSMITH_API_KEY`): no default, `secret: true`, `required: true` when the overlay cannot work without them. (c) Optional-auth keys (`APP_QDRANT_API_KEY`): no default, `secret: true`, `required: false`. The name/field/`.env.example` match rule stays; `.env.example` shows the localhost default for case (a).

## D-031: duplicate `testcontainers` dev-dep line across multiple datastore overlays is deferred to milestone 8

- Date: 2026-09-08
- Status: confirmed
- Decision: When two or more datastore overlays are selected with `tests_integration`, each contributes an identical `testcontainers==4.15.0` line to `[dependency-groups].dev`. `uv` de-duplicates on resolve, so this is cosmetically noisy but harmless. The milestone-8 `tests_integration` implementer collapses it to one injection point.
- Rationale: DataLayerEngineer. Not worth a special-case in Phase 2; `tests_integration` scaffolding is milestone 8 and owns the fix.

## D-032: overlays contribute routers through an `api_router` fragment slot, not runtime lifespan mounting

- Date: 2026-09-08
- Status: confirmed
- Decision: The base `api/router.py` gains an `api_router` fragment slot. An overlay that adds HTTP routes ships `_fragments/<id>/api_router.py.jinja` contributing an import + an `include_router(...)` line, assembled at app construction in `overlay_order` (like every other shared-file slot). Overlays MUST NOT mount routers from a lifespan startup hook or mutate `app.openapi_schema` at runtime.
- Rationale: MessagingEngineer-2's `streaming_sse` and `tool_scaffold` initially mounted their routers from the lifespan hook and reset `app.openapi_schema`, because no router slot existed. That works but violates overlay-contract §4 in spirit (overlays touch shared files only through render-time fragments, never runtime app mutation) and makes the OpenAPI schema depend on startup ordering. BaseTemplateEngineer adds the slot; `streaming_sse` and `tool_scaffold` migrate to it and are held from `build_status: implemented` until they do. `api_grpc` / `streaming_grpc` are unaffected (gRPC server, not FastAPI routes). This is the same class of gap as D-027 (compose `app.depends_on`) and D-021-adjacent slots.

## D-033: `messaging_rabbitmq` integration dev-dep follows the per-overlay `dev-deps.toml.jinja` pattern

- Date: 2026-09-08
- Status: confirmed
- Decision: `messaging_rabbitmq` ships `_fragments/messaging_rabbitmq/dev-deps.toml.jinja` emitting `testcontainers==4.15.0` gated on `tests_integration`, matching the four datastore overlays. The duplication when several such overlays are selected is deferred to the milestone-8 `tests_integration` implementer per D-031.
- Rationale: MessagingEngineer-2 flagged the inconsistency. Keeping one pattern across all container-fixture overlays is simpler than a special case now.
- Update 2026-09-08: the line is `testcontainers[rabbitmq]==4.15.0` (extra), not the datastores' bare `testcontainers==4.15.0`. `testcontainers.community.rabbitmq` imports sync `pika`; `aio-pika` (the overlay runtime) does not provide it, whereas each datastore overlay's runtime driver happens to satisfy its own testcontainers submodule. `uv` resolves the two lines as an extra-union, so the milestone-8 D-031 collapse must be extra-aware. MessagingEngineer-2 also fixed a latent bug in the same fragment: the `rabbitmq_channel` fixture was always the autouse fake with an unused `rabbitmq_container` fixture, so integration mode never hit a broker; it now switches container-backed under `tests_integration` like the datastores.

## D-034: generated-project mypy scope includes `tests/`

- Date: 2026-09-08
- Status: confirmed
- Decision: The base `pyproject.toml.jinja` `[tool.mypy]` `files` list includes `tests` alongside the package, so the generated project's CI type-checks its test suite (including the assembled `tests/conftest.py` that overlay fragments contribute to). Currently `files = ["{{ python_package }}"]` only, so the assembled conftest is ruff-checked but not mypy-checked in generated CI.
- Rationale: TestingHarness-2 flagged it as a "conscious choice" gap. Overlay conftest fragments are real typed code; a type error in one would ship silently. The base template's own tests are already mypy-checked, so generated projects should match. One-line base change; assign to the next base-template pass (folds cleanly with any Phase 3 base work). Non-blocking for the Phase 2 flips. Follow-on: the base pass that adds `tests` to mypy scope must also ensure overlay `conftest.py.jinja` fragments are fully typed (MessagingEngineer-2-2 noted the `_RabbitmqFake*` classes in the assembled conftest are currently untyped and only pass because `tests/` is out of the generated CI mypy scope).

- Update 2026-09-09: DEFERRED to a dedicated typing pass, NOT folded into the D-037 base pass. BaseTemplateEngineer-2 found it pervasive: adding `tests` to `[tool.mypy] files` breaks `mypy --strict` on the zero-overlay base itself (6 errors: untyped `client`/`app` params in `tests/conftest.py.jinja` + `tests/test_app_boots.py.jinja`), and `pydantic.mypy` does not help (`no-untyped-def`, not `call-arg`). Untyped overlay conftest fragments that would surface: `api_grpc` (`grpc_channel`), `messaging_rabbitmq` (`_RabbitmqFake*` classes + `rabbitmq_channel`, pervasive), `otel_tracing` (`otel_span_exporter`), `streaming_grpc` (`grpc_stream_stub`), `streaming_sse` (`sse_client`), `tool_scaffold` (`tool_client`). Clean already: all 4 db overlays, llm_openai, llm_anthropic. Required order: (a) type base `tests/conftest.py.jinja` + `tests/test_app_boots.py.jinja` + every `tests/overlays/test_*_boots.py.jinja` fixture/param; (b) the 6 owning engineers type their fragments; (c) then `files = ["{{ python_package }}", "tests"]`. Own chunk of work - schedule as a Phase 4 or wrap-up cleanup pass, do not attach to unrelated work.


## D-035: `mcp_server` tests the in-process MCP path; HTTP transport is present but best-effort in v1

- Date: 2026-09-09
- Status: confirmed
- Decision: The `mcp_server` overlay builds an `MCPServer` (mcp SDK v2, `from mcp.server import MCPServer`; `mcp==2.2.0`, research pin holds) and registers the same shared handler functions that back the REST (`tool_scaffold`) or gRPC (`api_grpc`) surface as `@mcp.tool()` - one implementation. The proves-it-boots + tool-list contract test runs in-process against the SDK's in-memory client<->server pair (no stdio, no HTTP), deterministic and offline. The streamable-http mount (`Mount("/mcp", app=mcp.streamable_http_app())`) ships via the `api_router.py` slot but is NOT on the boots-test critical path - the boots test only asserts the route is registered.
- Rationale: AIComponentsEngineer's upstream re-verification found mounting the MCP streamable-http app onto an existing FastAPI app has a known lifespan-chaining sharp edge (upstream issue #1367) that is fragile to make deterministic. The in-process/stdio path is the v1 tested contract; an "MCP-over-HTTP actually serves" check is `tests_integration`-gated or BACKLOG. If the session-manager lifespan can be chained into the base `create_app` lifespan deterministically, the overlay does that, but is not blocked on it. `overlays/mcp_server/OVERLAY.md` documents the caveat.

## D-036: `monorepo` / `multi_repo` use orchestrated per-service renders, not a single `{% yield %}` run (supersedes the mechanism in D-017)

- Date: 2026-09-09
- Status: confirmed
- Decision: Multi-service topology is produced by orchestration in the generator, not one giant Copier render:
  1. For each entry in `service_names` (frozen list order), run a normal `single`-style Copier render driven by that service's effective answer set (registry defaults + shared top-level keys + `services_config[<svc>]` submap). `monorepo` renders into `services/<svc>/`; `multi_repo` renders into a separate output dir per service. Same code path, different destination.
  2. Then one thin root render: root `docker-compose.yml` (one app block per service, wired by service name over the selected transport), root `README.md`, shared `proto/` + `buf.yaml`, root CI workflow, and a root `.copier-answers.yml` manifest carrying `topology` + `service_names` + `services_config` + shared keys.
  3. Each `services/<svc>/` keeps its OWN `.copier-answers.yml` (Copier's native per-run model). `copier update` = per-service update of each `services/<svc>/` + re-render of the root layer.
- This supersedes D-017's "one Copier run, `{% yield %}` over `service_names`, one root `.copier-answers.yml`, no per-service answers files" and the single-run parts of overlay-contract §3.3 / §8.1. D-017's `services_config` intent (per-service overlay selection, shared vs per-service split) stands.
- Rationale: TopologyEngineer showed the single-run `{% yield %}` mechanism forces (a) a yield ancestor into every frozen base path (against D-016), (b) a gate-expression rewrite in all 11 shipped overlays plus every Phase 3 overlay from `db_postgres` to `services_config[_svc].db_postgres` (against overlay-contract §3.2 rule 2), and (c) an unverified reliance on empty-yield-item path collapse for `single` to stay byte-identical. The orchestrated model needs ZERO base or overlay changes, keeps `single` provably byte-identical, gives a simpler determinism argument (N deterministic renders in frozen order + one deterministic root render), unifies `monorepo` and `multi_repo`, and makes per-service `copier update` granularity fall out for free (removes that BACKLOG item).
- Owners: the orchestration loop lives in a new `msvc_gen/topology.py` module that `cli.py` calls only when `topology != single` (cli.py stays a thin wrapper for `single`). TopologyEngineer owns `topology.py` + the root-layer templates + the transport wiring + `tests_contract`. RegistryArchitect-2 rewrites overlay-contract §3.3/§8.1 and integrates the `services_config` schema.

## D-037: base changes to support class-2 secret env vars (required, no default) - `llm_*`, `langsmith`

- Date: 2026-09-09
- Status: confirmed
- Decision: Three base-template changes, owned by BaseTemplateEngineer, so an overlay can declare a `required: true, secret: true, no-default` env var (D-030 class 2) without breaking `mypy --strict` or pytest collection:
  1. Add `plugins = ["pydantic.mypy"]` to base `pyproject.toml.jinja` `[tool.mypy]`. Without it, `return Settings()` in `config/settings.py` trips `mypy --strict` "Missing named argument" for a no-default field. `pydantic` is already a base dep; this is the standard pydantic-settings answer, zero other effect.
  2. Make the `from {{ python_package }}.main import create_app` import in base `tests/conftest.py.jinja` LAZY (inside the `app` fixture body, not module scope). `main.py` builds `app = create_app()` -> `Settings()` at import, so a module-scope import raises `ValidationError` at pytest collection before any fixture runs. Lazy import is backward-compatible; existing overlays unaffected. Overlay boots tests already keep their `main`/`app` imports inside test functions.
  3. Collection-time env seeding: an overlay needing a placeholder for its class-2 var at collection time seeds it via its autouse mock fixture (`monkeypatch.setenv(...)`), which runs before the `app` fixture. Only if a genuine non-fixture collection-time need exists (rendered-conftest lint/type check) does BaseTemplateEngineer add a dedicated `conftest_env.py` fragment slot near the top of base `tests/conftest.py` (the one sanctioned collection-time side effect, kept separate from the fixture-only `conftest.py` slot). AIComponentsEngineer + BaseTemplateEngineer settle which, based on whether the autouse route covers it.
- Also folded into this base pass: D-034 (base `pyproject.toml.jinja` `[tool.mypy]` `files` gains `tests`), since it touches the same block.
- Rationale: AIComponentsEngineer hit this building `llm_openai`; it blocks the whole `llm_*` / `langsmith` set. Same class of shared-mechanism gap as D-027 / D-032 - overlays cannot fix base-owned files.

- Landed 2026-09-09 (BaseTemplateEngineer-2): items 1 (pydantic.mypy plugin) + 2 (lazy `create_app` import) applied and verified (zero-overlay clean, diff is exactly those two changes; otel 7/7; llm_openai alone 8/8 ruff/mypy/pytest, double-render byte-identical). Item 3: chose the AUTOUSE-FIXTURE route - each `llm_*` overlay autouse mock fixture does `monkeypatch.setenv(...)` + `get_settings.cache_clear()` before the `app` fixture; NO `conftest_env.py` slot added. Consequence: the pre-interruption `_fragments/llm_openai/conftest_env.py.jinja` + `_fragments/llm_anthropic/conftest_env.py.jinja` are DEAD (no slot to receive them) - AIComponentsEngineer-2 deletes them. Item 4 (D-034) was NOT folded in - see D-034 update.

## D-038: Lead builds directly, speed over verification, deferred checks become new phases 6-8

- Date: 2026-09-09
- Status: confirmed (owner directive)
- Decision: The multi-agent build has been repeatedly stalled by worker session-limit failures, cold-start re-spawns, and shared-tree collisions between resumed originals and their replacements. Per the owner: the Lead now builds the remaining boilerplate components DIRECTLY, fast, with minimal inline verification (renders + imports, not the full compose-boot / mypy --strict / double-render-diff / combinatorial-harness gate). Git commits are made per phase. The main phase structure (3, 4, 5) is unchanged in scope. The verification work being skipped now is captured as new phases appended after Phase 5:
  - **Phase 6 - Combinatorial verification**: the full `harness/run.py` gate across every valid overlay combination; per-overlay `docker compose up --wait` real-container boot; `ruff` + `mypy --strict` on every rendered combo; double-render byte-identity; `copier update` DoD per overlay.
  - **Phase 7 - Hardening**: D-034 (generated CI mypy-checks `tests/` - type the base test fixtures + the 6 untyped overlay conftest fragments); MCP-over-HTTP integration test (upstream #1367); `buf` contract-test tooling real wiring; every BACKLOG item; the langgraph non-determinism review.
  - **Phase 8 - Release**: DevOps - SemVer tag, push to the private repo, `copier update` CI against real tags, the D-025 GitHub App token deployment, pipx publish path.
- Rationale: Owner priority is a complete set of boilerplate components now; correctness sweeps are batched into dedicated phases where they can run without blocking component delivery.

## D-039: `crud_scaffold` overlay - initial data CRUD operations with entity-named REST endpoints

- Date: 2026-09-09
- Status: confirmed (owner directive)
- Decision: A new `crud_scaffold` overlay (in `overlay_order` right after `db_qdrant`) ships a working async CRUD slice for one user-named entity. Keys: `crud_scaffold` (bool gate), `crud_entity` (identifier, validator `^[a-z][a-z0-9_]{0,30}$`, default `item`), `crud_backend` (computed: `postgres` if `db_postgres` else `mongodb` if `db_mongodb` else `redis` - the overlay hard-requires one of `db_postgres` / `db_mongodb` / `db_redis`).
  - `{{ python_package }}/data/models.py` - pydantic `<Entity>Create` / `<Entity>Update` / `<Entity>` plus, for `crud_backend == postgres`, a SQLAlchemy `<Entity>Row(Base)` mapped to table `<entity>s`.
  - `{{ python_package }}/data/repository.py` - `<Entity>Repository(Protocol)` with 7 async methods (`create` `get` `list` `update` `delete` `count` `exists`), an `InMemory<Entity>Repository` used by the offline test fixture, and exactly one backend-concrete class (`Postgres` / `Mongo` / `Redis`) selected at render time. `get_repository()` is the FastAPI dependency provider; the Postgres impl opens a short session per operation via the shared `get_session_factory()` (no request-scoped `Depends(get_session)`, which FastAPI resolves eagerly and breaks the test override).
  - `{{ python_package }}/data/routes.py` - `APIRouter(prefix="/<entity>s", tags=["<entity>s"])` with `POST ""` (201), `GET ""` (limit/offset), `GET "/count"`, `GET "/{id}"` (404), `PATCH "/{id}"` (404), `DELETE "/{id}"` (204). Mounted via the `api_router.py` fragment slot.
  - Tests: an autouse `conftest.py` fragment swaps `get_repository` for the in-memory store; `tests/overlays/test_crud_scaffold_boots.py` drives the full HTTP create/get/count/list/patch/delete/404 lifecycle over `ASGITransport`, fully offline.
  - `includes/answers_helpers.jinja` `overlay_order` list + `_gates` dict updated (they carry their own hardcoded mirror of `registry.yaml`). `PER_SERVICE_KEYS` (validate_registry.py) + `PER_SERVICE_ALLOWED_KEYS` (topology.py) gained the three crud keys so a per-service submap can select it under `monorepo` / `multi_repo`.
- Rationale: Owner asked for "initial code for the microservices to interact with data - adding, updating, finding all, finding one by id, deleting - for postgres, mongo and maybe redis" with "relevant endpoints that match the entity name". This is the minimal working slice. Richer operations (filtering, pagination cursors, bulk ops, soft-delete, search) stay in BACKLOG for a Phase 7 pass.

## D-040: every generated service ships a formatter + a commit-blocking pre-commit hook, by default

- Date: 2026-09-09
- Status: confirmed (owner directive)
- Decision: The base template (unconditional, no registry key) now ships:
  1. `[tool.ruff.format]` in `pyproject.toml` (`docstring-code-format = true`) - ruff is the formatter, standard made explicit.
  2. `.pre-commit-config.yaml` with two `repo: local` / `language: system` hooks - `ruff format` and `ruff check --fix` - that shell out to the project's own pinned ruff (from `uv.lock`). No external hook repo, no `rev` to keep in sync with the `ruff==` pin, no network fetch, no build step. The hook, `pyproject.toml`, and CI are guaranteed to use the identical ruff.
  3. `pre-commit==4.3.0` in the `dev` dependency group.
  4. A copy-only `_task` (argv, D-012): `uv run python -c "... subprocess.call(['pre-commit','install']) if os.path.isdir('.git') else 0"` - activates the hook when generating into an existing git repo, silent no-op otherwise. Plain `install` (not `--install-hooks`), so it needs no network and cannot fail generation; hook envs are trivial for `language: system`. Touches `.git/hooks/`, never the rendered tree, so double-render byte-identity holds.
  5. README "Git hooks" section: `uv run pre-commit install` for the standalone-then-`git init` flow.
- Rationale: Owner: "add to the microservices code formatters and a git action that prevents committing if the code format is not matching the standard." CI already ran `ruff format --check` + `ruff check`; this adds the local gate so a mis-formatted commit is stopped before it is made. Verified end-to-end: a mis-formatted staged file is blocked, a clean one passes; `ruff` / `mypy --strict` / `pytest` (7) green on a `db_postgres`+`crud_scaffold` render; double-render byte-identical; `pre-commit==4.3.0` resolves in `uv lock`.
- Not chosen: the `astral-sh/ruff-pre-commit` + `pre-commit/pre-commit-hooks` remote-repo form. It needs a network fetch (and a Python build env for `pre-commit-hooks`) on first run, which is fragile offline and would drift from the `ruff==` pin. The `repo: local` form is strictly better for this codebase's offline/deterministic discipline.

## D-041: `claude_hooks` overlay - vendor Claude Code hooks into the generated service's `.claude/`, selectable per project

- Date: 2026-09-09
- Status: confirmed (owner directive)
- Decision: A new `claude_hooks` overlay (last in `overlay_order`) vendors a curated subset of [karanb192/claude-code-hooks](https://github.com/karanb192/claude-code-hooks) (MIT, Copyright (c) 2026 Karan Bansal, upstream commit `18b77a5c3eb1a55c098b05419c0ed3bc82301cee`) as **pure checked-in JavaScript** under `.claude/hooks/`, plus a generated `.claude/settings.json` that wires only the selected hooks.
  - Keys: `claude_hooks` (bool master gate, default `true`) + six sub-option bools, each `when: "claude_hooks"`: `hook_guard_pack` (default true), `hook_format_code` (true), `hook_protect_tests` (true), `hook_auto_stage` (false), `hook_session_logger` (false), `hook_instructions_audit` (false).
  - Each `hook_*` gates BOTH the `.js` file copy (per-file name gate, `lib/` a path-segment gate) AND its `settings.json` block - an unselected hook leaves no dead code. `guard-pack.js` ships with its `hooks/lib/{block-dangerous-commands,protect-secrets,git-safety,protect-tests,case-insensitive-guard,config-guard}.js` (it loads them by `__dirname`).
  - `.claude/settings.json.jinja` builds the `hooks` mapping with a Jinja `namespace` + `dict()` merge and emits it via `| tojson(indent=2)` - deterministic, comma-safe. Commands are `node "$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.js"`.
  - `.claude/.gitignore` ignores `settings.local.json`. `.claude/hooks/VENDORED.md` carries provenance + the upstream MIT text.
  - Vendored `.js` is Jinja-token-free, so `.js.jinja` renders byte-identical to upstream (verified).
  - `includes/answers_helpers.jinja` `overlay_order`/`_gates`, `SHARED_PASSTHROUGH_KEYS` (topology.py - `.claude/` renders per service dir from the shared answer), and `docs/services-config-schema.md` §2.1 updated. `claude_hooks`/`hook_*` are NOT per-service selectable (not in `PER_SERVICE_KEYS`).
  - Boots test `tests/overlays/test_claude_hooks_boots.py`: settings.json is valid JSON wiring the selected hooks; selected scripts vendored + unselected absent; `node --check` each script when node is on PATH.
- Rationale: Owner: "load the pure code for the hooks ... from https://github.com/karanb192/claude-code-hooks and they should also be configurable in the project which ones to include." Curated subset chosen (owner-approved): the dev-safety + auto-format hooks that fit a Python microservice repo; the ~15 gamification / standup / Slack / telemetry hooks are BACKLOG. Hooks need `node >=18` on PATH and fail open if absent (never block a session on their own missing runtime).
- Verified inline (D-038 fast gate): renders for default set, all-six-on, and `claude_hooks=false` (no `.claude/` at all); `ruff check` / `ruff format --check` / `mypy --strict` / generator `pytest` (32) + boots test (4) green; double-render byte-identical; vendored JS diff-clean against upstream; `node --check` passes on every script.

## D-042: `crud_scaffold` gains bulk ops, list totals, name filtering, and optional soft-delete

- Date: 2026-09-11
- Status: confirmed (Phase 7 hardening, owner-requested BACKLOG item)
- Decision: `crud_scaffold` (D-039) is enriched, backward-compatibly for the existing keys:
  1. **Bulk operations**: `bulk_create` / `bulk_delete` added to the `<Entity>Repository` Protocol and all four implementations (Postgres: `add_all` / a single `UPDATE`-or-`DELETE ... WHERE id IN (...)`; Mongo: `insert_many` / `update_many`-or-`delete_many`; Redis: a pipelined create, a loop of `delete()` for bulk-delete since there is no atomic multi-key conditional primitive; InMemory: loops over `create`/`delete`). Two new routes: `POST /<entity>s/bulk` (body: a JSON array of create payloads, 201, returns the created list) and `POST /<entity>s/bulk-delete` (body `{"ids": [...]}`, returns `{"deleted": N}`).
  2. **List totals**: `GET /<entity>s` now returns `{"items": [...], "total": N}` (a new `<Entity>ListResponse` model) instead of a bare array. `total` is `repo.count()` under the same filter as the page, so it reflects a `name_contains` filter, not just the unfiltered dataset. This is a breaking response-shape change to the existing endpoint, accepted per the Lead's instruction; the existing boots test assertions on `GET /<entity>s` are updated to read `.json()["items"]` / `.json()["total"]`.
  3. **Optional soft-delete**: new sub-key `crud_soft_delete` (bool, default `false`, `when: "crud_scaffold"`, registry.yaml only - not in `overlay_order`, same pattern as `crud_entity`/`crud_backend`). When on, `delete`/`bulk_delete` set `deleted_at` instead of removing the row/doc/hash (Postgres: nullable `deleted_at` column added to `<Entity>Row`; Mongo: `deleted_at` field set via `$set`; Redis: `deleted_at` hash field set, entity removed from the sorted-set index so `list`/`count` still exclude it while the hash itself is kept; InMemory: an `_deleted_at` id->timestamp dict). `get`/`list`/`count`/`exists`/`update` then treat that entity as not found. Default `false` is behavior-identical to pre-D-042 `crud_scaffold` (hard delete) - the only code path gated on `crud_soft_delete` is which branch `delete()`/`bulk_delete()` take; every other new code (bulk ops, list wrapper, filtering) is unconditional now that D-039's initial slice is enriched.
  4. **Basic filtering**: optional `name_contains` query param on `list` (and, additionally, on the existing `GET /<entity>s/count`) - case-insensitive substring match on `name`. Postgres: `ILIKE`. Mongo: `$regex` with `$options: "i"`, needle escaped via `re.escape`. Redis: no secondary index, so it scans the full sorted-set index and filters client-side (documented as such in the repository docstring) - correct but not efficient at scale, acceptable for a scaffold.
  - `PER_SERVICE_ALLOWED_KEYS` (`msvc_gen/topology.py`) and `PER_SERVICE_KEYS` (`scripts/validate_registry.py`) both gained `crud_soft_delete` alongside the existing three crud keys. `includes/answers_helpers.jinja` untouched (only the `crud_scaffold` gate itself is in `overlay_order`/`_gates`; sub-options never were).
  - The public `<Entity>` pydantic model is unchanged (no `deleted_at` field exposed) - soft-delete is meant to be behaviorally transparent to a normal API consumer: a soft-deleted entity disappears from `get`/`list`/`count` exactly like a hard-deleted one does, from the outside. This is also why the boots test needs no `crud_soft_delete`-specific branch: the autouse `crud_repository` fixture always swaps in `InMemory<Entity>Repository`, which is the only repository pytest ever exercises (offline, both `tests_integration` on and off), so the same HTTP-level assertions hold whichever value `crud_soft_delete` has.
- Rationale: BACKLOG item raised during Phase 3 (owner, 2026-09-09): "count, exists, pagination" plus more real operations, explicitly deferred to "Phase 7 (hardening) or a dedicated overlay-enrichment pass" by D-039's own rationale. Phase 7 is that pass.
- Verified (DataLayerEngineer-2): rendered `crud_scaffold` with each of `db_postgres` / `db_mongodb` / `db_redis`, and `crud_scaffold` + `crud_soft_delete=true` with `db_postgres`, against the real generated `copier.yml` - `ruff check`, `ruff format --check`, `mypy --strict` (all clean, 0 errors), and `pytest` (12/12 passing: the base 5 + the selected datastore's own boots test + `test_crud_scaffold_boots.py`'s 2 tests, since these answers files select one datastore alongside `crud_scaffold`, per D-039's `requires`) all green in every one of the four configurations; render x2 byte-identical for each (only `.copier-answers.yml` `_commit` differs - Copier dirty-worktree bookkeeping). `registry.yaml` / `gen_copier_yml.py --check` / `validate_registry.py` all clean after the new `crud_soft_delete` option block. Two real bugs caught and fixed during verification, not present in the initial draft: (1) `bulk_delete`'s `sum(1 for x in xs if await ...)` silently became an async generator under `await` inside a generator expression (`TypeError: 'async_generator' object is not iterable` at runtime) - rewritten as an explicit loop in all four backends; (2) once a class defines a method literally named `list`, mypy (2.3.1, confirmed via isolated repro) misresolves every *later* bare `list[...]` annotation in that class as a reference to the method, not the builtin generic - `bulk_delete`'s `entity_ids` parameter (the only such later occurrence) is typed `Sequence[str]` instead, documented inline in `repository.py.jinja`.
