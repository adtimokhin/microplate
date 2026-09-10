# `services_config` submap schema

Version 0 draft. Owner of the content: TopologyEngineer (Phase 3, milestone 6).
Integrator: RegistryArchitect folds this into `docs/registry-schema.md` and
`scripts/validate_registry.py`.

Reference: D-005 (topology output is registry-selectable), D-017 (one root
answers file carries the whole map for `monorepo`; one answers file per repo for
`multi_repo`), overlay-contract §3.3 and §8.1, registry-schema.md §3 `topology`
group.

This document defines the exact shape of the `services_config` answer, which
registry keys a per-service submap may carry, how a submap is validated, what the
defaults are, and how a submap relates to the top-level answers.

---

## 1. What `services_config` is

`services_config` is answered only when `topology != 'single'`
(`when: "topology != 'single'"`, already in `registry.yaml`). It is a JSON object
(`type: json`, default `{}`):

```json
{
  "<service-name>": { <per-service submap> },
  "<service-name>": { <per-service submap> }
}
```

- Each top-level property name is a **service name** and MUST appear verbatim in
  the `service_names` answer. `service_names` is the authoritative, ordered,
  frozen list; `services_config` only attaches per-service answers to names that
  list already declares. The generator never invents a name and never derives one
  from `services_config` alone.
- A name present in `service_names` but absent from `services_config` is legal:
  that service renders with an all-defaults submap (a plain base FastAPI service,
  no optional overlays).
- A name present in `services_config` but absent from `service_names` is a
  validation error (V-T1 below). No silent drop, no silent add.
- `services_config` is **not recursive**: a submap may not contain
  `services_config`, `service_names`, or `topology`.

### 1.1 Service-name rules

Each service name is validated with the same regex the top-level `service_name`
uses: `^[a-z][a-z0-9-]{1,48}$` (lowercase, digits, hyphen; starts with a
letter). From a service name `svc` the generator derives, per service, exactly as
the base does for a single service:

| Derived value | Rule |
| --- | --- |
| `service_slug` | `slugify(svc)` (already hyphen-clean, so `== svc`) |
| `python_package` | `svc \| replace('-', '_')` |
| `service_name` (in that service's own settings/answers) | `svc` |

Two service names that slugify to the same `python_package` (`foo-bar` and
`foo_bar` cannot both occur because underscore is not allowed in a name; `foo-bar`
alone is fine) are a validation error (V-T2). Names are compared case-sensitively;
the regex already forces lower case.

---

## 2. Top-level vs per-service: which keys live where

A key is either **shared** (answered once at the top level, applies to the whole
monorepo / every repo in a `multi_repo` set) or **per-service** (answered inside
each submap, may differ between services). A key is never both.

### 2.1 Shared keys (top level only, NOT allowed in a submap)

| Key | Why it is shared |
| --- | --- |
| `topology` | Defines the whole output layout. |
| `service_names` | The service roster. |
| `services_config` | The map itself. No recursion. |
| `transport_grpc`, `transport_rabbitmq` | The inter-service transport fabric. Every service in the mesh must agree on how peers talk, so the transport wiring overlay is enabled for all services uniformly. A service still chooses whether it *exposes* its own gRPC server (`api_grpc`, per-service) or is a pure client. See §4. |
| `tests_contract` | Guards the shared `proto/` surface across services (buf breaking + lint, or the descriptor-set snapshot). One proto tree, one contract job. |
| `service_name` | The repo / project name (root `README.md`, root compose `name:`, `multi_repo` repo slug). Distinct from the per-service names in `service_names`. |
| `license` | One license for the repo. |
| `ci` | `monorepo`: one root workflow that fans out over the service folders. `multi_repo`: one workflow per repo, same value. |
| `iac` | Reserved (D-022); repo-level. |
| `logging_structured` | Computed `true` (D-026); base-level, identical everywhere. |
| `python_version` | Computed `3.12` (D-004). |
| `api_rest` | Computed `true` (D-018). |
| `healthchecks` | Computed `true`. |
| `registry_version`, `selected_overlays` | Computed / audit. `selected_overlays` is recomputed *per service* during that service's render from its effective submap; it is not meaningful at the top level for a multi-service topology. |

### 2.2 Per-service keys (allowed in a submap)

Every overlay gate and its sub-options, plus the per-service testing and docker
choices. A submap may carry any subset of:

```
api_grpc
streaming_sse
streaming_grpc
tool_scaffold
mcp_server
db_postgres
db_mongodb
db_redis
redis_pubsub
db_qdrant
messaging_rabbitmq
llm_openai
llm_anthropic
prompt_management
langchain
langchain_retrieval
embedding_pipeline
embedding_backend
embedding_vector_size
langgraph
langgraph_checkpoint
langsmith
otel_tracing
tests_unit
tests_integration
llm_response_mode
docker
```

This is exactly: the 20 `overlay_order` ids, minus `transport_grpc` and
`transport_rabbitmq` (shared, §2.1), plus the sub-option keys
(`redis_pubsub`, `langchain_retrieval`, `embedding_backend`,
`embedding_vector_size`, `langgraph_checkpoint`, `llm_response_mode`), plus
`tests_unit`, `tests_integration`, `docker`.

Any key not in this list appearing in a submap is a validation error (V-T3) -
no unknown keys, no shared keys, no typos pass silently.

**Yes, two services in one monorepo may select different databases** (`api` picks
`db_postgres`, `worker` picks `db_mongodb`), different AI stacks, different
streaming modes, different `otel_tracing`. Each service's `pyproject.toml`,
`docker-compose` service block, `.env.example`, settings, health checks, and
tests are assembled from that service's effective submap alone, exactly as a
`single` service would be. **Yes, that means per-service Python dependency sets**
- there is one `pyproject.toml` + one `uv.lock` per service folder, never a
shared root lockfile.

---

## 3. Defaults and the effective submap

For each service `svc` in `service_names`, the generator computes an **effective
submap**:

1. Start from the registry defaults for every per-service key (the same
   `default:` values a `single` render uses: `db_postgres=false`, `tests_unit=true`,
   `docker=true`, `embedding_backend='fastembed'`, ...).
2. Overlay `services_config[svc]` on top (a present key wins; an absent key keeps
   the registry default).
3. Inject the derived identity values from §1.1 (`service_name`, `service_slug`,
   `python_package`).
4. Inject the shared keys from §2.1 that a `single` render also needs
   (`api_rest`, `healthchecks`, `logging_structured`, `python_version`,
   `license`, `ci`, `docker`-adjacent). `transport_grpc` / `transport_rabbitmq`
   are passed through from the top level so the transport overlay renders in
   every service (see §4).
5. `tests_contract` is **not** injected into the per-service render. It is a
   root-level job (§2.1); a per-service tree never contains a contract-test
   file.

The effective submap is a complete, valid `single`-style answer set. Rendering
service `svc` is then identical to a `single` generation with those answers, into
that service's destination (`services/<svc>/` for `monorepo`, a separate repo for
`multi_repo`).

### 3.1 Determinism

- Services are always processed in `service_names` list order. That order is
  frozen for a given answers file (overlay-contract §8.2 forbids reordering a
  frozen list without a migration).
- The effective submap is built by a pure dict merge over a fixed key list (the
  §2.2 list, in that written order). No iteration over unordered answer data
  reaches an output path.
- Rendering the same root answers file twice produces byte-identical trees for
  every service folder and the root layer.

---

## 4. Transport wiring and per-service gRPC

`transport_grpc` / `transport_rabbitmq` are shared (§2.1). When on:

- **Every** service gets the transport overlay's client-side wiring: a generated
  client stub per peer service (`transport_grpc`) or a shared
  exchange/queue/publisher/consumer module (`transport_rabbitmq`), plus a
  discovery-by-name config entry per peer. Peer host defaults:
  - `monorepo`: the peer's compose service name, which is the peer's
    `service_slug` (e.g. `http://worker:8000`, `worker:50051`).
  - `multi_repo`: an env var per peer (`APP_PEER_<PEER>_URL`) with a default of
    the peer slug; real deployments override.
- A service **exposes** its own gRPC server only if its submap sets `api_grpc`
  (per-service). `transport_grpc` does not force `api_grpc` on a service - a
  service can be a pure gRPC client of its peers. But if **no** service in the
  mesh sets `api_grpc` while `transport_grpc` is on, that is validation error
  V-T4 (a gRPC transport with nothing to call).
