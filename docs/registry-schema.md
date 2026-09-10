# Registry Schema

Version 0. Owner: Registry & Copier Architect.

`registry.yaml` is the single source of truth for the generator's question schema. `copier.yml` is derived from it by `scripts/gen_copier_yml.py`. Nothing that reaches the user exists unless it maps to a key here.

This document defines the file structure, every field, the naming rules (cross-referenced from the overlay contract), the validation rules from scope §5, and the intended interface of the derivation script. It does not define overlay internals; see `docs/overlay-contract.md`.

---

## 1. Top-level structure

```yaml
meta: { ... }              # registry-wide constants
overlay_order: [ ... ]     # frozen ordered list of overlay ids, append-only
groups: { ... }            # display groups for prompts
options: { ... }             # every registry key, keyed by key name
validation_rules: [ ... ]    # machine-checkable cross-key rules (scope §5)
image_resolution: [ ... ]    # deterministic compose image choice when a tag depends on >1 answer
compose_image_pins: { ... }  # concrete compose image tags, one owner per row (D-023)
migrations: [ ... ]          # version-gated structural changes, emitted to copier.yml
```

### 1.1 `meta`

| Field | Meaning |
| --- | --- |
| `registry_version` | Integer. Bumped on any breaking schema change to this file's shape. |
| `copier_min_version` | Minimum Copier the generated `copier.yml` requires. `9.18.2` for v0. |
| `python_baseline` | `3.12` (D-004). |
| `answers_file` | `.copier-answers.yml`. Frozen (overlay contract §8.2). |
| `env_prefix` | `APP_`. Base env var prefix for all settings. |
| `subdirectory` | `template`. |
| `build_backend` | `hatchling` (D-010). |
| `dependency_manager` | `uv`, committed `uv.lock`, `uv sync --locked` in CI (D-010). |
| `base_image` | `python:3.12-slim-bookworm` (D-010). |
| `copier_tasks_form` | `list` (argv, no shell) (D-012). |

### 1.2 `overlay_order`

Frozen, append-only list of overlay ids. Defines the only legal iteration order for shared-file assembly (overlay contract §4.2). Reordering is a breaking change and is not allowed; new overlays append.

### 1.3 `groups`

Map of `group_id -> { title, order }`. Used by the derivation script to order and section the Copier prompts. Groups: `base`, `api`, `data`, `messaging`, `topology`, `ai`, `testing`, `observability`, `packaging`.

---

## 2. `options` entry schema

Each entry is keyed by its registry key. Fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `key` | str | yes | Repeats the map key. Snake case, group-prefixed. Naming rules: overlay contract §5.1. |
| `group` | str | yes | One of `groups`. |
| `prompt` | str | yes | Question text shown in interactive mode. |
| `help` | str | no | Longer help string. |
| `type` | str | yes | `str`, `bool`, `int`, `float`, `json`, `yaml`, `path`. Copier types. |
| `multiselect` | bool | no | If true, answer is a list; `default` must be a list. |
| `choices` | list or map | when enum | List of values, or map of `label -> value`. Values are lowercase snake case, frozen once shipped. |
| `default` | any | yes | Must reproduce prior behavior for existing answers files. Booleans default `false` unless the component is part of the base (then `true`). |
| `when` | str or bool | no | Copier `when`. `false` marks a computed key (never prompted, still recorded). Otherwise a Jinja expression gating whether the question is asked. |
| `validator_rule` | str | no | Prose statement of the input constraint. The derivation script turns registry `validation_rules` and this field into Copier `validator` blocks. |
| `gate` | str | for overlays | Jinja expression that turns the overlay on. For a boolean key this is just the key name (`db_postgres`). Compound conditions belong in a computed key (`when: false`), not inline in the gate. |
| `overlay_id` | str | for overlays | Stable id. Equals `key` when the overlay has a single boolean gate. Matches fragment dir, `overlay_order` entry, health suffix. |
| `template_paths` | list[str] | for overlays | Gated top-level directories under `template/` this overlay owns. |
| `requires` | list | no | Cross-key preconditions. Each item is `{ expr, message }` where `expr` is a Jinja boolean over other answers. All must be true when `gate` is true. |
| `conflicts` | list | no | Same shape as `requires`; each `expr` must be false when `gate` is true. |
| `python_deps` | map | for overlays | `package -> { version, as_of, group? }`. Exact pins only. `as_of` is the date the pin was verified upstream. `group` is `runtime` (default, omit) or `dev` - `dev` deps land in the generated `pyproject.toml` `[dependency-groups].dev` (PEP 735) via the overlay's `dev-deps.toml.jinja` fragment, never in `[project].dependencies`. The package key may carry an extra (`"testcontainers[rabbitmq]"`, `"sqlalchemy[asyncio]"`); `uv` unions extras across overlays. v0 dev deps: `messaging_rabbitmq` `testcontainers[rabbitmq]`, `api_grpc` `grpcio-tools`. |
| `env_vars` | list | no | Each: `{ name, type, required, default, secret, description }`. `name` is `APP_`-prefixed upper snake. Must match the `settings.py` field and `.env.example` line. |
| `compose_services` | list | no | Each: `{ name, image, ports, healthcheck, notes }`. Image tags pinned. |
| `fixtures` | list | no | Each: `{ name, kind }` where `kind` is `mock` or `container`. Fixture names namespaced by overlay id. |
| `health_checks` | list[str] | no | Check function ids added to readiness (for example `check_db_postgres`). |
| `ci_steps` | str | no | What the CI fragment adds and the answer that gates it. |
| `boots_test` | str | for overlays | Path to the proves-it-boots test (overlay contract §7). |
| `build_status` | str | yes | `planned` or `implemented`. All v0 entries are `planned`. |
| `milestone` | int | yes | Scope §8 milestone that builds this. |
| `notes` | str | no | Free text. |

