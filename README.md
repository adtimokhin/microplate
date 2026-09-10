# Microservice Boilerplate Generator

A deterministic, Copier-based generator that assembles a runnable Python backend
microservice from prewritten, pre-wired components. You choose the components
with explicit flags or an answers file; the generator renders a complete project
into a target folder. The same inputs always produce the same output. There is
no LLM anywhere in the generation path.

The services it produces are ordinary backend services (HTTP and gRPC APIs, data
stores, messaging, tracing) meant to be the building blocks of larger AI agentic
systems: a service an agent calls, a retrieval backend it queries, a tool server
it plugs in. AI pieces (LLM clients, LangChain, LangGraph, embeddings, MCP) are
opt-in overlays. Generate with none of them and you get a plain service.

- Scope and rationale: `microservice-boilerplate-generator-scope.md`
- Every resolved design question: `DECISIONS.md`
- Build status log: `STATUS.md`

## What you get

Every generated service, before any overlay, is:

- An async **FastAPI** app (`create_app()` factory plus a module-level `app`),
  Python 3.12, run under uvicorn.
- `GET /health/live` and `GET /health/ready`. Readiness aggregates one check per
  selected component and reports each one.
- Structured JSON logging (structlog) with a correlation-ID middleware that
  echoes `X-Request-ID`.
- `pyproject.toml` with exact pins, a committed `uv.lock`, and a PEP 735 dev
  dependency group. Build backend is hatchling, dependency manager is uv.
- A multi-stage `Dockerfile` on `python:3.12-slim-bookworm` (non-root) and a
  `docker-compose.yml` that stubs only the services you selected.
- A `pytest` suite with an offline mock fixture per component, plus a
  `.github/workflows/ci.yml` (lint, type-check, test, build).
- A `.copier-answers.yml` recording every answer, so `copier update` /
  `msvc-gen update` can pull template changes in later.

## One-time setup

You need:

| Tool | For | Install |
| --- | --- | --- |
| Docker | running the generated service and its datastores | https://docs.docker.com/get-docker/ |
| `uv` | dependency resolution and running the generated project | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| The generator | `msvc-gen` (or raw `copier`) | see below |

Install the generator as a single command:

```sh
# from the private template repo (URL provided by the platform team)
uv tool install msvc-gen            # or: pipx install msvc-gen
```

Or run it from a checkout of this repo:

```sh
uv sync
uv run msvc-gen --help
```

Raw Copier works too (`uv tool install copier`), it just does not do the
multi-service orchestration. See "Generate" below.

## Component menu

Every key below is `build_status: implemented` in `registry.yaml`. Select a
boolean by setting it to `true`; the rest keep their registry default. Keys not
listed here (`api_rest`, `logging_structured`, `healthchecks`) are always on.

### API layer

| Key | Default | What it adds |
| --- | --- | --- |
| `api_grpc` | `false` | An async `grpc.aio` server co-hosted in the FastAPI lifespan: one example service (unary + server-streaming), the standard health service, server reflection, and committed generated stubs plus a pinned `proto/regen_proto.py` and a CI drift guard. |
| `streaming_sse` | `false` | A Server-Sent Events example endpoint built on `sse-starlette`. |
| `streaming_grpc` | `false` | A bidirectional-streaming gRPC example added to the co-hosted server. Requires `api_grpc`. |
| `tool_scaffold` | `false` | Function-call-shaped FastAPI routes with function-calling-tuned OpenAPI: `POST /tools/<name>` per tool with a stable `operationId`, plus `GET /tools` returning the OpenAI function-spec catalogue. |
| `mcp_server` | `false` | Registers the same tool handlers on an `MCPServer` (`mcp` v2) so the service can be plugged into an agent runtime as a tool server. In-process server plus tool list is the tested contract; a streamable-HTTP mount at `/mcp` is best-effort. Requires `tool_scaffold` or `api_grpc`. |

### Data layer