- `tests_contract` requires `transport_grpc` (V-11, unchanged) and therefore at
  least one `api_grpc` service (V-T4 already guarantees it).

`transport_rabbitmq` has no per-service server/client split: a service publishes
and/or consumes on the shared topology; the overlay ships both sides and the
service uses what it needs.

RabbitMQ is the default transport when `topology != 'single'` (scope §4.3): the
derivation / validation layer SHOULD default `transport_rabbitmq` to `true` when
`topology != 'single'` and the answers file sets neither transport, rather than
failing V-1 outright. (RegistryArchitect: confirm whether this is a `copier.yml`
computed default or a CLI-side fill; either keeps V-1 satisfied.)

---

## 5. Validation

Every effective submap (§3) is validated against the **same** registry option
rules as a standalone `single` answer set: the `validation_rules` block V-2
through V-14, minus the four that are inherently topology-level
(V-1 `topology`, V-11 `tests_contract`, and any rule whose `applies_when` names
`topology`/`service_names`/`transport_*`), which are checked once at the top
level.

So, per service, these still apply (message text unchanged from
registry-schema.md §4):

| Rule | Holds per service |
| --- | --- |
| V-2 | `tool_scaffold` needs `api_rest or api_grpc` |
| V-3 | `mcp_server` needs `tool_scaffold or api_grpc` |
| V-4 | `embedding_pipeline` needs `db_qdrant` |
| V-5 | `langgraph` needs `db_postgres or db_redis` |
| V-6 | `langchain_retrieval` needs `langchain and db_qdrant` |
| V-7 | `langchain` needs `llm_openai or llm_anthropic` |
| V-8 | openai embedding backend needs `llm_openai` |
| V-9 | `langgraph_checkpoint` store must be enabled |
| V-10 | `langsmith` needs `llm_openai or llm_anthropic` |
| V-12 | `redis_pubsub` needs `db_redis` |
| V-13 | `streaming_grpc` needs `api_grpc` |
| V-14 | `streaming_sse` needs `api_rest` |

New topology-level rules to add to `validation_rules` (ids `V-T*` are a
placeholder; RegistryArchitect assigns final ids and `attach_to`):

| ID | Rule | `applies_when` | `expr` (must hold) |
| --- | --- | --- | --- |
| V-T1 | Every `services_config` key is a declared service | `topology != 'single'` | every key of `services_config` is in `service_names` |
| V-T2 | Service names are distinct after package normalization | `topology != 'single'` | `service_names \| map('replace', '-', '_') \| list \| unique \| length == service_names \| length` |
| V-T3 | Submap carries only known per-service keys | `topology != 'single'` | every key of every submap is in the §2.2 list |
| V-T4 | gRPC transport needs at least one gRPC server | `topology != 'single' and transport_grpc` | at least one service's effective submap has `api_grpc` |
| V-T5 | At least one service | `topology != 'single'` | `service_names \| length >= 1` |
| V-T6 | Names match the regex | `topology != 'single'` | every `service_names` entry matches `^[a-z][a-z0-9-]{1,48}$` |

V-1 (`transport_grpc or transport_rabbitmq` when `topology != 'single'`) is
unchanged and stays attached to `topology` / `transport_grpc` /
`transport_rabbitmq`. See §4 for the RabbitMQ-default softening of V-1.

### 5.1 Where validation runs

- **Interactive / `copier.yml`**: the derivation script attaches V-1, V-T5, V-T6
  as Copier `validator` blocks on `topology` / `service_names`. `services_config`
  is a `json` free-form answer; Copier cannot deep-validate it, so V-T1..V-T4 and
  the per-submap V-2..V-14 replay run in:
- **`scripts/validate_registry.py` + a new `validate_services_config(answers)`
  helper** (RegistryArchitect owns the integration). The CLI (`msvc_gen`) calls
  it before invoking Copier for a `monorepo` / `multi_repo` generation and exits
  non-zero with the failing rule messages. This keeps the "complete, valid
  answers file" contract (scope §6) for multi-service too: the generator does not
  guess, it rejects.

---

## 6. Answers-file examples

### 6.1 `monorepo`, two services, gRPC transport

