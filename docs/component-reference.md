# Component reference

This is the exhaustive reference for the microservice generator: how to invoke
it, what topology means, and exactly what every implemented registry key ships
into a generated project. It complements, rather than replaces, the narrower
docs it cross-references (`docs/registry-schema.md`, `docs/overlay-contract.md`,
`docs/services-config-schema.md`, `docs/non-interactive.md`).

Every fact below traces to `registry.yaml` (the source of truth), the matching
`overlays/<id>/OVERLAY.md`, or a `DECISIONS.md` entry. Where `registry.yaml`
and an `OVERLAY.md` differ in emphasis, `registry.yaml` wins; no such conflict
was found while writing this document (see the closing note in this repo's
PR/commit description for the one genuine cross-doc discrepancy found).

`build_status: implemented` keys are documented here as available now. A
handful of base-scaffold keys are `build_status: planned` in the registry but
already ship as fixed, unconditional behavior of every generated project
(FastAPI, health endpoints, structured logging, Docker, CI) — the registry key
exists so overlays can reference it in a `requires`/`conflicts` expression, not
because it is a real toggle yet. Those are called out as "always present"
where relevant.

---

## 1. What this tool is and how to invoke it

The generator is a [Copier](https://copier.readthedocs.io/) template. `registry.yaml`
is the single source of truth for every question; `copier.yml` is *derived*
from it by `scripts/gen_copier_yml.py` and is never hand-edited. `msvc-gen` is
a thin CLI wrapper around `copier.run_copy` / `copier.run_update` that adds
three things raw Copier does not have: an always-explicit `--vcs-ref`, a
`--data` / `--answers-file` merge, and multi-service orchestration
(`topology != single`, see section 2). For a single-service project, `msvc-gen`
and raw `copier copy` are interchangeable.

### Installation

```sh
uv tool install msvc-gen        # or: pipx install msvc-gen
```

or, from a checkout of this repo:

```sh
uv sync
uv run msvc-gen --help
```

Raw Copier (`uv tool install copier`) also works for single-service generation;
it just cannot do the multi-service orchestration `msvc-gen` adds.

### `msvc-gen new` / `msvc-gen update`

```
msvc-gen new    --output DIR [--answers-file FILE] [--data KEY=VALUE ...] \
                [--vcs-ref REF] [--template-src SRC] [--skip-tasks] [--force] \
                [--dry-run] [--quiet]

msvc-gen update --output DIR [--answers-file FILE] [--data KEY=VALUE ...] \
                [--vcs-ref REF] [--skip-tasks] [--conflict {inline,rej}] \
                [--dry-run] [--quiet]
```

| Flag | Meaning |
| --- | --- |
| `-o, --output DIR` | required. Target directory. For a multi-service topology this is the directory that will hold `services/<svc>/` (monorepo) or `<svc>/` (multi_repo) plus the root layer. |
| `--answers-file FILE` | YAML mapping of answers. Copier-internal keys (`_src_path`, `_commit`, any `_`-prefixed key) are stripped on load, so a generated `.copier-answers.yml` can be fed straight back in. |
| `--data KEY=VALUE` | one answer, repeatable. Value is parsed as YAML (`true`, `42`, `[a, b]`, `{"k": 1}` all work). Last occurrence of a repeated key wins, and `--data` always overrides `--answers-file`. |
| `--vcs-ref REF` | template git ref (tag, branch, or commit). Default `main` (pre-v1) or `$MSVC_GEN_VCS_REF`. **Always pass this explicitly for anything beyond local iteration** — the CLI never relies on Copier's "highest PEP 440 tag" default (D-012), because that default silently changes as new tags are pushed. |
| `--template-src SRC` | template path or git URL. Default: an auto-detected source checkout, else `$MSVC_GEN_TEMPLATE_SRC`, else the packaged private-repo URL. |
| `--skip-tasks` | do not run the post-generation `uv lock` / pre-commit-install tasks. |
| `--force` | overwrite existing files without asking (`new` only, in practice). |
| `--conflict {inline,rej}` | `update` only. `rej` writes `.rej` files for unresolved hunks instead of inline `<<<<<<<` markers — easier to detect in CI. |
| `--dry-run` | render nothing to disk. |
| `--quiet` | suppress Copier's file-by-file output. |

There is no per-registry-key CLI flag. Component selection is entirely
`--data` / `--answers-file`, so the flag surface never drifts from
`registry.yaml`.

### Raw Copier (equivalent for single-service)

```sh
copier copy --defaults --trust --data-file answers.yml \
  --vcs-ref v0.4.0 --skip-tasks <template-src> ./my-service
```

`msvc-gen new` for a single service does exactly this plus explicit ref
handling and the `--data`/`--answers-file` merge. Raw `copier copy` cannot do
`monorepo` / `multi_repo` — it renders one service tree only.

### Precedence

Highest wins: `--data` > `--answers-file` > the registry default for a
question. `cli.py` builds the answer set as `answers_file` then `--data` on
top; Copier fills every still-unset question from its `registry.yaml`
default.

### Non-interactive mode

`msvc_gen/cli.py` always calls Copier with `defaults=True`. With that flag
Copier never opens a prompt: it takes the supplied answer or the registry
default, and a question with neither is a hard error, not a prompt. Exactly
one question in the whole registry has no default: `service_name`. Everything
else is answerable purely from `--data` / `--answers-file`, so the generator
never blocks waiting for input and never guesses (scope §6). Full detail,
including how to supply `services_config` from the command line as a JSON
string: `docs/non-interactive.md`.

The generator **rejects** an invalid or incomplete answer set; it never
repairs one. Cross-key rules (`registry.yaml` `validation_rules`) are compiled
into Copier `validator` blocks and abort the run with the rule's message. For
multi-service topology, `msvc_gen/topology.py` additionally replays the
per-service `services_config` rules (V-15..V-20 plus a per-service V-2..V-14
replay) via `scripts/validate_registry.py` **before any render**.

### Private-repo access

The template lives in one private GitHub repo. Developer laptops use normal
SSH/HTTPS auth; downstream CI that runs `copier update` / `msvc-gen update`
against it authenticates with a short-lived GitHub App installation token
(interim: a read-only SSH deploy key for a small number of consumer repos).
Full setup steps, the App vs. PAT vs. deploy-key comparison, and the exact CI
workflow snippet: `docs/private-template-access.md` (D-025).

---

## 2. Topology

`topology` (str, choices `single` / `monorepo` / `multi_repo`, default
`single`) selects the output layout (D-005). Multi-service output
(`monorepo` or `multi_repo`) is produced by **orchestration in the CLI**, not
a single giant Copier render (D-036, `msvc_gen/topology.py`): one ordinary
`single`-style Copier render per entry in `service_names` (in frozen list
order), each driven by that service's *effective answer set*, plus one thin
root wiring layer rendered with a plain Jinja environment (no Copier, no
overlay fragments). `cli.py` dispatches to `topology.py` only when
`topology != 'single'`; the `single` code path is untouched and its output is
byte-identical to a build with no topology overlay at all.

### `single`

The default. One project, written straight into `--output DIR`.

### `monorepo`

One repo, one root layer, N complete standalone service trees under
`services/<name>/`:

```
<output>/
  .copier-answers.yml        # root manifest: topology, service_names, services_config, shared keys
  docker-compose.yml         # one app container per service + a namespaced-once backing service per datastore/broker any submap selects
  README.md                  # roster table, transport summary, run/test/update instructions
  proto/                     # shared inter-service contract (transport_grpc or any api_grpc service)
  buf.yaml                   # only when tests_contract
  .github/workflows/ci.yml   # matrix over service dirs; a proto-contract job when tests_contract
  services/
    api/                     # its own pyproject.toml, uv.lock, tests/, Dockerfile, .copier-answers.yml
    worker/
      ...
```

`copier update` for a monorepo = `copier.run_update` per `services/<svc>/` +
a wholesale re-render of the root layer, all driven from the root
`.copier-answers.yml` manifest (not re-discovered from disk).

### `multi_repo`

The same per-service renders, but each service is a fully independent repo
directory (`<output>/<svc>/`) rather than a subdirectory of one repo. The
same root wiring content (proto tree, CI) is emitted redundantly, byte-
identically, into each repo. There is no single root compose or README shared
across repos — `msvc-gen new` writes one root manifest per invocation
alongside the per-service directories it created.

### `service_names` and `services_config`

`service_names` (type `yaml`, default `["api"]`, `when: topology != 'single'`)
is the explicit, ordered, frozen service roster. The generator never invents
or infers a name.

`services_config` (type `json`, default `{}`, `when: topology != 'single'`) is
a JSON object `{"<service-name>": {<per-service submap>}}`. Every top-level key
must appear verbatim in `service_names`; a name present in `service_names` but
absent from `services_config` renders as an all-defaults service. A key is
either **shared** (answered once, applies to the whole mesh) or **per-service**
(may differ between services) — never both. Full table:
`docs/services-config-schema.md` §2.1/§2.2. Summary:

**Shared (top level only, not allowed inside a submap):**

`topology`, `service_names`, `services_config`, `transport_grpc`,
`transport_rabbitmq`, `tests_contract`, `service_name` (the repo/project name,
distinct from each entry in `service_names`), `license`, `ci`, `iac`,
`logging_structured` (computed), `claude_hooks` + all six `hook_*`,
`python_version` (computed), `api_rest` (computed), `healthchecks` (computed),
`registry_version` / `selected_overlays` (computed/audit).

**Per-service (allowed inside a submap, exactly the 20 `overlay_order` ids
minus the two transports, plus their sub-options, plus per-service testing/
packaging choices):**

```
api_grpc, streaming_sse, streaming_grpc, tool_scaffold, mcp_server,
db_postgres, db_mongodb, db_redis, redis_pubsub, db_qdrant,
messaging_rabbitmq, crud_scaffold, crud_entity, crud_backend,
crud_soft_delete, llm_openai, llm_anthropic, prompt_management, langchain,
langchain_retrieval, embedding_pipeline, embedding_backend,
embedding_vector_size, langgraph, langgraph_checkpoint, langsmith,
otel_tracing, tests_unit, tests_integration, llm_response_mode, docker
```

Any key not on this list appearing in a submap is a validation error (V-17 /
V-T3): no unknown keys, no shared keys inside a submap, no typos pass
silently. Two services in one monorepo may pick entirely different stacks
(different databases, different AI overlays) — each gets its own
`pyproject.toml` and `uv.lock`, never a shared root lockfile.

**Important gotcha on `transport_rabbitmq`'s default.** `registry.yaml` gives
`transport_rabbitmq` a *templated* default (`true` when `topology != 'single'`
and the user answers neither transport), so a plain Copier render of a
multi-service config with no transport answered still satisfies V-1. The
`msvc_gen/topology.py` orchestrator does **not** apply that templated default —
it reads `transport_grpc` / `transport_rabbitmq` straight off the passed data
with a plain `False` fallback. So when driving multi-service generation
through `msvc-gen`, set at least one transport explicitly; V-1 will reject a
run with neither.

### `transport_grpc` / `transport_rabbitmq`

Both `bool`, `when: topology != 'single'`, gate the shared inter-service
transport fabric (overlay ids `transport_grpc` / `transport_rabbitmq`, split
from a former multiselect per D-020). At least one must be true when
`topology != 'single'` (V-1). Detail is in section 3's topology group below.

### `tests_contract`

`bool`, default `false`, group `testing`, `when: topology != 'single'`,
requires `topology != 'single' and transport_grpc` (V-11). Adds `buf lint` +
`buf breaking` (with a no-toolchain descriptor-set fallback) to the **root**
CI job, guarding the shared `proto/` tree. Never rendered per-service.

### Worked example: a 2-service monorepo

```sh
msvc-gen new --output ./shop-platform --vcs-ref v0.4.0 \
  --answers-file ci/answers/monorepo-2svc.yml
```

`ci/answers/monorepo-2svc.yml` (real file in this repo):

```yaml
service_name: shop-platform
topology: monorepo
service_names: [api, worker]
transport_grpc: true
transport_rabbitmq: true
tests_contract: true
license: proprietary
ci: github_actions
services_config:
  api:
    api_grpc: true
    db_postgres: true
    tool_scaffold: true
  worker:
    messaging_rabbitmq: true
    db_redis: true
```

Constraint chain this satisfies: `topology != single` needs a transport (V-1)
— both are set; `tests_contract` needs `topology != single and transport_grpc`
(V-11); `transport_grpc` needs at least one service exposing `api_grpc` (V-18)
— `api` does; every `services_config` key (`api`, `worker`) appears in
`service_names` (V-15).

Equivalent via `--data` (JSON string for `services_config`, parsed as YAML so
JSON is accepted):

```sh
msvc-gen new -o ./shop-platform --vcs-ref v0.4.0 \
  --data service_name=shop-platform \
  --data topology=monorepo \
  --data 'service_names=[api, worker]' \
  --data transport_grpc=true --data transport_rabbitmq=true \
  --data tests_contract=true \
  --data 'services_config={"api": {"api_grpc": true, "db_postgres": true, "tool_scaffold": true}, "worker": {"messaging_rabbitmq": true, "db_redis": true}}'
```

---

## 3. Every implemented component

Groups and order follow `registry.yaml` (`base`, `api`, `data`, `messaging`,
`topology`, `ai`, `testing`, `observability`, `packaging`). Non-interactive
setting is always `--data <key>=<value>` (or the equivalent line in an answers
file / `services_config` submap).

### 3.0 Base group — always present

These are not real toggles yet (`build_status: planned`), but every generated
project gets them unconditionally, and overlays reference them in `requires`
expressions:

| Key | Default | What it is |
| --- | --- | --- |
| `service_name` | *(required, no default)* | Kebab-case identity, `^[a-z][a-z0-9-]{1,48}$`. The only question with no default. |
| `service_slug` (computed) | `{{ service_name }}` | Normalized slug. |
| `python_package` (computed) | `{{ service_slug\|replace('-','_') }}` | Import package name; every overlay path is rooted here. |
| `python_version` (computed) | `3.12` | Only version supported in v1 (D-004). |
| `api_rest` (computed) | `true` | The FastAPI app is always present; not a toggle in v1 (D-018). |
| `license` | `proprietary` | Choices: `proprietary`, `mit` (`MIT`), `apache_2_0` (`Apache 2.0`). Only affects `LICENSE` / README footer text. |
| `logging_structured` (computed) | `true` | structlog (`structlog==26.1.0`) + a vendored correlation-ID middleware (D-011, D-026) — every request gets an `X-Request-ID` (generated if absent), echoed on the response and attached to every log line. |
| `healthchecks` (computed) | `true` | `GET /health/live` (liveness, no dependency checks) and `GET /health/ready` (aggregates one check per selected component). |

Also unconditional, not registry-gated at all: `pyproject.toml` (hatholding
build backend, uv dependency manager, committed `uv.lock`, PEP 735
`[dependency-groups].dev`), a multi-stage `Dockerfile` on
`python:3.12-slim-bookworm` (non-root, exec-form `CMD`), a `.pre-commit-config.yaml`
with local `ruff format` / `ruff check --fix` hooks that block a mis-formatted
commit (`pre-commit==4.3.0`, D-040), and a `pytest` suite with an offline mock
fixture per selected component.

---

### 3.1 API group

#### `api_grpc`

- **Set**: `--data api_grpc=true`
- **What**: an async (`grpc.aio`) gRPC server co-hosted in the FastAPI
  lifespan, with the standard gRPC health service, server reflection, and
  committed generated stubs (no build-time codegen, D-009).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/grpc/` — `service.py` (`ExampleServicer`: one unary
    `Greet`, one server-streaming `Ticks`), `server.py` (`GrpcRuntime`: builds
    the server, wires `ExampleService` + `grpc.health.v1.Health` + reflection,
    sets health to SERVING, graceful shutdown), `client.py` (`open_channel`/
    `example_stub` helpers), `_pb/example/v1/` (committed `example_pb2.py`,
    `example_pb2.pyi`, `example_pb2_grpc.py`).
  - `proto/example/v1/example.proto` (schema source of truth) and
    `proto/regen_proto.py` (pinned-toolchain regenerator).
  - Python deps: `grpcio==1.83.1`, `grpcio-health-checking==1.83.1`,
    `grpcio-reflection==1.83.1`, `grpcio-status==1.83.1`, `protobuf==7.36.1`
    (runtime); `grpcio-tools==1.83.1` (dev group, regen only).
  - Env vars: `APP_GRPC_HOST` (str, not required, default `0.0.0.0`),
    `APP_GRPC_PORT` (int, not required, default `50051`).
  - No compose service.
  - Health check: `check_api_grpc` (dials the co-hosted server over loopback,
    calls the gRPC health `Check` RPC).
  - CI: adds a `test`-job step that runs `proto/regen_proto.py` then
    `git diff --exit-code`, so the committed stubs can never drift.
  - Tests: `tests/overlays/test_api_grpc_boots.py`; `grpc_channel` fixture
    (mock, pins `APP_GRPC_PORT=0` so an ephemeral port binds, no external
    service).
- **Requires/conflicts**: none of its own; other overlays (`streaming_grpc`,
  `mcp_server`, `tool_scaffold`) can require it.

#### `streaming_sse`

- **Set**: `--data streaming_sse=true`
- **What**: a Server-Sent Events example endpoint on `sse-starlette`.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/streaming/sse/routes.py` — `GET /stream/sse`:
    streams `count` numbered `tick` events then a `done` event, honours
    client disconnect. Wired into `api_router` at import time (D-032), so it
    appears in `/openapi.json` immediately, no lifespan hook.
  - Python dep: `sse-starlette==3.4.11`.
  - No env vars, no compose service, no health check, no CI step.
  - Tests: `tests/overlays/test_streaming_sse_boots.py`; `sse_client` fixture
    (mock, a plain `TestClient`).
- **Requires**: `api_rest` (V-14; always true in v1).

#### `streaming_grpc`

- **Set**: `--data streaming_grpc=true`
- **What**: a bidirectional-streaming gRPC example (`streaming.v1.ChatService`)
  added to the `api_grpc` overlay's co-hosted server.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/streaming/grpc/` — `service.py` (`ChatServicer`:
    `Chat` bidi RPC, echoes each inbound message upper-cased, preserving
    `seq`), `client.py` (`chat_stub` helper), `_pb/streaming/v1/` (committed
    `chat_pb2*`).
  - `proto/streaming/v1/chat.proto` (regenerated by `api_grpc`'s
    `regen_proto.py` in the same run as `example_pb2*`).
  - No new Python dependency — reuses `grpcio` from `api_grpc`.
  - Tests: `tests/overlays/test_streaming_grpc_boots.py` (real bidi exchange
    over loopback); `grpc_stream_stub` fixture.