---

## 3. Keys by group (v0)

All keys below are defined in `registry.yaml` now, even where the overlay is built later (scope milestone 1). `build_status` is `planned` for every key in v0.

### base

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `service_name` | str | (required, no default) | Human/kebab name. `validator_rule`: `^[a-z][a-z0-9-]{1,48}$`. |
| `service_slug` | str (computed, `when: false`) | `{{ service_name }}` | Normalized slug. |
| `python_package` | str (computed, `when: false`) | `{{ service_slug|replace('-', '_') }}` | Import package name. Used in every overlay path. |
| `python_version` | str (computed, `when: false`) | `3.12` | Only 3.12 in v1 (D-004), so not prompted. Becomes a prompted `str` + `choices` when a second version lands. |
| `api_rest` | bool (computed, `when: false`) | `true` | FastAPI REST is the base. Key exists so overlays can express `requires` against it. Not user-togglable in v1. |
| `license` | str, choices | `proprietary` | `proprietary`, `mit`, `apache_2_0`. Private-repo default is proprietary. |

### api

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `api_grpc` | bool | `false` | Overlay `api_grpc`. Adds protobuf defs, committed stubs (D-009), grpc server. |
| `streaming_sse` | bool | `false` | Overlay `streaming_sse` (D-020). Requires `api_rest` (rule V-14). |
| `streaming_grpc` | bool | `false` | Overlay `streaming_grpc` (D-020). Requires `api_grpc` (rule V-13). |
| `tool_scaffold` | bool | `false` | Overlay `tool_scaffold`. OpenAPI function-call-shaped routes (D-007). Requires `api_rest or api_grpc`. |
| `mcp_server` | bool | `false` | Overlay `mcp_server`. Exposes selected endpoints as MCP tools (D-007). Requires `tool_scaffold or api_grpc`. |

### data

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `db_postgres` | bool | `false` | Overlay `db_postgres`. Async SQLAlchemy 2.x + Alembic. |
| `db_mongodb` | bool | `false` | Overlay `db_mongodb`. PyMongo async client (`AsyncMongoClient`), document models (D-008, not Motor). |
| `db_redis` | bool | `false` | Overlay `db_redis`. Cache + short-term state. |
| `redis_pubsub` | bool | `false` | Sub-option. `when: db_redis`. Requires `db_redis`. |
| `db_qdrant` | bool | `false` | Overlay `db_qdrant`. Vector store client + collection bootstrap. Sole vector store (D-001). |

All four datastores are independently selectable and combinable (scope §4.2).

### messaging

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `messaging_rabbitmq` | bool | `false` | Overlay `messaging_rabbitmq`. Publisher/consumer scaffolding, DLQ defaults, retry/backoff defaults baked in (not separate keys). |