```yaml
# root answers file passed to `msvc-gen new`
service_name: order-platform
topology: monorepo
service_names: [api, worker]
transport_grpc: true
transport_rabbitmq: false
tests_contract: true
services_config:
  api:
    api_grpc: true          # exposes a gRPC server the worker calls
    db_postgres: true
    tool_scaffold: true
  worker:
    db_postgres: true
    messaging_rabbitmq: true
    otel_tracing: true
```

Renders:

```
order-platform/
  .copier-answers.yml        # root: topology, service_names, services_config, shared keys
  docker-compose.yml         # root: app-per-service + backing services, wired by name
  README.md                  # root
  proto/                     # shared contracts (api_grpc + transport_grpc)
  buf.yaml                   # tests_contract
  .github/workflows/ci.yml   # root: matrix over services + proto-contract job
  services/
    api/                     # a complete single-style tree: pyproject, uv.lock, tests, Dockerfile
      .copier-answers.yml    # per-service (see D-017 amendment note below)
      order_platform_api/... # python_package = "api" -> package dir "api"? see 6.3
    worker/
      ...
```

### 6.2 `multi_repo`, same roster

`msvc-gen new` runs Copier once per service name, each into its own output
directory (`--output` gains a per-service suffix, or the CLI takes an output
*parent* and makes `order-platform-api/`, `order-platform-worker/`). Each repo:

```
order-platform-api/
  .copier-answers.yml        # this repo's own run: service_name=api + effective submap + shared keys
  docker-compose.yml         # this service + its own backing services only
  proto/                     # the SAME shared contracts, emitted identically into every repo
  pyproject.toml / uv.lock
  ...
```

The shared `proto/` tree is generated from the top-level `service_names` +
`transport_grpc` and is byte-identical across the repos in one generation. A
consistency check (`buf breaking` against the sibling repo, or a descriptor-set
diff) is the `tests_contract` job.

### 6.3 Package directory name

Per service, `python_package = svc | replace('-', '_')`. For `svc = api` the
package dir is `api/`. That is a very generic top-level package name inside
`services/api/`. Options for RegistryArchitect / Lead to pick:

- **A (simple, recommended)**: `python_package = svc_normalized` exactly. Package
  dir is `services/api/api/`. Import is `import api.main`. Acceptable because each
  service folder is its own project root with its own `pyproject.toml`.
- **B**: prefix with the repo slug: `python_package =
  "{{ service_slug }}_{{ svc }}" | replace('-', '_')` ->
  `services/api/order_platform_api/`. Avoids a bare `api` package but couples the
  import path to the repo name and lengthens every overlay path.

Recommend **A**. It keeps every overlay's `template_paths` unchanged (they are
already `{{ python_package }}`-rooted) and the per-service render is then
literally a `single` render with `python_package=api`.

---

## 7. Relationship to `.copier-answers.yml` (D-017) and open mechanism question

D-017 as written says `monorepo` is **one** Copier run (a `{% yield %}` loop over
`service_names`) with **one** root `.copier-answers.yml` and **no** per-service
answers files.

The schema above is mechanism-neutral for its *content* (the submap shape,
defaults, validation are the same either way), but the *consumption* differs:

- **Single-run `{% yield %}` mechanism (D-017 literal)**: every overlay's gated
  directory (`template/{% if db_postgres %}{{ python_package }}{% endif %}/...`)
  must change its gate to read `services_config[<yield var>]` when rendering
  inside the per-service loop and the top-level answer otherwise. That is a
  base-structure change touching the frozen base root (D-016) and all 11 shipped
  overlays' gate expressions. TopologyEngineer has raised this with the Lead as a
  blocker (see STATUS.md Phase 3).
- **Orchestrated multi-render mechanism (recommended amendment)**: the CLI runs a
  `single`-style Copier render per service into `services/<svc>/`, each with its
  own `.copier-answers.yml`, then renders a thin root layer (root compose,
  README, `proto/`, `buf.yaml`, CI) from a root `.copier-answers.yml` that
  carries `topology`, `service_names`, `services_config`, and the shared keys as a
  manifest. `copier update` re-runs per service folder + re-renders the root
  layer. Zero base changes, zero overlay changes, `single` stays byte-identical.
  Requires amending D-017 to allow per-service `.copier-answers.yml` alongside
  the root manifest.

This document does not decide the mechanism; it is scoped to the submap schema.
The submap keys, defaults, and validation rules in §2-§5 stand under either
mechanism.