- **Requires**: `api_grpc` (V-13).

#### `tool_scaffold`

- **Set**: `--data tool_scaffold=true`
- **What**: function-call-shaped FastAPI routes with OpenAPI tuned for
  function-calling consumption (D-007, the "OpenAPI half"; MCP exposure is
  the separate `mcp_server` overlay).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/tools/` — `registry.py` (`ToolSpec` +
    `ToolRegistry`, `function_schema()` renders the OpenAI
    `{name, description, parameters}` shape), `examples.py` (`echo`, `add`
    example tools with typed request/response models), `routes.py`.
  - Endpoints: `POST /tools/echo`, `POST /tools/add` (each with a stable
    `operationId`, summary, description, typed models), `GET /tools`
    (returns the function-spec catalogue). Wired via `api_router` at import
    time.
  - No new Python dependency (FastAPI + pydantic are base).
  - Health check: `check_tool_scaffold` (healthy when the tool registry holds
    ≥1 tool).
  - Tests: `tests/overlays/test_tool_scaffold_boots.py` (asserts the
    function-calling OpenAPI shape); `tool_client` fixture.
- **Requires**: `api_rest or api_grpc` (V-2; `api_rest` is always true in v1).

#### `mcp_server`

- **Set**: `--data mcp_server=true`
- **What**: registers the same handler functions that back the REST
  (`tool_scaffold`) or gRPC (`api_grpc`) surface as `@mcp.tool()` entries on
  an `MCPServer`, so the service can be plugged into an agent runtime as an
  MCP tool server.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/mcp/server.py` — `get_server()`,
    `list_tool_names()`, `get_asgi_app()`, `start_http_transport()`,
    `stop_http_transport()`.
  - Python dep: `mcp==2.2.0`.
  - Env vars: `APP_MCP_HOST` (default `0.0.0.0`), `APP_MCP_PORT` (default
    `8900`).
  - Health check: `check_mcp_server`.
  - Streamable-HTTP mount at `/mcp`, chained into the base app lifespan
    (fixed for upstream mcp issue #1367 in the Phase 7 hardening pass, D-035
    update); actually serves real MCP protocol traffic end to end now, not
    just a registered route.
  - CI: adds an MCP tool-list contract test to the unit job.
  - Tests: `tests/overlays/test_mcp_server_boots.py` (in-process contract, no
    transport) plus `tests/overlays/test_mcp_server_http.py` (a real MCP
    round trip — `initialize` → `list_tools` → `call_tool` — over an
    in-process ASGI transport, always on, no `tests_integration` gate).