### topology

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `topology` | str, choices `[single, monorepo, multi_repo]` | `single` | D-005. |
| `service_names` | `yaml` (free list) | `["api"]` | `when: topology != 'single'`. Explicit list; generator does not invent names. Not `multiselect` because the values are open-ended, not a fixed `choices` set. |
| `transport_grpc` | bool | `false` | Overlay `transport_grpc` (D-020). `when: topology != 'single'`. Pulls the `api_grpc` wiring for service-to-service calls. |
| `transport_rabbitmq` | bool | `false` | Overlay `transport_rabbitmq` (D-020). `when: topology != 'single'`. Pulls the `messaging_rabbitmq` wiring. At least one of `transport_grpc`/`transport_rabbitmq` required when topology is not single (rule V-1). |
| `services_config` | json (supplied) | `{}` | Per-service overlay selections for `monorepo`/`multi_repo`. `when: topology != 'single'`. Full submap schema: **`docs/services-config-schema.md`**. Each top-level property is a service name from `service_names`; its value is a submap that may carry only the per-service keys (§2.2 of that doc): every overlay gate and sub-option **except** `transport_grpc`/`transport_rabbitmq`/`tests_contract` (which are shared, top-level only), plus `tests_unit`/`tests_integration`/`llm_response_mode`/`docker`. Each service's effective submap (registry defaults ← submap ← derived identity ← shared keys) is validated against these same registry options. Consumed by orchestrated per-service renders (D-036), not a single `{% yield %}` run (supersedes D-017's mechanism; the shared-vs-per-service split stands). |

### ai

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `llm_openai` | bool | `false` | Overlay `llm_openai`. OpenAI client, key config, retry, timeout, sample deterministic endpoint (D-002). |
| `llm_anthropic` | bool | `false` | Overlay `llm_anthropic`. Anthropic client, same shape (D-002). |
| `prompt_management` | bool | `false` | Overlay `prompt_management`. Versioned prompt files + settings loader. |
| `langchain` | bool | `false` | Overlay `langchain`. Prompt templates, output parsers, LLM calls. Requires `llm_openai or llm_anthropic` (rule V-7). |
| `langchain_retrieval` | bool | `false` | Sub-option. `when: langchain`. Retrieval chain against the vector store. Requires `langchain and db_qdrant` (rule V-6). |
| `embedding_pipeline` | bool | `false` | Overlay `embedding_pipeline`. Embedding client + ingestion job to Qdrant. Requires `db_qdrant` (rule V-4); the `openai` backend also needs the OpenAI client, fastembed is offline (rule V-8). Ships fastembed (via `qdrant-client[fastembed]` extra) + OpenAI embedding client (D-014). |
| `embedding_backend` | str, choices `[fastembed, openai]` | `fastembed` | `when: embedding_pipeline`. Sub-option (D-014). `openai` requires the OpenAI client. Anthropic has no embeddings API. |
| `embedding_vector_size` | int | `384` | `when: embedding_pipeline`. Explicit Qdrant collection dimension (D-014). fastembed bge-small=384 (enforced), openai 3-small=1536, 3-large=3072. |
| `langgraph` | bool | `false` | Overlay `langgraph`. Minimal stateful graph behind one route (D-006). Requires `db_postgres or db_redis` (rule V-5). Postgres checkpoint pulls `psycopg` (psycopg3), separate from the `db_postgres` asyncpg driver. |
| `langgraph_checkpoint` | str, choices `[postgres, redis]` | `postgres` | `when: langgraph`. Selected store must itself be enabled (rule V-9). `redis` resolves the `db_redis` compose image to `redis/redis-stack` (D-015). |
| `langsmith` | bool | `false` | Overlay `langsmith`. Tracing hook. Requires `llm_openai or llm_anthropic` (rule V-10). |

### testing

| Key | Type | Default | Gate / requires |
| --- | --- | --- | --- |
| `tests_unit` | bool | `true` | pytest scaffolding + per-component mock fixtures. |
| `tests_integration` | bool | `false` | testcontainers spin-up for selected datastores/broker. |
| `tests_contract` | bool | `false` | gRPC contract tests. `when: topology != 'single'`. Requires `topology != 'single' and transport_grpc` (rule V-11). |
| `llm_response_mode` | str, choices `[mock_transport, fake_server]` | `mock_transport` | `when: llm_openai or llm_anthropic or langchain or langgraph`. Deterministic AI tests (scope §4.5). D-013: the SDKs run on httpx2, so respx/vcrpy do not intercept; stub via httpx2 `MockTransport` or redirect `*_BASE_URL` to a local fake server. |

