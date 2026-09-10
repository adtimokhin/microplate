# Non-interactive generation

Scope milestone 9. Every question the generator can ask is answerable from a
file or a flag, with **no prompts**. This is the mode CI and any wrapper script
must use.

## How "no prompts" is guaranteed

`msvc_gen/cli.py` calls Copier with `defaults=True` on both `new` and `update`.
With that flag Copier never opens a prompt: it takes the supplied answer, or the
question's registry default, and **a question that has neither is a hard error**,
not a prompt. So a non-interactive run either succeeds with a fully determined
answer set or fails loudly - it never blocks waiting for input and never guesses
(scope §6).

Exactly one prompted question in `registry.yaml` has no default:

| Key | Why | You must supply it |
| --- | --- | --- |
| `service_name` | the service's identity; there is no sane default | always |

Everything else has a registry default, so a minimal run is just
`--data service_name=...`. `service_slug` and `python_package` are computed from
`service_name` (`when: false`, never prompted); pass them only to override the
derivation.

## Input surface

### `msvc-gen new` / `msvc-gen update`

```
msvc-gen new    --output DIR [--answers-file FILE] [--data KEY=VALUE ...] \
                [--vcs-ref REF] [--template-src SRC] [--skip-tasks] [--force] [--quiet]

msvc-gen update --output DIR [--answers-file FILE] [--data KEY=VALUE ...] \
                [--vcs-ref REF] [--skip-tasks] [--conflict {inline,rej}] [--quiet]
```

| Flag | Meaning |
| --- | --- |
| `-o, --output DIR` | **required**; target directory for the service (or, for a multi-service topology, the directory that holds `services/<svc>/` + the root layer) |
| `--answers-file FILE` | YAML mapping of answers. Copier-internal keys (`_src_path`, `_commit`, any `_`-prefixed key) are stripped on load, so a generated `.copier-answers.yml` can be fed straight back in |
| `--data KEY=VALUE` | one answer; repeatable. The value is parsed as YAML (`true`, `42`, `[a, b]`, `{"k": 1}` all work) |
| `--vcs-ref REF` | template git ref - tag, branch, or commit. Default `main` (pre-v1) or `$MSVC_GEN_VCS_REF`. The CLI **always** passes an explicit ref; it never uses Copier's "highest PEP 440 tag" default (D-012) |
| `--template-src SRC` | template path or git URL. Default: an auto-detected source checkout, else `$MSVC_GEN_TEMPLATE_SRC`, else the packaged private-repo URL |
| `--skip-tasks` | do not run the post-generation `uv lock` task (run `uv lock` / `uv sync` yourself) |
| `--force` | overwrite existing files without asking (`new` only in practice) |
| `--conflict {inline,rej}` | `update` only: how to mark unresolved hunks. `rej` writes `.rej` files instead of inline `<<<<<<<` markers - easier to detect in CI |
| `--dry-run` | render nothing to disk |
| `--quiet` | suppress Copier's file-by-file output |

There is no `msvc-gen` flag per registry key. Component selection is entirely
`--data` / `--answers-file`, so the flag surface never drifts from the registry
(scope §5, §6).

### Raw Copier (equivalent, no CLI)

```sh
copier copy --defaults --trust --data-file answers.yml \
  --vcs-ref v0.4.0 --skip-tasks <template-src> ./my-service
```

`msvc-gen` adds only: explicit `--vcs-ref` handling, `_`-key stripping, the
`--data` / `--answers-file` merge, and the multi-service orchestration
(`topology != single`). For a single-service project the two are interchangeable.
Multi-service (`monorepo` / `multi_repo`) needs `msvc-gen` - raw `copier copy`
renders one service tree only.

## Precedence

Highest wins:

1. `--data KEY=VALUE` (last occurrence of a repeated key wins)
2. `--answers-file` entries
3. `registry.yaml` question default

`cli.py` builds the answer set as `answers_file` then `--data` on top
(`_merge_data`); Copier then fills every still-unset question from its registry
default. Verified: `--answers-file` with `service_name: from-file, db_postgres:
true` plus `--data service_name=from-data --data db_postgres=false` produces a
project named `from-data` with `db_postgres: false`.