- **Requires**: `tool_scaffold or api_grpc` (V-3).

---

### 3.2 Data group

#### `db_postgres`

- **Set**: `--data db_postgres=true`
- **What**: async PostgreSQL — SQLAlchemy 2.x + asyncpg engine, a
  request-scoped session dependency, an async Alembic migration environment.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/db/postgres/` — `engine.py` (`init_engine` /
    `get_engine` / `get_session_factory` / `dispose_engine`), `session.py`
    (`get_session` FastAPI dependency, rollback-on-exception), `models.py`
    (`Base` declarative base).
  - `migrations/` — `alembic.ini` (no DSN committed), `env.py` (async, reads
    the DSN from `APP_DB_POSTGRES_DSN`, `target_metadata = Base.metadata`),
    `script.py.mako`, `versions/.gitkeep`.
  - Python deps: `sqlalchemy[asyncio]==2.0.52`, `asyncpg==0.31.0`,
    `alembic==1.19.2`, `greenlet==3.5.5`; dev group `testcontainers==4.15.0`
    (only when `tests_integration`).
  - Env vars: `APP_DB_POSTGRES_DSN` (str, not required, default
    `postgresql+asyncpg://app:app@postgres:5432/app`, secret),
    `APP_DB_POSTGRES_POOL_SIZE` (int, not required, default `5`).
  - Compose service: `postgres` (`postgres:17.6`, port `5432:5432`,
    healthcheck `pg_isready -U app -d app`; compose env
    `POSTGRES_USER=app`/`POSTGRES_PASSWORD=app`/`POSTGRES_DB=app` matching the
    DSN default).
  - Health check: `check_db_postgres` (`SELECT 1` on a fresh connection,
    never raises).
  - Tests: `tests/overlays/test_db_postgres_boots.py`; `postgres_session`
    (mock, autouse `AsyncMock` engine), `postgres_container` (testcontainers,
    only when `tests_integration`).