### observability

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `logging_structured` | bool | `true` | structlog + correlation IDs. Base-level; key exists to allow opting out. |
| `otel_tracing` | bool | `false` | Overlay `otel_tracing`. OpenTelemetry SDK + FastAPI instrumentation + OTLP HTTP/protobuf exporter, endpoint default `:4318` (D-011). |
| `healthchecks` | bool (computed, `when: false`) | `true` | Health/readiness endpoints are always present (scope §4.6). Key exists for `requires`. |

### packaging

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `docker` | bool | `true` | Dockerfile + docker-compose with only selected deps. |
| `ci` | str, choices `[none, github_actions]` | `github_actions` | CI pipeline template (lint, unit, integration, build). |
| `iac` | str, choices `[none, compose_only]` | `none` | Cloud-agnostic (D-003). No cloud IaC in v1. Key reserved. |

### computed / internal

| Key | Type | Notes |
| --- | --- | --- |
| `selected_overlays` | json (computed, `when: false`) | The `selected_overlays()` helper result (list of selected overlay ids in `overlay_order`). Available to templates during rendering. Default imports the helper `with context` and does NOT re-apply `| tojson` (the macro already emits a JSON array string). No leading underscore, per the naming rule, though see the note below. |
| `registry_version` | int (computed, `when: false`) | `meta.registry_version`, for `copier update` diagnostics. `validate_registry.py` checks the two agree. |

**`when: false` keys are NOT written to `.copier-answers.yml`.** Verified against Copier 9.18.2 (BaseTemplateEngineer, 2026-09-08): Copier omits every `when: false` computed value from `_copier_answers`, independently of the leading-underscore stripping. So `selected_overlays` and `registry_version` exist only during rendering, not in the persisted answers file. This is fine for audit and for `copier update`: every overlay gate is an ordinary boolean question, so all of them ARE recorded (`api_grpc: false`, `db_postgres: false`, …) and the selected set is fully reconstructible from the answers file. If `registry_version` is ever needed IN the answers file, the answers-file template (`template/{{ _copier_conf.answers_file }}.jinja`) has to emit it explicitly; a computed key cannot get it there.

---

## 4. Validation rules (scope §5)

Encoded as `validation_rules` in `registry.yaml`, each `{ id, applies_when, expr, message }`. `applies_when` and `expr` are Jinja booleans over the answers. The rule fails (and the message is shown) when `applies_when` is true and `expr` is false. The derivation script attaches each rule to the relevant question(s) as a Copier `validator`.

A rule may also carry `scope`: `copier` (default — compiled to a Copier `validator` via `attach_to`, as above) or `services_config` (a structural predicate over the `services_config` map that Copier cannot express; `expr` is a prose statement of the predicate, `gen_copier_yml.py` never emits it as a validator regardless of `attach_to`, and it is evaluated only by `scripts/validate_registry.py` `validate_services_config(answers)`, which the `msvc-gen` CLI runs before an orchestrated `monorepo`/`multi_repo` generation — D-036).

| ID | Rule | `applies_when` | `expr` (must hold) |
| --- | --- | --- | --- |
| V-1 | Multi-service topology needs a transport | `topology != 'single'` | `transport_grpc or transport_rabbitmq` |
| V-2 | Tool scaffold needs an API layer | `tool_scaffold` | `api_rest or api_grpc` |
| V-3 | MCP server needs tool scaffold or gRPC | `mcp_server` | `tool_scaffold or api_grpc` |
| V-4 | Embedding pipeline needs Qdrant | `embedding_pipeline` | `db_qdrant` |
| V-5 | LangGraph needs a checkpoint store | `langgraph` | `db_postgres or db_redis` |
| V-6 | LangChain retrieval needs a vector store | `langchain_retrieval` | `langchain and db_qdrant` |
| V-7 | LangChain needs an LLM provider | `langchain` | `llm_openai or llm_anthropic` |
| V-8 | OpenAI embedding backend needs the OpenAI client (fastembed is offline) | `embedding_pipeline` | `embedding_backend == 'fastembed' or (embedding_backend == 'openai' and llm_openai)` |
| V-9 | LangGraph checkpoint store must be enabled | `langgraph` | `(langgraph_checkpoint == 'postgres' and db_postgres) or (langgraph_checkpoint == 'redis' and db_redis)` |
| V-10 | LangSmith needs an LLM provider to trace | `langsmith` | `llm_openai or llm_anthropic` |
| V-11 | gRPC contract tests need multi-service + gRPC transport | `tests_contract` | `topology != 'single' and transport_grpc` |
| V-12 | Redis pub/sub needs Redis | `redis_pubsub` | `db_redis` |
| V-13 | gRPC streaming needs the gRPC overlay | `streaming_grpc` | `api_grpc` |
| V-14 | SSE streaming needs REST | `streaming_sse` | `api_rest` |