| Key | Default | What it adds |
| --- | --- | --- |
| `db_postgres` | `false` | Async PostgreSQL: SQLAlchemy 2.x + asyncpg engine, a request-scoped session dependency, and an async Alembic migration environment. |
| `db_mongodb` | `false` | Async MongoDB using the PyMongo async API (`AsyncMongoClient`), no ODM. |
| `db_redis` | `false` | Async Redis (redis-py asyncio) on a shared pool, with a read-through cache helper. |
| `redis_pubsub` | `false` | Adds a Redis pub/sub helper inside the `db_redis` tree. Requires `db_redis`. |
| `db_qdrant` | `false` | Async Qdrant vector store: `AsyncQdrantClient`, idempotent collection bootstrap, thin upsert/search helpers. |
| `crud_scaffold` | `false` | An example entity plus an async repository (create/get/list/update/delete/count/exists) and a REST router at `/<entity>s`, backed by the highest-priority store you selected (`db_postgres` > `db_mongodb` > `db_redis`). Sub-options: `crud_entity` (entity name, default `item`), `crud_backend` (computed). Requires one of `db_postgres` / `db_mongodb` / `db_redis`. |

### Messaging

| Key | Default | What it adds |
| --- | --- | --- |
| `messaging_rabbitmq` | `false` | RabbitMQ publisher/consumer scaffolding on `aio-pika`: robust connection, publisher confirms, bounded-prefetch consumer, and a dead-letter + TTL retry topology with terminal parking. |

### Multi-service topology

| Key | Default | What it adds |
| --- | --- | --- |
| `topology` | `single` | `single`, `monorepo` (one repo, `services/<svc>/` folders), or `multi_repo` (one independent repo per service). Multi-service output is produced by N single-service renders plus a thin root wiring layer (D-036). |
| `service_names` | `[api]` | The service roster (a YAML list). Frozen iteration order. Used when `topology != single`. |
| `services_config` | `{}` | JSON map of service name to a per-service answers submap, so two services can pick different stacks. See `docs/services-config-schema.md` and `docs/non-interactive.md`. |
| `transport_grpc` | `false` | Wire gRPC for inter-service calls (peers discovered by service name). |
| `transport_rabbitmq` | `false` | Wire a shared RabbitMQ broker for inter-service messaging. |

### AI components (opt-in overlays)

| Key | Default | What it adds |
| --- | --- | --- |
| `llm_openai` | `false` | Async `AsyncOpenAI` client bound to the lifespan, `tenacity` retry, and a deterministic `POST /llm/openai/summarize` sample. |
| `llm_anthropic` | `false` | Async `AsyncAnthropic` client, `tenacity` retry, and a `POST /llm/anthropic/summarize` sample. |
| `langchain` | `false` | A chat-model factory for the selected provider, a `prompt \| model \| parser` summarize chain at `POST /langchain/summarize`. Sub-option `langchain_retrieval` adds a Qdrant retrieval chain at `POST /langchain/retrieve`. Requires `llm_openai` or `llm_anthropic`; retrieval also requires `db_qdrant`. |
| `embedding_pipeline` | `false` | An embedding client plus a batched ingestion job that writes vectors into the `db_qdrant` collection. Sub-options: `embedding_backend` (`fastembed` offline default, or `openai`), `embedding_vector_size` (384 / 1536). Requires `db_qdrant`; the `openai` backend also requires `llm_openai`. |
| `langgraph` | `false` | A minimal stateful LangGraph graph (`prepare -> respond`) behind `POST /langgraph/run`, checkpointed to the selected store. Sub-option `langgraph_checkpoint` (`postgres` default via `AsyncPostgresSaver`, or `redis` via `AsyncRedisSaver` with the compose image upgraded to redis-stack). Requires `db_postgres` or `db_redis`. |
| `langsmith` | `false` | LangSmith tracing hooks: `@traceable` re-exported from one place plus a startup `configure()`. Zero-overhead until an operator turns tracing on. Requires `llm_openai` or `llm_anthropic`. |
| `prompt_management` | `false` | Versioned prompt files (`prompts/*.toml`) plus a load-time prompt registry and a `python -m <pkg>.prompts --check` CLI for CI. The base settings loader stays base-owned. |

### Testing and observability

| Key | Default | What it adds |
| --- | --- | --- |
| `otel_tracing` | `false` | OpenTelemetry: SDK, FastAPI instrumentation, and an OTLP HTTP/protobuf exporter to `:4318`. |
| `tests_contract` | `false` | gRPC contract tests for the shared `proto/` tree (`buf lint` + `buf breaking`, with a descriptor-set fallback). Multi-service only; requires `transport_grpc`. |
| `llm_response_mode` | `mock_transport` | How LLM traffic is stubbed in tests: `mock_transport` (httpx2 `MockTransport`, default) or `fake_server` (a local server via `*_BASE_URL`). Never `respx`/`vcrpy`. |
| `tests_unit` | `true` | Unit test scaffolding with a mock fixture per selected component. |
| `tests_integration` | `false` | Integration test scaffolding (pytest + testcontainers) for the selected datastores/brokers. |
| `docker` | `true` | Emit `Dockerfile` + `docker-compose.yml`. |
| `ci` | `github_actions` | CI workflow template (`github_actions` or `none`). |
| `license` | `proprietary` | `proprietary`, `mit`, or `apache_2_0`. |