- **Requires/conflicts**: none. Freely combinable with the other three
  datastores.

#### `db_mongodb`

- **Set**: `--data db_mongodb=true`
- **What**: async MongoDB using the PyMongo async API (`AsyncMongoClient`,
  not Motor — Motor is deprecated/EOL, D-008), no ODM.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/db/mongodb/client.py` — `init_client` /
    `get_client` / `get_database` / `close_client`.
  - Python dep: `pymongo==4.18.0`; dev group `testcontainers==4.15.0` (when
    `tests_integration`).
  - Env vars: `APP_DB_MONGODB_URI` (default `mongodb://mongodb:27017`,
    secret), `APP_DB_MONGODB_DATABASE` (default `{{ service_slug }}`),
    `APP_DB_MONGODB_SERVER_SELECTION_TIMEOUT_MS` (default `3000`).
  - Compose service: `mongodb` (`mongo:8.0`, port `27017:27017`, healthcheck
    `mongosh --eval 'db.runCommand({ping:1})'`).
  - Health check: `check_db_mongodb` (`admin.command("ping")`, never raises).
  - Tests: `tests/overlays/test_db_mongodb_boots.py`; `mongodb_db` (mock,
    spec'd `AsyncMock`), `mongodb_container` (testcontainers).
- **Requires/conflicts**: none.

#### `db_redis`

- **Set**: `--data db_redis=true`
- **What**: async Redis (redis-py asyncio) on a shared connection pool, with
  a read-through cache helper.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/db/redis/client.py` — `init_client` / `get_client`
    / `close_client`, `cache_get_or_set` helper.
  - Python dep: `redis==8.1.0`; dev group `testcontainers==4.15.0` (when
    `tests_integration`).
  - Env vars: `APP_REDIS_URL` (default `redis://redis:6379/0`, secret),
    `APP_REDIS_MAX_CONNECTIONS` (default `20`),
    `APP_REDIS_HEALTH_CHECK_INTERVAL` (default `30`).
  - Compose service: `redis` — `redis:8.0` by default; upgraded to
    `redis/redis-stack:7.4.0-v8` (also publishing port `8001`) when
    `langgraph and langgraph_checkpoint == 'redis'` (image_resolution rule
    IR-1, D-015 — `langgraph-checkpoint-redis` needs RedisJSON + RediSearch).
  - Health check: `check_db_redis` (`PING`, never raises).
  - Tests: `tests/overlays/test_db_redis_boots.py`; `redis_client` (mock),
    `redis_container` (testcontainers).
- **Requires/conflicts**: none.
- **Sub-option — `redis_pubsub`** (`bool`, default `false`, `when: db_redis`,
  requires `db_redis`, V-12): adds `{{ python_package }}/db/redis/pubsub.py`
  (`publish` reusing the shared client; `subscribe`, a dedicated-connection
  async generator) inside the same gated subtree. No separate `overlay_id`,
  fixture, or boots test — covered by an extra assertion inside
  `test_db_redis_boots.py`.

#### `db_qdrant`

- **Set**: `--data db_qdrant=true`
- **What**: async Qdrant vector store — `AsyncQdrantClient`, idempotent
  collection bootstrap, thin upsert/search helpers. Sole vector store in v1
  (D-001).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/db/qdrant/client.py` — `init_client` /
    `get_client` / `close_client`, `ensure_collection`, `upsert`, `search`
    (`query_points` under the hood).
  - Python dep: `qdrant-client==1.19.0`; dev group `testcontainers==4.15.0`
    (when `tests_integration`).
  - Env vars: `APP_QDRANT_URL` (default `http://qdrant:6333`),
    `APP_QDRANT_API_KEY` (secret, no default, optional), `APP_QDRANT_COLLECTION`
    (default `{{ service_slug }}`), `APP_QDRANT_VECTOR_SIZE` (default `384`,
    defaulted from `embedding_vector_size` when `embedding_pipeline` is also
    selected).
  - Compose service: `qdrant` (`qdrant/qdrant:v1.19.1`, ports `6333:6333`,
    `6334:6334`; healthcheck is a raw `bash`/`/dev/tcp` GET on `/readyz`
    because the image has no curl/wget).
  - Health check: `check_db_qdrant` (`get_collections()`, also validates the
    API key, never raises).
  - Tests: `tests/overlays/test_db_qdrant_boots.py`; `qdrant_client` (mock —
    a real in-process `AsyncQdrantClient(location=":memory:")`, not a
    stub), `qdrant_container` (testcontainers).
- **Requires/conflicts**: none of its own; several AI overlays require it.

#### `crud_scaffold`

- **Set**: `--data crud_scaffold=true`
- **What**: a working async CRUD slice for one example entity — repository,
  pydantic models, and a REST router (D-039, enriched with bulk ops/totals/
  filtering/soft-delete by D-042).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/data/models.py` — `<Entity>Create` /
    `<Entity>Update` / `<Entity>` pydantic models (plus, for the Postgres
    backend, a SQLAlchemy `<Entity>Row(Base)` mapped to table `<entity>s`,
    gaining a nullable `deleted_at` column when `crud_soft_delete`);
    `<Entity>ListResponse` (`items` + `total`); `<Entity>BulkDeleteRequest`
    (`ids: list[str]`).
  - `{{ python_package }}/data/repository.py` — `<Entity>Repository`
    (`Protocol`) with `create`, `bulk_create`, `get`, `list`
    (limit/offset/`name_contains`), `update` (partial), `delete`,
    `bulk_delete`, `count` (optional `name_contains`), `exists`; one
    concrete backend implementation selected at render time
    (Postgres/Mongo/Redis) plus `InMemory<Entity>Repository` used by the
    offline test fixture. `get_repository()` is the FastAPI dependency
    provider.
  - `{{ python_package }}/data/routes.py` — `APIRouter(prefix="/<entity>s")`:
    `POST /<entity>s` (201), `GET /<entity>s` (returns `{"items": [...],
    "total": N}`, honours `limit`/`offset`/`name_contains`), `GET
    /<entity>s/count` (honours `name_contains`), `GET /<entity>s/{id}` (404
    if missing), `PATCH /<entity>s/{id}` (partial update, 404 if missing),
    `DELETE /<entity>s/{id}` (204), `POST /<entity>s/bulk` (body: a JSON
    array of create payloads, 201, returns the created list), `POST
    /<entity>s/bulk-delete` (body `{"ids": [...]}`, returns `{"deleted": N}`).
    Mounted via the `api_router` fragment slot.
  - No new Python dependency.
  - No compose service, no health check of its own (rides on whichever
    datastore backs it).
  - Tests: `tests/overlays/test_crud_scaffold_boots.py` (full HTTP
    create/get/count/list/patch/delete/bulk/404 lifecycle over
    `ASGITransport`, fully offline); an autouse `crud_repository` fixture
    always swaps in `InMemory<Entity>Repository`, so the boots test exercises
    identical assertions regardless of which real backend is selected.
- **Requires**: `db_postgres or db_mongodb or db_redis` (relational,
  document, or key-value store).
- **Sub-options**:
  - `crud_entity` (str, default `"item"`, `when: crud_scaffold`, validator
    `^[a-z][a-z0-9_]{0,30}$`) — the example entity name. Class is
    capitalized (`Item`); table/collection/route prefix is `<entity>s`
    (`/items`).
  - `crud_backend` (computed, `when: false`) — the datastore the scaffold
    binds to, by priority `db_postgres > db_mongodb > db_redis`.
  - `crud_soft_delete` (bool, default `false`, `when: crud_scaffold`) —
    `delete`/`bulk_delete` set `deleted_at` instead of removing the
    row/doc/hash (Postgres: nullable column; Mongo: `$set` field; Redis: hash
    field, removed from the sorted-set index so list/count still exclude it
    while the hash is kept; InMemory: an id→timestamp dict). `get`/`list`/
    `count`/`exists`/`update` then treat that entity as not found. `false`
    (the default) is behavior-identical to hard delete; a soft-deleted
    entity is invisible to a normal API consumer either way. Run
    `alembic revision --autogenerate` after generation to create the real
    `<entity>s` table for the Postgres backend.

---

### 3.3 Messaging group

#### `messaging_rabbitmq`

- **Set**: `--data messaging_rabbitmq=true`
- **What**: RabbitMQ publisher/consumer scaffolding on `aio-pika` — robust
  connection, publisher confirms, bounded-prefetch consumer, and a
  dead-letter + TTL retry topology, all baked in (not separate keys).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/messaging/` — `client.py` (`RabbitMQ`: robust
    connection + two channels, publisher confirms, bounded-prefetch
    consumer, `set_connection_factory` test seam), `topology.py`
    (`TopologyConfig` + `declare_topology`: events exchange, DLX, work
    queue, TTL retry queue, terminal dead queue), `consumer.py`
    (`consume_with_retry` + `delivery_attempts`: reads `x-death` attempt
    count, nack→DLX retry cycle, parks on the dead queue after
    `max_attempts` or a `PermanentError`).
  - Python dep: `aio-pika==10.0.1`; dev group `testcontainers[rabbitmq]==4.15.0`
    (note the `rabbitmq` extra, not bare `testcontainers` — `aio-pika` does
    not provide sync `pika`, which that testcontainers submodule imports;
    only when `tests_integration`).
  - Env vars: `APP_RABBITMQ_URL` (default
    `amqp://guest:guest@rabbitmq:5672/`, secret), `APP_RABBITMQ_PREFETCH`
    (default `10`).
  - Compose service: `rabbitmq` (`rabbitmq:4.1-management`, ports
    `5672:5672`/`15672:15672`, healthcheck `rabbitmq-diagnostics -q ping`).
  - Health check: `check_messaging_rabbitmq` (opens and closes a channel to
    prove the broker answers).
  - Tests: `tests/overlays/test_messaging_rabbitmq_boots.py`;
    `rabbitmq_channel` (mock, fake robust connection), `rabbitmq_container`
    (testcontainers).
  - Default transport when `topology != single` if no transport is answered
    (see the multi-service gotcha in section 2).
- **Requires/conflicts**: none.

---

### 3.4 Topology group

See section 2 for the full topology/`services_config` discussion. Quick
reference for the remaining topology-group keys not already covered:

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `topology` | str, choices `single`/`monorepo`/`multi_repo` | `single` | D-005. |
| `service_names` | yaml list | `["api"]` | `when: topology != 'single'`. |
| `transport_grpc` | bool | `false` | `when: topology != 'single'`. Ships, per service: `{{ python_package }}/transport/grpc/peers.py` (`PEERS` tuple derived from `service_names`; `peer_target()` resolves `APP_PEER_<NAME>_GRPC_TARGET`, default `<peer-slug>:50051`; `peer_channel()` async context manager). Deps: `grpcio`, `grpcio-status==1.83.1`. Requires `topology != 'single'`. |
| `transport_rabbitmq` | bool | computed `true` when `topology != 'single'` else `false` (only inside a Copier render — see the gotcha in section 2) | `when: topology != 'single'`. Ships, per service: `{{ python_package }}/transport/rabbitmq/bus.py` (`connect`/`publish`/`consume` over one shared durable topic exchange; `inbox_queue_name()` = `<service_name>.inbox`). Env: `APP_TRANSPORT_RABBITMQ_URL`/exchange/prefetch settings. Dep: `aio-pika==10.0.1`. Adds a standalone `rabbitmq` compose service + `depends_on` to that service's own compose, but only when `messaging_rabbitmq` is not already selected (never duplicates the broker). Requires `topology != 'single'`. |
| `services_config` | json | `{}` | `when: topology != 'single'`. See section 2. |

Each service in a `transport_grpc` mesh exposes its **own** gRPC server only
if its own submap sets `api_grpc`; `transport_grpc` on its own only wires the
client side into every service. At least one service must set `api_grpc`
when `transport_grpc` is on (V-18), otherwise there is nothing to call.

---

### 3.5 AI group

#### `llm_openai`

- **Set**: `--data llm_openai=true`
- **What**: an `AsyncOpenAI` client bound to the FastAPI lifespan, `tenacity`
  retry around a deterministic sample call, one sample endpoint (D-002).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/llm/openai/` — `client.py` (`init_client`/
    `get_client`/`close_client`, `max_retries=0` so tenacity owns retry),
    `summarize.py` (`@retry`-wrapped one-sentence summary via Chat
    Completions, `temperature=0`), `routes.py`.
  - Endpoint: `POST /llm/openai/summarize`.
  - Python deps: `openai==3.8.0`, `tenacity==9.1.4`.
  - Env vars: `APP_LLM_OPENAI_API_KEY` (str, **required**, no default,
    secret), `APP_LLM_OPENAI_MODEL` (default `gpt-4o-mini`),
    `APP_LLM_OPENAI_TIMEOUT_S` (default `30`), `APP_LLM_OPENAI_BASE_URL`
    (default `null`, override for pointing at a local fake server in tests).
  - No compose service (external SaaS).
  - Health check: `check_llm_openai` (client built + key configured; does
    **not** call the API — a readiness probe should not burn tokens).
  - Tests: `tests/overlays/test_llm_openai_boots.py`; `openai_client`
    (autouse; default `mock_transport` mode patches in an `httpx2
    MockTransport`, `fake_server` mode points `APP_LLM_OPENAI_BASE_URL` at a
    stdlib `http.server` stub — see `llm_response_mode` in the testing
    group).
- **Requires/conflicts**: none of its own; several other overlays require an
  LLM provider (`llm_openai or llm_anthropic`).

#### `llm_anthropic`

- **Set**: `--data llm_anthropic=true`
- **What**: symmetric with `llm_openai` — an `AsyncAnthropic` client,
  `tenacity` retry, one sample endpoint.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/llm/anthropic/` — `client.py`, `summarize.py`
    (`@retry`-wrapped one-sentence summary via the Messages API, fixed
    `system` prompt — `anthropic` 1.x removed the top-level `temperature`
    argument to `messages.create`), `routes.py`.
  - Endpoint: `POST /llm/anthropic/summarize`.
  - Python deps: `anthropic==1.4.0`, `tenacity==9.1.4`.
  - Env vars: `APP_LLM_ANTHROPIC_API_KEY` (**required**, no default,
    secret), `APP_LLM_ANTHROPIC_MODEL` (default `claude-sonnet-5`),
    `APP_LLM_ANTHROPIC_TIMEOUT_S` (default `30`),
    `APP_LLM_ANTHROPIC_BASE_URL` (default `null`).
  - No compose service.
  - Health check: `check_llm_anthropic` (no network round-trip).
  - Tests: `tests/overlays/test_llm_anthropic_boots.py`; `anthropic_client`
    fixture (same `mock_transport`/`fake_server` split as `llm_openai`).
- **Requires/conflicts**: none of its own.

#### `prompt_management`

- **Set**: `--data prompt_management=true`
- **What**: versioned prompt files plus a load-time prompt registry scoped to
  prompts. The pydantic-settings loader itself is base-owned (D-021); this
  overlay adds only the prompt layer.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/prompts/` — `registry.py` (`Prompt` schema,
    `extra="forbid"`; `PromptRegistry` indexed by `(name, version)`,
    `load_registry(dir=None)`, `PromptError`), `__main__.py` (`python -m
    {{ python_package }}.prompts --check` CLI).
  - `prompts/` at the project root — example prompt files `summarize.toml`,
    `classify.toml` (TOML, parsed with stdlib `tomllib`, so no new
    dependency).
  - Env var: `APP_PROMPTS_DIR` (default `prompts`).
  - No compose service, no health check, no route.
  - CI: adds `uv run python -m {{ python_package }}.prompts --check` to the
    test job — a malformed prompt file fails the build.
  - Tests: `tests/overlays/test_prompt_management_boots.py`;
    `prompt_registry` autouse fixture.
- **Requires/conflicts**: none.

#### `langchain`

- **Set**: `--data langchain=true`
- **What**: a chat-model factory selecting the configured provider, a sample
  `prompt | model | parser` summarize chain.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/langchain/chain.py` (model factory + summarize
    chain), `routes.py`.
  - Endpoint: `POST /langchain/summarize`.
  - Python deps: `langchain==1.4.0`, `langchain-core==1.6.2`,
    `langchain-openai==1.6.0` (only when `llm_openai` is also selected),
    `langchain-anthropic==1.7.1` (only when `llm_anthropic` is also
    selected), `langchain-qdrant==1.1.0` (only when `langchain_retrieval`).
  - No env vars of its own.
  - Tests: `tests/overlays/test_langchain_boots.py`; `langchain_llm`
    autouse fixture patches `chain.build_chat_model` to return
    `FakeListChatModel` — no provider key or network needed.
- **Requires**: `llm_openai or llm_anthropic` (V-7).
- **Sub-option — `langchain_retrieval`** (bool, default `false`, `when:
  langchain`, requires `langchain and db_qdrant`, V-6): adds
  `{{ python_package }}/langchain/retrieval.py` and endpoint `POST
  /langchain/retrieve`. The boots test patches `_retrieve` to a fixed
  document list.

#### `embedding_pipeline`

- **Set**: `--data embedding_pipeline=true`
- **What**: an embedding client plus a batched ingestion job writing vectors
  into the `db_qdrant` collection.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/embeddings/embedder.py` (fastembed / OpenAI
    backends), `ingest.py` (`ingest_documents(...)`, batched, upserts to
    Qdrant).
  - Python dep: `qdrant-client[fastembed]==1.19.0` (the fastembed offline
    backend rides this extra; the OpenAI embedding backend reuses the
    `openai` client from `llm_openai`, no extra dependency).
  - Env var: `APP_EMBEDDING_BATCH_SIZE` (default `64`).
  - Health check: `check_embedding_pipeline`.
  - Tests: `tests/overlays/test_embedding_pipeline_boots.py`;
    `embedding_client` autouse fixture patches `embed_texts` to fixed zero
    vectors and `expected_dim` to the configured size — no model download,
    no Qdrant server, no OpenAI call.
- **Requires**: `db_qdrant` (V-4); and `embedding_backend == 'fastembed' or
  llm_openai` (V-8 — the `openai` backend needs the OpenAI client; fastembed
  is offline by design).
- **Sub-options**:
  - `embedding_backend` (str, choices `fastembed` ("fastembed offline
    (bge-small, 384)") / `openai` ("OpenAI (text-embedding-3-small, 1536)"),
    default `fastembed`, `when: embedding_pipeline`) — Anthropic has no
    embeddings API, so it is not an option.
  - `embedding_vector_size` (int, default `384`, `when: embedding_pipeline`)
    — feeds `APP_QDRANT_VECTOR_SIZE`. Must be a positive integer matching
    the chosen backend (fastembed bge-small = 384, enforced by a
    `requires`; OpenAI 3-small = 1536, 3-large = 3072 — not enforced beyond
    the fastembed constraint).

#### `langgraph`

- **Set**: `--data langgraph=true`
- **What**: a minimal stateful LangGraph graph behind one route,
  checkpointed to the selected store (D-006 — the only place agent-style
  control flow appears in a generated service in v1).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/langgraph/graph.py` (the `StateGraph`: `prepare ->
    respond`, state `{messages, turn}`; `respond` is a deterministic text
    transform — swap in an LLM node for a real step), `checkpointer.py`
    (store-specific saver), `routes.py`.
  - Endpoint: `POST /langgraph/run` (invokes one turn; reuse `thread_id` to
    resume from the checkpoint).
  - Python deps: `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0`, plus
    only the checkpoint driver for the selected store —
    `langgraph-checkpoint-postgres==3.1.2` + `psycopg==3.3.5` +
    `psycopg-pool==3.3.1` (psycopg3, separate from `db_postgres`'s asyncpg
    driver) when `langgraph_checkpoint == postgres`, or
    `langgraph-checkpoint-redis==0.5.2` when `redis`.
  - Health check: `check_langgraph`.
  - Tests: `tests/overlays/test_langgraph_boots.py`; `langgraph_app`
    autouse fixture patches `build_checkpointer` to an `InMemorySaver` — no
    DB, no LLM call.
- **Requires**: `db_postgres or db_redis` (V-5).
- **Sub-option — `langgraph_checkpoint`** (str, choices `postgres`/`redis`,
  default `postgres`, `when: langgraph`, requires the matching store be
  enabled, V-9): `redis` upgrades the compose `redis` service to
  `redis/redis-stack` (IR-1, D-015) since `langgraph-checkpoint-redis` needs
  RedisJSON + RediSearch.
- **Out of scope for v1** (BACKLOG): multi-node agent loops, tool-calling
  nodes, human-in-the-loop interrupts, intermediate-step streaming.

#### `langsmith`

- **Set**: `--data langsmith=true`
- **What**: LangSmith tracing hooks — `@traceable` re-exported from one
  place, plus a startup `configure()` that resolves tracing state from
  settings. Zero-overhead pass-through until an operator turns it on.
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/observability/langsmith/` — `tracing.py`
    (`TracingConfig`, `configure()`), `pipeline.py` (a sample `@traceable`
    function).
  - Python dep: `langsmith==0.12.2`.
  - Env vars: `APP_LANGSMITH_API_KEY` (**required**, no default, secret),
    `APP_LANGSMITH_PROJECT` (default `{{ service_slug }}`),
    `APP_LANGSMITH_TRACING` (default `"true"`).
  - No compose service (external SaaS), no health check (tracing liveness is
    not a readiness concern).
  - Tests: `tests/overlays/test_langsmith_boots.py`; `langsmith_tracer`
    autouse fixture forces tracing off and strips `LANGSMITH_*`/`LANGCHAIN_*`
    env at teardown.
- **Requires**: `llm_openai or llm_anthropic` (V-10 — needs a provider to
  trace).

---

### 3.6 Testing group

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `tests_unit` | bool | `true` | *(base-owned, planned)* pytest scaffolding + a mock fixture per selected component. Deps: `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `pytest-cov==7.1.0`, `anyio==4.11.0`. |
| `tests_integration` | bool | `false` | *(base-owned, planned)* testcontainers scaffolding for the selected datastores/broker. Dep: `testcontainers==4.15.0` (which containers spin up is derived from the selected overlays). |
| `tests_contract` | bool | `false` | `when: topology != 'single'`. Requires `topology != 'single' and transport_grpc` (V-11). gRPC contract tests for the shared `proto/` tree — see section 2/3.4. |
| `llm_response_mode` | str, choices `mock_transport`/`fake_server` | `mock_transport` | `when: llm_openai or llm_anthropic or langchain or langgraph`. Controls how every AI overlay's tests stub LLM traffic: `mock_transport` wraps an `httpx2.MockTransport` inside the SDK's own client; `fake_server` redirects `*_BASE_URL` to a local stub server. Never `respx`/`pytest-httpx`/`vcrpy` — those patch `httpx`, and openai 3.x / anthropic 1.x / langsmith 0.12.x run on `httpx2` (D-013). |

---

### 3.7 Observability group

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `logging_structured` | bool (computed) | `true` | See base group above; always on. |
| `otel_tracing` | bool | `false` | Documented below. |
| `healthchecks` | bool (computed) | `true` | See base group above; always on. |

#### `otel_tracing`

- **Set**: `--data otel_tracing=true`
- **What**: OpenTelemetry tracing — SDK, FastAPI instrumentation, OTLP
  HTTP/protobuf exporter (D-011 — HTTP, not gRPC, so the zero-overlay image
  never pulls `grpcio`).
- **Default**: `false`
- **Ships**:
  - `{{ python_package }}/observability/otel/tracing.py` — `setup_tracing`,
    `instrument_app`, `shutdown_tracing`. Manual in-process setup (not the
    `opentelemetry-instrument` launcher), so the run command is identical
    whether the overlay is on or off.
  - Python deps: `opentelemetry-sdk==1.44.0`,
    `opentelemetry-exporter-otlp-proto-http==1.44.0`,
    `opentelemetry-instrumentation-fastapi==0.65b0`.
  - Env vars: `APP_OTEL_EXPORTER_OTLP_ENDPOINT` (default
    `http://localhost:4318`), `APP_OTEL_SERVICE_NAME` (default
    `{{ service_slug }}`).
  - No compose service, no health check — a tracing failure must not take
    the service out of rotation.
  - Tests: `tests/overlays/test_otel_tracing_boots.py`; `otel_span_exporter`
    fixture (in-memory exporter, no network in any test).
- **Requires/conflicts**: none.

---

### 3.8 Packaging group

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `docker` | bool | `true` | *(base-owned, planned)* Dockerfile + docker-compose with only selected deps. |
| `ci` | str, choices `none`/`github_actions` | `github_actions` | *(base-owned, planned)* CI pipeline template. |
| `iac` | str, choices `none`/`compose_only` | `none` | *(reserved, planned, D-022)* Cloud-agnostic; no effect in v1 beyond recording the answer. |

#### `claude_hooks`

- **Set**: `--data claude_hooks=true` (already the default)
- **What**: vendors a curated subset of
  [karanb192/claude-code-hooks](https://github.com/karanb192/claude-code-hooks)
  (MIT, commit `18b77a5`) into the generated service's `.claude/` as pure
  checked-in JavaScript, plus a generated `.claude/settings.json` wiring only
  the selected hooks (D-041).
- **Default**: `true` (off = no `.claude/` directory at all)
- **Ships** (layout with every `hook_*` on):
  ```
  .claude/
    .gitignore              # ignores settings.local.json
    settings.json           # generated, wires only the selected hooks
    hooks/
      VENDORED.md            # provenance + upstream MIT license text
      guard-pack.js
      lib/{block-dangerous-commands,protect-secrets,git-safety,protect-tests,case-insensitive-guard,config-guard}.js
      format-code.js
      auto-stage.js
      protect-tests.js
      session-logger.js
      instructions-audit.js
  ```
  No Python dependency. Requires Node ≥18 on `PATH` for the hooks themselves
  (they fail open — Claude Code logs and continues — if node is absent, they
  never block a session over their own missing runtime); `format-code.js`
  additionally shells out to `uv run ruff` and `npx prettier`.
  Tests: `tests/overlays/test_claude_hooks_boots.py` (settings.json is valid
  JSON wiring the selected hooks; selected scripts vendored, unselected
  absent; `node --check` on each script when node is on `PATH`).
- **Requires/conflicts**: none. Not per-service selectable in a multi-service
  `services_config` submap — it is a shared, top-level answer; each service
  directory still gets its own `.claude/` rendered from that one shared
  answer.
- **Sub-options** (all `bool`, all `when: claude_hooks`):

  | Key | Default | Wires | Effect |
  | --- | --- | --- | --- |
  | `hook_guard_pack` | `true` | PreToolUse `Bash\|Read\|Edit\|MultiEdit\|Write` | Vendors `guard-pack.js` + the six `lib/` guards (dangerous shell, secret reads, unsafe git, test deletion, fs-case, config tampering) as one Node process. |
  | `hook_format_code` | `true` | PostToolUse `Write\|Edit` | Runs `uv run ruff format` + `ruff check --fix` on written Python (same ruff as pre-commit/CI, D-040) and `npx prettier` on non-Python files. |
  | `hook_protect_tests` | `true` | PreToolUse `Bash\|Edit\|MultiEdit\|Write` | Standalone guard blocking deleting/renaming-away/skip-xfail-disabling tests to fake a green suite. Redundant with `hook_guard_pack`'s bundled copy (harmless together; guard-pack's runs first) — kept selectable for guard-pack-off setups. |
  | `hook_auto_stage` | `false` | PostToolUse `Edit\|Write` | `git add`s files after Claude edits them. |
  | `hook_session_logger` | `false` | SessionStart/PostToolUse/SessionEnd | Durable markdown log of each session (files touched, bash commands) under `~/.claude/sessions` — writes to `$HOME`, not the repo. |
  | `hook_instructions_audit` | `false` | InstructionsLoaded/UserPromptSubmit/PreToolUse | Scans instruction files for hidden/hostile directives, locks the session on detection. Off by default — can be noisy on large `CLAUDE.md` trees; `HOOK_AUDIT_WARN_ONLY=true` softens it. |

  Each `hook_*` gates **both** the file copy and its `settings.json` entry —
  an unselected hook leaves no dead code. Toggle via `copier update`, never
  by hand-editing the generated `settings.json`.

---

## 4. Common recipes

Every command pins `--vcs-ref v0.4.0` as a placeholder release tag —
substitute the tag you actually want, or `main` for pre-v1 iteration. All
five recipes below are drawn directly from the real example files in
`ci/answers/`.

### A plain CRUD API (PostgreSQL, example entity `order`)

```sh
msvc-gen new --output ./orders-api --vcs-ref v0.4.0 \
  --data service_name=orders-api \
  --data db_postgres=true \
  --data crud_scaffold=true \
  --data crud_entity=order
```

Ships an async `Order` repository against Postgres and a REST router at
`/orders` (create/get/list/update/delete/bulk/bulk-delete/count), a
`postgres` compose service, and Alembic migrations scaffolding. Run
`alembic revision --autogenerate` after generation to create the real
`orders` table.

### A RAG backend

```sh
msvc-gen new --output ./rag-search --vcs-ref v0.4.0 \
  --answers-file ci/answers/rag-backend.yml
```

`ci/answers/rag-backend.yml` selects `db_qdrant` + `llm_openai` + `langchain`
(with `langchain_retrieval`) + `embedding_pipeline` (backend `openai`, vector
size `1536`) + `llm_response_mode: mock_transport`. Satisfies the constraint
chain: `embedding_pipeline` needs `db_qdrant` (V-4); `langchain` needs an LLM
provider (V-7); `langchain_retrieval` needs `langchain and db_qdrant` (V-6);
`embedding_backend=openai` needs `llm_openai` (V-8). `pytest` needs no API
key (LLM traffic is stubbed offline); a real `APP_LLM_OPENAI_API_KEY` is
needed only to run the service.

### An agent service with LangGraph

```sh
msvc-gen new --output ./agent-runner --vcs-ref v0.4.0 \
  --answers-file ci/answers/agent-langgraph.yml
```

`ci/answers/agent-langgraph.yml` selects `db_postgres` + `db_redis` +
`langgraph` with `langgraph_checkpoint: postgres`. Ships a minimal
`prepare -> respond` `StateGraph` behind `POST /langgraph/run`, checkpointed
to Postgres via `AsyncPostgresSaver` (psycopg3) so a conversation resumes on
a reused `thread_id`; Redis is along for short-term state/caching alongside
the checkpoint store. Constraint chain: `langgraph` needs `db_postgres or
db_redis` (V-5); `langgraph_checkpoint=postgres` needs `db_postgres` (V-9).

### A 2-service monorepo with gRPC between services

```sh
msvc-gen new --output ./shop-platform --vcs-ref v0.4.0 \
  --answers-file ci/answers/monorepo-2svc.yml
```

See section 2's worked example for the full breakdown — `api` (Postgres +
gRPC server + tool scaffold) and `worker` (Redis + RabbitMQ consumer), wired
by `transport_grpc` + `transport_rabbitmq`, with `tests_contract` guarding
the shared `proto/` tree.

### A service with the full dev-tooling set (pre-commit + every Claude Code hook)

The pre-commit ruff hooks (D-040) are unconditional on every generated
project; to also turn on every `claude_hooks` sub-option (three of the six
default off):

```sh
msvc-gen new --output ./tooling-demo --vcs-ref v0.4.0 \
  --data service_name=tooling-demo \
  --data claude_hooks=true \
  --data hook_guard_pack=true \
  --data hook_format_code=true \
  --data hook_protect_tests=true \
  --data hook_auto_stage=true \
  --data hook_session_logger=true \
  --data hook_instructions_audit=true
```

Ships every vendored hook script under `.claude/hooks/`, a
`.claude/settings.json` wiring all six, plus the base project's
`.pre-commit-config.yaml` (`ruff format` + `ruff check --fix`, blocking a
mis-formatted commit) and `pre-commit==4.3.0` in the dev dependency group.