V-2 and V-14 are always satisfied in v1 because `api_rest` is a computed `true`. They are encoded now so they hold if REST ever becomes optional.

Rules are also restated as `requires` / `conflicts` on the individual option entries so a single option carries its own preconditions. `validation_rules` is the canonical list; `requires` blocks must not contradict it.

### 4.1 `services_config` rules (`scope: services_config`)

V-15..V-20 (`scope: services_config`, added Phase 3) are structural checks on a multi-service answers file's `services_config` map. They are **not** Copier validators; `validate_registry.py` `validate_services_config(answers)` evaluates them (plus a per-service replay of V-2..V-14 over each service's effective submap) and the `msvc-gen` CLI calls it before an orchestrated `monorepo`/`multi_repo` run (D-036). Full schema and merge order: `docs/services-config-schema.md`.

| ID | Rule | `applies_when` | Predicate (must hold) |
| --- | --- | --- | --- |
| V-15 | Every `services_config` key is a declared service | `topology != 'single'` | every key of `services_config` appears verbatim in `service_names` |
| V-16 | Names stay distinct after `-`→`_` normalization | `topology != 'single'` | `service_names` map to distinct `python_package` names |
| V-17 | Submap carries only known per-service keys | `topology != 'single'` | every key of every submap is in the per-service key list (services-config-schema §2.2) |
| V-18 | gRPC transport needs a gRPC server | `topology != 'single' and transport_grpc` | at least one service's effective submap enables `api_grpc` |
| V-19 | A multi-service topology has ≥1 service | `topology != 'single'` | `service_names` is non-empty |
| V-20 | Service names are kebab-case | `topology != 'single'` | every `service_names` entry matches `^[a-z][a-z0-9-]{1,48}$` |

V-1 (`transport_grpc or transport_rabbitmq` when `topology != 'single'`) and V-11 (`tests_contract` needs multi-service + gRPC transport) stay `scope: copier` validators on the topology keys and are checked once at the top level, not per service.

---

## 4a. Image resolution (`image_resolution`, `compose_image_pins`)

Most compose images are pinned directly on the option's `compose_services` entry. When an image tag depends on more than one answer, the choice is encoded as an `image_resolution` rule instead so it stays deterministic and auditable.

- `image_resolution`: ordered list of `{ id, description, service, when, image_ref, else_image_ref }`. The derivation script evaluates `when` (a Jinja boolean over answers); the first matching rule for a given `service` wins. `image_ref` / `else_image_ref` point into `compose_image_pins`.
- `compose_image_pins`: map of `ref -> { image, owner, as_of, ... }`. One owner per row (D-023). A row with `as_of: null` is not yet pinned by its owner and must be resolved before that overlay ships.
- v0 has one rule, IR-1: the single compose `redis` service resolves to `redis_stack` when `db_redis and langgraph and langgraph_checkpoint == 'redis'` (D-015), else `redis_plain`. V-9 guarantees `db_redis` is on whenever the checkpoint store is redis, so there is always exactly one redis service to resolve. The `redis/redis-stack` tag is owned by the Data Layer Engineer (D-023) and carries `as_of: null` until Phase 2.

---

## 5. Determinism and ordering rules baked into the schema

- Independent on/off overlays are boolean keys; `multiselect` is not used for them (D-020). `service_names` is a `yaml`-typed free list, not `multiselect`, because its values are open-ended.
- Enum values are frozen strings. Changing a spelling requires a `migrations` entry.
- `default` values must keep old answers files valid and behavior-stable.
- `overlay_order` is append-only. Every entry maps 1:1 to an option `overlay_id`.
- Version pins in `python_deps`, `compose_services`, and `compose_image_pins` are exact and carry an `as_of` date. Pins are frozen at v0; bumps are an explicit task (D-019).