## Validation, not inference

The generator rejects an invalid or incomplete answer set; it never repairs one.

- Cross-key rules (`registry.yaml` `validation_rules`, e.g. `embedding_pipeline`
  requires `db_qdrant`; `langgraph` requires a checkpoint store) are enforced by
  Copier validators derived from the registry. A violation aborts the run with
  the rule's message.
- For multi-service, `msvc_gen/topology.py` additionally replays the per-service
  rules (V-15..V-20 + V-2..V-14 per effective submap) via
  `scripts/validate_registry.py` before any render.
- A wrapper (form, wizard, internal tool) **must** emit a complete, valid
  answers file matching the registry schema. "Complete" = `service_name` plus
  any answer that differs from the registry default plus any answer a
  `validation_rule` forces. It is fine to emit every key explicitly; the
  round-tripped `.copier-answers.yml` is exactly that.

## Supplying `services_config` for `monorepo` / `multi_repo`

`services_config` is a JSON object `{"<service-name>": {<submap>}}` whose keys
must be exactly the `service_names` entries (a missing name renders as an
all-defaults service; an extra name is an error).

**In an answers file** - a native nested mapping:

```yaml
service_name: shop-platform
topology: monorepo
service_names: [api, worker]
transport_grpc: true
transport_rabbitmq: true
tests_contract: true
services_config:
  api:
    api_grpc: true
    db_postgres: true
    tool_scaffold: true
  worker:
    messaging_rabbitmq: true
    db_redis: true
```

**Via `--data`** - a JSON string (parsed as YAML, so JSON is accepted):

```sh
msvc-gen new -o ./mesh --vcs-ref v0.4.0 \
  --data service_name=mesh \
  --data topology=monorepo \
  --data 'service_names=[api, worker]' \
  --data transport_grpc=true \
  --data 'services_config={"api": {"api_grpc": true}, "worker": {"db_redis": true}}'
```

Shared-vs-per-service split (`docs/services-config-schema.md`):

- **Top level only** (mesh-wide fabric): `topology`, `service_names`,
  `services_config`, `transport_grpc`, `transport_rabbitmq`, `tests_contract`,
  plus `license`, `ci`, `iac`, `docker` and the repo-level `service_name`.
- **Per-service submap only**: the overlay gates (`db_*`, `api_grpc`,
  `llm_*`, `langchain`, `langgraph`, `otel_tracing`, ...) minus the two
  transports, plus their sub-options (`redis_pubsub`, `embedding_backend`,
  `langgraph_checkpoint`, `llm_response_mode`, ...) and per-service
  `tests_unit` / `tests_integration` / `docker`.

Each service's effective answer set is
`registry defaults <- services_config[svc] <- shared passthrough keys <- forced
identity`, and each service renders as a standalone `single` project (its own
`pyproject.toml`, `uv.lock`, tests, `Dockerfile`, `.copier-answers.yml`). Two
services can pick entirely different stacks.

Note: for a multi-service run, `transport_grpc` / `transport_rabbitmq` are read
straight from your answers (default `false`); the templated
"`true` when `topology != single`" registry default only applies inside a Copier
render, not the topology orchestrator. Set at least one transport explicitly -
V-1 is enforced and will reject a run with neither.

## Curated example answers files

`ci/answers/` carries complete, valid sets used by `check_determinism.py`,
`verify_update.sh`, and the docs:

| File | Shape |
| --- | --- |
| `zero-overlay.yml` | plain FastAPI service, no overlays |
| `otel-only.yml` | one overlay (OpenTelemetry) |
| `datastore-postgres-redis.yml` | PostgreSQL + Redis + Redis pub/sub |
| `rag-backend.yml` | Qdrant + OpenAI + LangChain (+ retrieval) + embedding pipeline - a retrieval backend an agent queries |
| `agent-langgraph.yml` | PostgreSQL + Redis + a LangGraph graph checkpointed to Postgres |
| `monorepo-2svc.yml` | two-service monorepo (`api` + `worker`) with gRPC + RabbitMQ transport and contract tests |
| `sample-agent-service.yml` | Postgres + Redis + RabbitMQ + gRPC + OpenTelemetry |