## Generate

### With `msvc-gen`

Non-interactive, one command. Every question comes from `--answers-file` and/or
repeatable `--data KEY=VALUE`; nothing is prompted. Only `service_name` has no
default and must always be supplied.

```sh
# minimal: a plain service
msvc-gen new --output ~/Desktop/hello-svc --vcs-ref v0.4.0 \
  --data service_name=hello-svc

# from an answers file (see ci/answers/ for complete examples)
msvc-gen new --output ~/Desktop/rag-search --vcs-ref v0.4.0 \
  --answers-file ci/answers/rag-backend.yml

# multi-service (monorepo / multi_repo needs msvc-gen, not raw copier)
msvc-gen new --output ~/Desktop/shop-platform --vcs-ref v0.4.0 \
  --answers-file ci/answers/monorepo-2svc.yml
```

`--vcs-ref` is always explicit (a release tag; `main` during pre-v1). `--data`
overrides `--answers-file` overrides the registry default. Full flag surface and
the `services_config` shape: `docs/non-interactive.md`.

### With raw Copier (single-service equivalent)

```sh
copier copy --defaults --trust --skip-tasks \
  --data-file ci/answers/rag-backend.yml \
  --vcs-ref v0.4.0 \
  <template-src> ~/Desktop/rag-search
```

`msvc-gen new` for a single service is this plus explicit ref handling and the
`--data` / `--answers-file` merge. For `monorepo` / `multi_repo`, use
`msvc-gen`: raw `copier copy` renders one service tree only.

## Where the generated code lives

`--output DIR` is exactly where the project is written. For `single` the project
root is `DIR`. For `monorepo` each service is `DIR/services/<name>/` (a complete
standalone project) with a root layer in `DIR` (`docker-compose.yml`, `proto/`,
`buf.yaml`, root CI, `.copier-answers.yml` manifest). For `multi_repo` each
service is `DIR/<name>/` as an independent repo, plus the same root manifest.

The generator never touches this repo; it only reads the template and writes to
`--output`.

## Run the generated service

From the project directory (a single service, or one `services/<name>/`):

```sh
uv sync
uv run pytest                       # offline, all component fixtures mocked
uv run uvicorn <package>.main:app --port 8000
curl -s localhost:8000/health/ready
```

With backing services (datastores, brokers):

```sh
docker compose up -d --build --wait
curl -s localhost:8000/health/ready   # each selected component reports healthy
docker compose down -v
```

Worked, tested walkthroughs with real output: `docs/usage-examples.md`.

## Update a generated service

When the template moves forward, pull the changes into an existing project
without losing your edits (Copier does a three-way merge):

```sh
# single service
cd my-service
msvc-gen update --output . --vcs-ref v0.5.0

# multi-service: re-runs copier update per services/<svc>/ and re-renders the root
msvc-gen update --output ./shop-platform --vcs-ref v0.5.0
```

The clean-apply gate and per-slice results: `docs/update-verification.md`.
Release and tagging process: `docs/release-process.md`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `registry.yaml` | Single source of truth for the question schema, pins, and validation rules |
| `copier.yml` | Generated from `registry.yaml` by `scripts/gen_copier_yml.py`. Never hand-edited |
| `template/` | The Copier `_subdirectory`: everything a generated service contains |
| `template/_fragments/` | Per-overlay fragments spliced into shared files, excluded from output |
| `includes/` | Shared Jinja macros, excluded from output |
| `overlays/` | Per-overlay `OVERLAY.md` docs, not rendered |
| `msvc_gen/` | The `msvc-gen` CLI and the multi-service orchestrator (`topology.py`, `root_templates/`) |
| `scripts/` | Registry derivation and validation, determinism and update verification, release, pin refresh |
| `ci/answers/` | Complete, valid example answers files |
| `docs/` | Contracts and process docs |
| `harness/` | Combinatorial render/boot verification harness |

## Contributor quickstart

```sh
uv sync
uv run ruff check .
uv run mypy
uv run pytest
python scripts/validate_registry.py
python scripts/gen_copier_yml.py --check
```