---

## 6. Derivation scripts

Both are built (Phase 2, D-028). Pure, offline, deterministic. `copier.yml` is
generated and committed; CI runs `gen_copier_yml.py --check` and fails on drift.

### 6.1 `scripts/gen_copier_yml.py`

- Input: `registry.yaml` (path arg, default `./registry.yaml`).
- Output: `copier.yml` (default `./copier.yml`). `--stdout` prints; `--check`
  exits 1 on drift; `--allow-missing` is a no-op kept for CI compatibility.
- Emits, in this fixed order:
  1. header comment (no timestamp), then Copier settings: `_subdirectory`,
     `_templates_suffix: .jinja`, `_answers_file` (from `meta.answers_file`),
     `_min_copier_version` (from `meta.copier_min_version`).
  2. `_exclude`: the eight Copier defaults (re-listed, because defining `_exclude`
     replaces them) then `/_fragments`, `/_fragments/**`. Patterns are
     destination-relative (after `_subdirectory` strips `template/`) and follow
     gitignore semantics: an unanchored bare name matches at ANY depth, so the
     fragment dir is anchored (`/_fragments`), never a bare `_fragments`. `includes/`
     and `overlays/` are OUTSIDE `_subdirectory` and are NOT excluded - a bare
     `overlays` would drop the rendered `tests/overlays/` boots-test subtree.
  3. `_skip_if_exists` from `meta.skip_if_exists` (omitted if empty).
  4. `_tasks` from top-level `tasks` (base) plus any per-option `tasks` (each
     folded to `{{ (gate) and (extra_when) }}`). List-form argv (D-012).
  5. `_migrations` from `migrations` (omitted when empty).
  6. one question per `options` entry, ordered by `groups[group].order` then by
     the order the option appears in `registry.yaml`, grouped under a
     `# ---- <group> ----` comment. Each question carries `type`, `help` (the
     `prompt`, unless the option is computed / `prompt: "computed"`), `choices`
     (dict or list form, registry order preserved), `multiselect`, `default`
     (omitted when null), `when` (`false` for a computed key, else the quoted
     expression), and a compiled `validator`.
- Validator compilation, per question key:
  * a structured `option.validator: { regex, message }` becomes
    `{% if not (KEY | regex_search('REGEX')) %}MESSAGE{% endif %}`.
  * every `validation_rules` entry whose `attach_to` names the key becomes
    `{% if (APPLIES_WHEN) and not (EXPR) %}MESSAGE{% endif %}`.
  * per-option `requires` / `conflicts` are compiled ONLY for a key that no
    `validation_rules` entry attaches to (v0: only `embedding_vector_size`), so
    the "restated" preconditions do not produce near-duplicate clauses. A
    `requires` on a `bool` option is guarded with `{% if KEY and ... %}`.
  * clauses are joined into one `>-` folded block, blank line between them.
- Guarantees: no network, no randomness, stable key ordering, idempotent. The
  generated `copier.yml` does not change the zero-overlay SERVICE output; it does
  make `.copier-answers.yml` complete (every gate boolean recorded), which
  `copier update` needs.

### 6.2 `scripts/validate_registry.py`

- `--prev PATH` / `REGISTRY_PREV` env: a previous `registry.yaml` to diff enum
  values against (optional; the check is skipped, with a note, when absent).
- Checks: required sections; `overlay_order` ids map 1:1 to an option
  `overlay_id` and vice versa, no duplicates; option map key equals its `key`;
  `group` refs exist; every identifier in a `when` / `requires` / `conflicts` /
  `gate` / `validation_rules` / `image_resolution` expression is a defined option
  key or a known computed key (string literals are ignored); `validation_rules`
  ids unique with `expr` + `message`, `attach_to` targets defined;
  `image_resolution` `image_ref` / `else_image_ref` resolve into
  `compose_image_pins`; `compose_image_pins` rows carry `owner` and an `image`
  key (`as_of: null` allowed = not yet pinned); `python_deps` are exact pins with
  an `as_of`; `default`s type-match the option `type` and, for `choices`, are a
  valid choice value; `registry_version` option default equals
  `meta.registry_version`; and, when `--prev` is given, no `choices` value was
  removed or renamed without a `migrations` entry.
- Exit 0 clean, 1 with a problem list, 2 on usage error.
